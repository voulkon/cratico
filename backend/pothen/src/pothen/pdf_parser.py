"""PDF text extraction and parsing for parliament declarations."""

import logging
import re
from pathlib import Path
from typing import List, Optional

try:
    import PyPDF2

    HAS_PYPDF2 = True
except ImportError:
    HAS_PYPDF2 = False

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False

from .constants import MIN_PDF_CONTENT_LENGTH
from .exceptions import PothenParsingError, PothenValidationError
from .schemas import ParsedDeclarationContent, PDFMetadata

logger = logging.getLogger(__name__)


class PDFTextExtractor:
    """Service for extracting text content from PDF files."""

    def __init__(self, preferred_method: str = "pdfplumber"):
        """
        Initialize PDF extractor.

        Args:
            preferred_method: "pdfplumber" or "pypdf2"
        """
        self.preferred_method = preferred_method

        # Check available libraries
        available_methods = []
        if HAS_PDFPLUMBER:
            available_methods.append("pdfplumber")
        if HAS_PYPDF2:
            available_methods.append("pypdf2")

        if not available_methods:
            raise RuntimeError(
                "No PDF processing libraries available. Install pdfplumber or PyPDF2."
            )

        if preferred_method not in available_methods:
            self.preferred_method = available_methods[0]
            logger.warning(
                f"Preferred method '{preferred_method}' not available. Using '{self.preferred_method}'"
            )

    def extract_text_pypdf2(self, filepath: Path) -> tuple[str, int]:
        """Extract text using PyPDF2."""
        if not HAS_PYPDF2:
            raise PothenParsingError("PyPDF2 not available")

        try:
            text_content = []
            page_count = 0

            with open(filepath, "rb") as file:
                pdf_reader = PyPDF2.PdfReader(file)
                page_count = len(pdf_reader.pages)

                for page_num, page in enumerate(pdf_reader.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            text_content.append(
                                f"--- Page {page_num + 1} ---\n{page_text}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract text from page {page_num + 1}: {str(e)}"
                        )
                        continue

            full_text = "\n\n".join(text_content)
            return full_text, page_count

        except Exception as e:
            raise PothenParsingError(
                f"PyPDF2 extraction failed for {filepath}: {str(e)}"
            ) from e

    def extract_text_pdfplumber(self, filepath: Path) -> tuple[str, int]:
        """Extract text using pdfplumber."""
        if not HAS_PDFPLUMBER:
            raise PothenParsingError("pdfplumber not available")

        try:
            text_content = []
            page_count = 0

            with pdfplumber.open(filepath) as pdf:
                page_count = len(pdf.pages)

                for page_num, page in enumerate(pdf.pages):
                    try:
                        page_text = page.extract_text()
                        if page_text:
                            text_content.append(
                                f"--- Page {page_num + 1} ---\n{page_text}"
                            )
                    except Exception as e:
                        logger.warning(
                            f"Failed to extract text from page {page_num + 1}: {str(e)}"
                        )
                        continue

            full_text = "\n\n".join(text_content)
            return full_text, page_count

        except Exception as e:
            raise PothenParsingError(
                f"pdfplumber extraction failed for {filepath}: {str(e)}"
            ) from e

    def extract_text(self, filepath: Path) -> ParsedDeclarationContent:
        """Extract text from PDF using the preferred method."""
        logger.info(f"Extracting text from {filepath} using {self.preferred_method}")

        # Try preferred method first
        text = ""
        page_count = 0
        extraction_method = self.preferred_method

        try:
            if self.preferred_method == "pdfplumber":
                text, page_count = self.extract_text_pdfplumber(filepath)
            elif self.preferred_method == "pypdf2":
                text, page_count = self.extract_text_pypdf2(filepath)

        except Exception as e:
            logger.warning(f"Primary extraction method failed: {str(e)}")

            # Try fallback method
            try:
                if self.preferred_method == "pdfplumber" and HAS_PYPDF2:
                    text, page_count = self.extract_text_pypdf2(filepath)
                    extraction_method = "pypdf2"
                elif self.preferred_method == "pypdf2" and HAS_PDFPLUMBER:
                    text, page_count = self.extract_text_pdfplumber(filepath)
                    extraction_method = "pdfplumber"
                else:
                    raise PothenParsingError(f"No fallback extraction method available")

                logger.info(f"Fallback extraction successful using {extraction_method}")

            except Exception as fallback_e:
                raise PothenParsingError(
                    f"All extraction methods failed: {str(fallback_e)}"
                ) from fallback_e

        # Validate extracted text
        if len(text.strip()) < MIN_PDF_CONTENT_LENGTH:
            raise PothenValidationError(
                f"Extracted text too short ({len(text)} chars) from {filepath}"
            )

        # Parse structured content
        parsed_content = ParsedDeclarationContent(
            raw_text=text, page_count=page_count, extraction_method=extraction_method
        )

        # Try to extract structured information
        try:
            parsed_content.mp_name = self._extract_mp_name(text)
        except Exception as e:
            logger.debug(f"Could not extract MP name: {str(e)}")

        logger.info(
            f"Successfully extracted {len(text)} characters from {page_count} pages"
        )
        return parsed_content

    def _extract_mp_name(self, text: str) -> Optional[str]:
        """Try to extract MP name from the text content."""
        # Common patterns in Greek parliament declarations
        patterns = [
            r"ΣΤΟΙΧΕΙΑ\s+ΥΠΟΧΡΕΟΥ[:\s]+(.+?)(?:\n|$)",  # Declaration form header
            r"ΟΝΟΜΑΤΕΠΩΝΥΜΟ[:\s]+(.+?)(?:\n|$)",  # Name field
            r"Ο\/Η\s+(.+?)\s+(?:ΒΟΥΛΕΥΤΗΣ|ΒΟΥΛΕΥΤΡΙΑ)",  # "The MP [name]"
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
            if match:
                name = match.group(1).strip()
                # Clean up common artifacts
                name = re.sub(r"\s+", " ", name)  # Normalize whitespace
                if len(name) > 3 and len(name) < 100:  # Reasonable name length
                    return name

        return None

    def extract_from_metadata_list(
        self, pdf_metadata_list: List[PDFMetadata]
    ) -> List[ParsedDeclarationContent]:
        """Extract text from multiple PDFs."""
        results = []

        for i, metadata in enumerate(pdf_metadata_list):
            try:
                logger.info(
                    f"Processing PDF {i+1}/{len(pdf_metadata_list)}: {metadata.filepath.name}"
                )

                parsed_content = self.extract_text(metadata.filepath)
                results.append(parsed_content)

            except Exception as e:
                logger.error(
                    f"Failed to extract text from {metadata.filepath}: {str(e)}"
                )
                continue

        logger.info(
            f"Successfully extracted text from {len(results)} out of {len(pdf_metadata_list)} PDFs"
        )
        return results
