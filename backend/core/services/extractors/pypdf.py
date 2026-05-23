from core.protocols.extraction_protocol import ExtractionResult
from loguru import logger


class PyPdfExtractor:
    """Text extractor using PyPDF library"""

    def extract_text(self, file_path: str) -> ExtractionResult:
        """Extract text using PyPDF"""
        try:
            import pypdf

            text_content = []
            with open(file_path, "rb") as f:
                pdf = pypdf.PdfReader(f)
                page_count = len(pdf.pages)

                # Extract metadata if available
                metadata = {}
                if pdf.metadata:
                    for key, value in pdf.metadata.items():
                        if key and value:
                            # Clean the key by removing leading /
                            clean_key = key[1:] if key.startswith("/") else key
                            metadata[clean_key] = str(value)

                for page in pdf.pages:
                    text_content.append(page.extract_text() or "")

                full_text = "\n".join(text_content)

                # Heuristic to detect scanned documents
                chars_per_page = len(full_text) / max(page_count, 1)
                is_scanned = chars_per_page < 100

                return ExtractionResult(
                    text=full_text,
                    page_count=page_count,
                    is_scanned=is_scanned,
                    metadata={
                        "provider": "PYPDF",
                        "chars_per_page": chars_per_page,
                        "pdf_metadata": metadata,
                    },
                )

        except Exception as e:
            logger.error(f"PyPDF extraction failed: {str(e)}")
            raise
