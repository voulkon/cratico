from typing import Any, Dict, List, Optional, Protocol

from pydantic import BaseModel


class ExtractionResult(BaseModel):
    """Standardized result from text extraction"""

    text: str
    page_count: int
    is_scanned: bool = False
    pages_data: Optional[List[Dict[str, Any]]] = None
    metadata: Optional[Dict[str, Any]] = None


class TextExtractor(Protocol):
    """Protocol defining text extraction methods"""

    def extract_text(self, file_path: str) -> ExtractionResult:
        """
        Extract text from a document file

        Args:
            file_path: Path to the document file

        Returns:
            ExtractionResult: Standardized extraction result
        """
        ...
