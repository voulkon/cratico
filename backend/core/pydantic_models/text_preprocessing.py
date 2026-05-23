from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, ConfigDict, Field, field_serializer


class CorruptionDetectionStrategy(Enum):
    COMMON_WORDS = "common_words"
    GREEK_DICTIONARY = "greek_dictionary"
    GR_NLP_TOOLKIT = "gr_nlp_toolkit"
    HYBRID = "hybrid"


class PreprocessingResult(BaseModel):
    """Result of text preprocessing operations."""

    model_config = ConfigDict()

    processed_text: str = Field(
        ..., description="The text after preprocessing (stopwords removed, etc.)"
    )
    is_corrupted: bool = Field(
        ..., description="True if the text appears to be corrupted or garbled"
    )
    confidence_score: Optional[float] = Field(
        None, description="Confidence score for corruption detection (0.0-1.0)"
    )
    performance_stats: Dict[str, Any] = Field(
        default_factory=dict, description="Performance metrics for the preprocessing"
    )
    corruption_indicators: Dict[str, Any] = Field(
        default_factory=dict,
        description="Details about what triggered corruption detection",
    )

    @field_serializer("confidence_score")
    def serialize_confidence_score(self, value: Optional[float]) -> Optional[float]:
        """Round confidence score to 4 decimal places."""
        return round(value, 4) if value is not None else None
