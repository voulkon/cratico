"""
Language Detection Service for Greek/Latin text identification.

This service is specifically designed for Greek-Latin language detection
in search queries and entity names. It focuses on accuracy and performance
for the specific use case of Greek public sector data.

Separate from transliteration - this only detects language, doesn't convert.
"""

import re
from dataclasses import dataclass
from typing import Literal, Tuple

# Language type definition
LanguageType = Literal["greek", "latin", "mixed", "neutral"]


@dataclass
class LanguageDetectionResult:
    """
    Result of language detection.

    Attributes:
        language: Detected language ('greek', 'latin', 'mixed', 'neutral')
        confidence: Confidence score (0.0 - 1.0)
        greek_ratio: Ratio of Greek characters (0.0 - 1.0)
        latin_ratio: Ratio of Latin characters (0.0 - 1.0)
        total_chars: Total alphabetic characters analyzed
    """

    language: LanguageType
    confidence: float
    greek_ratio: float
    latin_ratio: float
    total_chars: int

    def __str__(self) -> str:
        return (
            f"Language: {self.language} "
            f"(confidence: {self.confidence:.2f}, "
            f"greek: {self.greek_ratio:.2f}, "
            f"latin: {self.latin_ratio:.2f})"
        )


class LanguageDetectionService:
    """
    Detect the primary language/script of text.

    Designed for Greek/Latin detection in search queries and entity names.

    Detection rules:
    - 'greek': > 70% Greek characters
    - 'latin': > 70% Latin characters
    - 'mixed': Both Greek and Latin present (< 70% each)
    - 'neutral': No alphabetic characters (numbers, punctuation only)

    Examples:
        >>> service = LanguageDetectionService()
        >>> result = service.detect('ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ')
        >>> result.language
        'greek'
        >>> result.confidence
        1.0
    """

    # Unicode ranges for Greek characters
    # Main Greek block: U+0370 to U+03FF
    # Extended Greek block: U+1F00 to U+1FFF (polytonic, ancient Greek)
    GREEK_PATTERN = re.compile(r"[\u0370-\u03FF\u1F00-\u1FFF]")

    # Latin characters including accented variants
    # Basic Latin: a-z, A-Z
    # Latin Extended: À-ÿ (common accented characters)
    LATIN_PATTERN = re.compile(r"[a-zA-ZÀ-ÿ]")

    # Threshold for classifying as predominantly one language
    DOMINANCE_THRESHOLD = 0.7

    @classmethod
    def detect(cls, text: str) -> LanguageDetectionResult:
        """
        Detect the primary language of the given text.

        Args:
            text: Text to analyze

        Returns:
            LanguageDetectionResult with language and confidence

        Examples:
            >>> LanguageDetectionService.detect('ΔΗΜΟΣ')
            LanguageDetectionResult(language='greek', confidence=1.0, ...)

            >>> LanguageDetectionService.detect('Athens')
            LanguageDetectionResult(language='latin', confidence=1.0, ...)

            >>> LanguageDetectionService.detect('ΔΗΜΟΣ Athens')
            LanguageDetectionResult(language='mixed', confidence=0.85, ...)
        """
        if not text:
            return LanguageDetectionResult(
                language="neutral",
                confidence=1.0,
                greek_ratio=0.0,
                latin_ratio=0.0,
                total_chars=0,
            )

        # Count Greek and Latin characters
        greek_chars = len(cls.GREEK_PATTERN.findall(text))
        latin_chars = len(cls.LATIN_PATTERN.findall(text))
        total_alpha = greek_chars + latin_chars

        # If no alphabetic characters, it's neutral (numbers/punctuation)
        if total_alpha == 0:
            return LanguageDetectionResult(
                language="neutral",
                confidence=1.0,
                greek_ratio=0.0,
                latin_ratio=0.0,
                total_chars=0,
            )

        # Calculate ratios
        greek_ratio = greek_chars / total_alpha
        latin_ratio = latin_chars / total_alpha

        # Determine language and confidence
        if greek_ratio > cls.DOMINANCE_THRESHOLD:
            language = "greek"
            confidence = greek_ratio
        elif latin_ratio > cls.DOMINANCE_THRESHOLD:
            language = "latin"
            confidence = latin_ratio
        else:
            language = "mixed"
            # Confidence for mixed is based on how balanced it is
            # Perfect balance (50/50) = high confidence
            # Extreme imbalance (69/31) = lower confidence
            balance = 1.0 - abs(greek_ratio - latin_ratio)
            confidence = 0.5 + (balance * 0.5)  # Range: 0.5 to 1.0

        return LanguageDetectionResult(
            language=language,
            confidence=confidence,
            greek_ratio=greek_ratio,
            latin_ratio=latin_ratio,
            total_chars=total_alpha,
        )

    @classmethod
    def is_greek(cls, text: str) -> bool:
        """
        Quick check if text is predominantly Greek.

        Args:
            text: Text to check

        Returns:
            True if > 70% Greek characters
        """
        result = cls.detect(text)
        return result.language == "greek"

    @classmethod
    def is_latin(cls, text: str) -> bool:
        """
        Quick check if text is predominantly Latin.

        Args:
            text: Text to check

        Returns:
            True if > 70% Latin characters
        """
        result = cls.detect(text)
        return result.language == "latin"

    @classmethod
    def is_mixed(cls, text: str) -> bool:
        """
        Quick check if text is mixed Greek/Latin.

        Args:
            text: Text to check

        Returns:
            True if contains both Greek and Latin (< 70% each)
        """
        result = cls.detect(text)
        return result.language == "mixed"

    @classmethod
    def get_search_weights(cls, query: str) -> Tuple[str, str]:
        """
        Get PostgreSQL FTS weights based on query language.

        Returns tuple of (greek_field_weight, latin_field_weight).
        Higher letter = lower priority: A > B > C > D

        Strategy:
        - Greek query → prioritize Greek fields (A), deprioritize Latin (C)
        - Latin query → prioritize Latin fields (A), deprioritize Greek (C)
        - Mixed/neutral → balanced (A, B)

        Args:
            query: Search query text

        Returns:
            Tuple of (greek_weight, latin_weight)

        Example:
            >>> LanguageDetectionService.get_search_weights('ΔΗΜΟΣ')
            ('A', 'C')  # Prioritize Greek fields
            >>> LanguageDetectionService.get_search_weights('Athens')
            ('C', 'A')  # Prioritize Latin fields
        """
        result = cls.detect(query)

        if result.language == "greek":
            return ("A", "C")  # Greek high, Latin low
        elif result.language == "latin":
            return ("C", "A")  # Latin high, Greek low
        else:  # mixed or neutral
            return ("A", "B")  # Both important

    @classmethod
    def get_search_rank_weights(cls, query: str) -> list[float]:
        """
        Get Django SearchRank weights based on query language.

        Returns list of 4 floats for [D, C, B, A] priority fields.
        Used with: SearchRank(F('search_vector'), search_query, weights=weights)

        Args:
            query: Search query text

        Returns:
            List of weights [D, C, B, A]

        Example:
            >>> LanguageDetectionService.get_search_rank_weights('ΔΗΜΟΣ')
            [0.1, 0.2, 0.4, 1.0]  # Favor 'A' fields (Greek)
        """
        result = cls.detect(query)

        if result.language == "greek":
            return [0.1, 0.2, 0.4, 1.0]  # Favor A (Greek fields)
        elif result.language == "latin":
            return [0.1, 1.0, 0.4, 0.2]  # Favor C (Latin fields)
        else:  # mixed or neutral
            return [0.1, 0.2, 0.4, 1.0]  # Default balanced


# Convenience singleton for easy imports
language_detector = LanguageDetectionService()
