"""PDF downloader service for parliament declarations."""

import hashlib
import logging
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from .base_scraper import BaseScraperClient
from .constants import MAX_PDF_SIZE_MB, PDF_CHUNK_SIZE
from .exceptions import PothenDownloadError, PothenValidationError
from .schemas import DeclarationEntry, PDFMetadata

logger = logging.getLogger(__name__)


class PDFDownloader:
    """Service for downloading and managing PDF declaration files."""

    def __init__(self, scraper_client: BaseScraperClient, download_dir: Path):
        self.scraper = scraper_client
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

    def generate_filename(self, declaration: DeclarationEntry) -> str:
        """Generate a standardized filename for a declaration PDF."""
        # Use the original filename but ensure it's safe
        original_filename = Path(urlparse(str(declaration.pdf_url)).path).name

        # Sanitize filename while preserving important parts
        if original_filename.endswith(".pdf"):
            return original_filename
        else:
            # Fallback filename generation
            safe_name = (
                f"{declaration.last_name}_{declaration.first_name}_{declaration.year}"
            )
            if declaration.file_id:
                safe_name = f"{safe_name}_{declaration.file_id}"
            return f"{safe_name}.pdf"

    def get_download_path(self, declaration: DeclarationEntry) -> Path:
        """Get the full download path for a declaration PDF."""
        filename = self.generate_filename(declaration)

        # Organize by year
        year_dir = self.download_dir / str(declaration.year)
        year_dir.mkdir(exist_ok=True)

        return year_dir / filename

    def is_already_downloaded(self, declaration: DeclarationEntry) -> bool:
        """Check if a declaration PDF is already downloaded."""
        filepath = self.get_download_path(declaration)
        return filepath.exists() and filepath.stat().st_size > 0

    def download_declaration(
        self, declaration: DeclarationEntry, force_redownload: bool = False
    ) -> PDFMetadata:
        """Download a single declaration PDF."""
        filepath = self.get_download_path(declaration)

        # Check if already downloaded
        if not force_redownload and self.is_already_downloaded(declaration):
            logger.info(f"PDF already exists: {filepath}")
            return PDFMetadata(
                url=declaration.pdf_url,
                filepath=filepath,
                filesize_bytes=filepath.stat().st_size,
                content_hash=self._calculate_file_hash(filepath),
            )

        logger.info(f"Downloading {declaration.pdf_url} to {filepath}")

        try:
            # Download the file
            downloaded_path = self.scraper.download_file(
                url=str(declaration.pdf_url),
                filepath=filepath,
                chunk_size=PDF_CHUNK_SIZE,
                max_size_mb=MAX_PDF_SIZE_MB,
            )

            # Validate the downloaded file
            self._validate_pdf_file(downloaded_path)

            # Create metadata
            metadata = PDFMetadata(
                url=declaration.pdf_url,
                filepath=downloaded_path,
                filesize_bytes=downloaded_path.stat().st_size,
                content_hash=self._calculate_file_hash(downloaded_path),
            )

            logger.info(
                f"Successfully downloaded PDF: {downloaded_path} ({metadata.filesize_mb:.2f} MB)"
            )
            return metadata

        except Exception as e:
            raise PothenDownloadError(
                f"Failed to download {declaration.pdf_url}: {str(e)}"
            ) from e

    def download_declarations(
        self,
        declarations: List[DeclarationEntry],
        force_redownload: bool = False,
        max_downloads: Optional[int] = None,
    ) -> List[PDFMetadata]:
        """Download multiple declaration PDFs."""
        results = []
        downloaded_count = 0

        for i, declaration in enumerate(declarations):
            if max_downloads and downloaded_count >= max_downloads:
                logger.info(f"Reached maximum downloads limit: {max_downloads}")
                break

            try:
                logger.info(
                    f"Processing declaration {i+1}/{len(declarations)}: {declaration.full_name}"
                )

                metadata = self.download_declaration(declaration, force_redownload)
                results.append(metadata)
                downloaded_count += 1

            except Exception as e:
                logger.error(
                    f"Failed to download declaration for {declaration.full_name}: {str(e)}"
                )
                continue

        logger.info(
            f"Downloaded {downloaded_count} PDFs out of {len(declarations)} declarations"
        )
        return results

    def _validate_pdf_file(self, filepath: Path) -> None:
        """Validate that the downloaded file is a valid PDF."""
        if not filepath.exists():
            raise PothenValidationError(f"Downloaded file does not exist: {filepath}")

        if filepath.stat().st_size == 0:
            raise PothenValidationError(f"Downloaded file is empty: {filepath}")

        # Check PDF magic number
        try:
            with open(filepath, "rb") as f:
                header = f.read(4)
                if not header.startswith(b"%PDF"):
                    raise PothenValidationError(f"File is not a valid PDF: {filepath}")
        except IOError as e:
            raise PothenValidationError(
                f"Cannot read downloaded file: {filepath}"
            ) from e

    def _calculate_file_hash(self, filepath: Path) -> str:
        """Calculate SHA256 hash of a file."""
        hash_sha256 = hashlib.sha256()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_sha256.update(chunk)
            return hash_sha256.hexdigest()
        except IOError as e:
            logger.warning(f"Could not calculate hash for {filepath}: {str(e)}")
            return ""

    def get_download_stats(self) -> dict:
        """Get statistics about downloaded files."""
        stats = {"total_files": 0, "total_size_mb": 0.0, "by_year": {}}

        for year_dir in self.download_dir.iterdir():
            if year_dir.is_dir() and year_dir.name.isdigit():
                year = year_dir.name
                year_files = list(year_dir.glob("*.pdf"))
                year_size = sum(f.stat().st_size for f in year_files)

                stats["by_year"][year] = {
                    "files": len(year_files),
                    "size_mb": year_size / (1024 * 1024),
                }

                stats["total_files"] += len(year_files)
                stats["total_size_mb"] += year_size / (1024 * 1024)

        return stats
