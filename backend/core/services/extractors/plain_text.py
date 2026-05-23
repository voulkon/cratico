import os
import warnings

from core.protocols.extraction_protocol import ExtractionResult
from loguru import logger


class PlainTextExtractor:
    """
    Simple text extractor using Python's built-in functions for text files.
    Great for testing with minimal dependencies.

    WARNING: This extractor is only suitable for actual text files (.txt).
    For PDFs, use PDFTextExtractor instead. This extractor will NOT correctly
    handle binary files like PDFs and may produce binary garbage.
    """

    def __init__(self):
        warnings.warn(
            "PlainTextExtractor is only suitable for plain text files (.txt). "
            "For PDFs or other binary formats, use a dedicated extractor class.",
            DeprecationWarning,
            stacklevel=2,
        )

    def extract_text(self, file_path: str) -> ExtractionResult:
        """Extract text from a plain text file"""
        warning_msg = (
            f"Using PlainTextExtractor on a PDF file ({file_path}). "
            "This will produce incorrect results. Use another extractor instead!"
        )
        logger.warning(warning_msg)
        warnings.warn(warning_msg, UserWarning, stacklevel=2)

        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()

            # For plain text files, assume always 1 page and never scanned
            return ExtractionResult(
                text=text,
                page_count=1,
                is_scanned=False,
                metadata={
                    "provider": "PLAINTEXT",
                    "file_size_bytes": os.path.getsize(file_path),
                },
            )

        except Exception as e:
            logger.error(f"Plain text extraction failed: {str(e)}")
            raise
