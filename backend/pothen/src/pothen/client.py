"""Main POTHEN client for orchestrating the scraping workflow."""

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from .base_scraper import BaseScraperClient
from .constants import DECLARATIONS_LANDING_URL
from .exceptions import PothenError
from .parliament_parser import ParliamentParser
from .pdf_downloader import PDFDownloader
from .pdf_parser import PDFTextExtractor
from .schemas import (
    DeclarationEntry,
    ParsedDeclarationContent,
    PDFMetadata,
    ScrapingSession,
    YearlyDeclarations,
)

logger = logging.getLogger(__name__)


class PothenClient:
    """
    Main client for scraping Greek Parliament asset declarations.

    This client orchestrates the entire workflow:
    1. Parse parliament pages to find declaration links
    2. Download PDF files
    3. Extract text content from PDFs
    4. Provide structured access to the data
    """

    def __init__(
        self,
        download_dir: Union[str, Path] = "./pothen_downloads",
        timeout: int = 30,
        max_retries: int = 3,
        requests_per_minute: int = 10,
        user_agent: Optional[str] = None,
    ):
        """
        Initialize the POTHEN client.

        Args:
            download_dir: Directory to store downloaded PDFs
            timeout: HTTP request timeout in seconds
            max_retries: Maximum retry attempts for failed requests
            requests_per_minute: Rate limit for requests
            user_agent: Custom User-Agent string
        """
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)

        # Initialize components
        self.scraper = BaseScraperClient(
            timeout=timeout,
            max_retries=max_retries,
            requests_per_minute=requests_per_minute,
            user_agent=user_agent,
        )

        self.parser = ParliamentParser(self.scraper)
        self.downloader = PDFDownloader(self.scraper, self.download_dir)
        self.text_extractor = PDFTextExtractor()

        # Session tracking
        self.current_session: Optional[ScrapingSession] = None

        logger.info(
            f"POTHEN client initialized with download directory: {self.download_dir}"
        )

    def get_available_years(self) -> List[int]:
        """Get list of available declaration years from parliament website."""
        logger.info("Fetching available declaration years...")
        return self.parser.get_available_years(DECLARATIONS_LANDING_URL)

    def get_declarations(self, year: int) -> YearlyDeclarations:
        """
        Get all declarations for a specific year.

        Args:
            year: Year to fetch declarations for

        Returns:
            YearlyDeclarations object containing all found declarations
        """
        logger.info(f"Getting declarations for year {year}")
        return self.parser.parse_year_page(year)

    def get_declarations_multiple_years(
        self, years: List[int]
    ) -> Dict[int, YearlyDeclarations]:
        """
        Get declarations for multiple years.

        Args:
            years: List of years to fetch

        Returns:
            Dictionary mapping year to YearlyDeclarations
        """
        logger.info(f"Getting declarations for years: {years}")
        return self.parser.get_declarations_for_years(years)

    def download_pdfs(
        self,
        declarations: Union[YearlyDeclarations, List[DeclarationEntry]],
        force_redownload: bool = False,
        max_downloads: Optional[int] = None,
    ) -> List[PDFMetadata]:
        """
        Download PDF files for declarations.

        Args:
            declarations: YearlyDeclarations object or list of DeclarationEntry objects
            force_redownload: Whether to redownload existing files
            max_downloads: Maximum number of files to download

        Returns:
            List of PDFMetadata objects for downloaded files
        """
        if isinstance(declarations, YearlyDeclarations):
            declaration_list = declarations.entries
        else:
            declaration_list = declarations

        logger.info(f"Downloading {len(declaration_list)} PDF files...")
        return self.downloader.download_declarations(
            declaration_list, force_redownload, max_downloads
        )

    def extract_text(
        self, pdf_metadata: List[PDFMetadata]
    ) -> List[ParsedDeclarationContent]:
        """
        Extract text content from downloaded PDFs.

        Args:
            pdf_metadata: List of PDFMetadata objects

        Returns:
            List of ParsedDeclarationContent objects
        """
        logger.info(f"Extracting text from {len(pdf_metadata)} PDF files...")
        return self.text_extractor.extract_from_metadata_list(pdf_metadata)

    def scrape_year(
        self,
        year: int,
        download_pdfs: bool = True,
        extract_text: bool = True,
        max_downloads: Optional[int] = None,
    ) -> Dict[str, any]:
        """
        Complete scraping workflow for a single year.

        Args:
            year: Year to scrape
            download_pdfs: Whether to download PDF files
            extract_text: Whether to extract text from PDFs
            max_downloads: Maximum number of PDFs to download

        Returns:
            Dictionary containing all scraped data
        """
        logger.info(f"Starting complete scrape for year {year}")

        result = {
            "year": year,
            "declarations": None,
            "pdf_metadata": [],
            "extracted_content": [],
        }

        try:
            # 1. Get declarations
            declarations = self.get_declarations(year)
            result["declarations"] = declarations
            logger.info(f"Found {len(declarations.entries)} declarations for {year}")

            # 2. Download PDFs if requested
            if download_pdfs and declarations.entries:
                pdf_metadata = self.download_pdfs(
                    declarations, max_downloads=max_downloads
                )
                result["pdf_metadata"] = pdf_metadata
                logger.info(f"Downloaded {len(pdf_metadata)} PDFs for {year}")

                # 3. Extract text if requested
                if extract_text and pdf_metadata:
                    extracted_content = self.extract_text(pdf_metadata)
                    result["extracted_content"] = extracted_content
                    logger.info(
                        f"Extracted text from {len(extracted_content)} PDFs for {year}"
                    )

            return result

        except Exception as e:
            logger.error(f"Failed to scrape year {year}: {str(e)}")
            raise PothenError(f"Scraping failed for year {year}: {str(e)}") from e

    def scrape_multiple_years(
        self,
        years: List[int],
        download_pdfs: bool = True,
        extract_text: bool = True,
        max_downloads_per_year: Optional[int] = None,
    ) -> Dict[int, Dict[str, any]]:
        """
        Complete scraping workflow for multiple years.

        Args:
            years: List of years to scrape
            download_pdfs: Whether to download PDF files
            extract_text: Whether to extract text from PDFs
            max_downloads_per_year: Maximum number of PDFs to download per year

        Returns:
            Dictionary mapping year to scraped data
        """
        logger.info(f"Starting complete scrape for years: {years}")

        # Start session tracking
        self._start_session()

        results = {}

        for year in years:
            try:
                result = self.scrape_year(
                    year, download_pdfs, extract_text, max_downloads_per_year
                )
                results[year] = result

                # Update session stats
                if self.current_session:
                    self.current_session.years_scraped.append(year)
                    if result["declarations"]:
                        self.current_session.total_declarations_found += len(
                            result["declarations"].entries
                        )
                    if result["pdf_metadata"]:
                        self.current_session.total_pdfs_downloaded += len(
                            result["pdf_metadata"]
                        )

            except Exception as e:
                logger.error(f"Failed to scrape year {year}: {str(e)}")
                if self.current_session:
                    self.current_session.errors.append(f"Year {year}: {str(e)}")
                continue

        # End session
        self._end_session()

        return results

    def _start_session(self) -> None:
        """Start a new scraping session."""
        self.current_session = ScrapingSession(
            session_id=str(uuid.uuid4())[:8], start_time=datetime.now()
        )
        logger.info(f"Started scraping session: {self.current_session.session_id}")

    def _end_session(self) -> None:
        """End the current scraping session."""
        if self.current_session:
            self.current_session.end_time = datetime.now()
            logger.info(
                f"Completed scraping session {self.current_session.session_id} "
                f"in {self.current_session.duration_minutes:.1f} minutes"
            )

    def get_download_stats(self) -> dict:
        """Get statistics about downloaded files."""
        return self.downloader.get_download_stats()

    def close(self) -> None:
        """Close the client and cleanup resources."""
        self.scraper.close()
        logger.info("POTHEN client closed")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
