import os

from core.protocols.extraction_protocol import ExtractionResult
from loguru import logger


class PyMuPDFExtractor:
    """
    Text extractor using PyMuPDF (fitz) for PDF files.
    This class is designed to extract text from PDF documents.
    """

    def extract_text(self, file_path: str) -> ExtractionResult:
        """Extract text from a PDF file using PyMuPDF"""
        try:
            import pymupdf  # PyMuPDF
        except ImportError:
            raise ImportError(
                "PyMuPDF is not installed. Please install it with 'pip install PyMuPDF'."
            )

        try:
            doc = pymupdf.open(file_path)
            text = ""
            pages_data = []
            for page_num, page in enumerate(doc, 1):
                page_text = page.get_text()
                text += page_text
                pages_data.append(
                    {
                        "page_number": page_num,
                        "text": page_text,
                        "character_count": len(page_text),
                    }
                )

            return ExtractionResult(
                text=text,
                page_count=len(doc),
                is_scanned=False,
                pages_data=pages_data,
                metadata={
                    "provider": "PYMUPDF",
                    "file_size_bytes": os.path.getsize(file_path),
                },
            )
        except Exception as e:
            logger.error(f"PyMuPDF extraction failed: {str(e)}")
            raise
