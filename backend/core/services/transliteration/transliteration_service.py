"""
Unified Transliteration Service.

This service provides a comprehensive interface for all transliteration needs,
consolidating Latin↔Greek transliteration and language detection functionality.

Main capabilities:
- Latin → Greek transliteration (e.g., "DHMOS" → "ΔΗΜΟΣ")
- Greek → Latin transliteration (e.g., "ΔΗΜΟΣ" → "DIMOS")
- Language detection (Greek, Latin, Mixed, Neutral)
- Search-optimized query processing
- Search rank weight calculation for FTS

Usage:
    from core.services.transliteration import TransliterationService

    # Transliterate search query
    greek_query = TransliterationService.transliterate_query("DHMOS")

    # Detect language
    lang = TransliterationService.detect_language("ΔΗΜΟΣ")

    # Get search weights
    weights = TransliterationService.get_search_rank_weights(query)
"""

from typing import Tuple

from core.services.language_detection_service import (
    LanguageDetectionService,
    LanguageType,
)

from .greek_transliteration_service import GreekTransliterationService
from .latin_transliteration_service import LatinTransliterationService


class TransliterationService:
    """
    Unified service for transliteration and language detection.

    This service consolidates all transliteration functionality:
    - Latin → Greek (via GreekTransliterationService)
    - Greek → Latin (via LatinTransliterationService)
    - Language detection (via LanguageDetectionService)
    - Search optimization utilities

    Design:
        This is a facade/unified interface that delegates to specialized services.
        Each specialized service handles one specific concern (Single Responsibility).

    Examples:
        >>> # Transliterate English letters to Greek
        >>> TransliterationService.latin_to_greek("DHMOS")
        "ΔΗΜΟΣ"

        >>> # Smart query transliteration (auto-detects if needed)
        >>> TransliterationService.transliterate_query("DHMOS")
        "ΔΗΜΟΣ"

        >>> # Detect language
        >>> TransliterationService.detect_language("ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ")
        "greek"

        >>> # Get search weights for FTS ranking
        >>> TransliterationService.get_search_rank_weights("ΔΗΜΟΣ")
        [0.1, 0.2, 0.4, 1.0]
    """

    # ==================== LATIN → GREEK TRANSLITERATION ====================

    @classmethod
    def latin_to_greek(cls, text: str, preserve_original: bool = False) -> str:
        """
        Transliterate Latin/English letters to Greek.

        Delegates to GreekTransliterationService for the actual conversion.

        Args:
            text: Latin text to transliterate
            preserve_original: If True, returns text unchanged

        Returns:
            Greek transliteration

        Examples:
            >>> TransliterationService.latin_to_greek("DHMOS")
            "ΔΗΜΟΣ"
            >>> TransliterationService.latin_to_greek("perifereia")
            "περιφερεια"
        """
        return GreekTransliterationService.transliterate(text, preserve_original)

    @classmethod
    def needs_latin_to_greek_transliteration(cls, text: str) -> bool:
        """
        Check if text needs Latin → Greek transliteration.

        Returns True if text is predominantly Latin and could benefit from
        conversion to Greek for Greek-language search.

        Args:
            text: Text to check

        Returns:
            True if text should be transliterated to Greek
        """
        return GreekTransliterationService.needs_transliteration(text)

    # ==================== GREEK → LATIN TRANSLITERATION ====================

    @classmethod
    def greek_to_latin(cls, text: str) -> str:
        """
        Transliterate Greek letters to Latin (romanization).

        Delegates to LatinTransliterationService for the actual conversion.

        Args:
            text: Greek text to transliterate

        Returns:
            Latin/romanized text

        Examples:
            >>> TransliterationService.greek_to_latin("ΔΗΜΟΣ")
            "DIMOS"
            >>> TransliterationService.greek_to_latin("Αθήνα")
            "Athina"
        """
        return LatinTransliterationService.transliterate(text)

    # ==================== LANGUAGE DETECTION ====================

    @classmethod
    def detect_language(cls, text: str) -> LanguageType:
        """
        Detect the primary language/script of text.

        Delegates to LanguageDetectionService for analysis.

        Args:
            text: Text to analyze

        Returns:
            'greek', 'latin', 'mixed', or 'neutral'

        Examples:
            >>> TransliterationService.detect_language("ΔΗΜΟΣ")
            'greek'
            >>> TransliterationService.detect_language("Athens")
            'latin'
        """
        result = LanguageDetectionService.detect(text)
        return result.language

    @classmethod
    def is_greek(cls, text: str) -> bool:
        """Check if text is predominantly Greek (> 70% Greek characters)."""
        return LanguageDetectionService.is_greek(text)

    @classmethod
    def is_latin(cls, text: str) -> bool:
        """Check if text is predominantly Latin (> 70% Latin characters)."""
        return LanguageDetectionService.is_latin(text)

    @classmethod
    def is_mixed(cls, text: str) -> bool:
        """Check if text contains both Greek and Latin (< 70% each)."""
        return LanguageDetectionService.is_mixed(text)

    # ==================== SEARCH OPTIMIZATION ====================

    @classmethod
    def transliterate_query(cls, query: str) -> str:
        """
        Smart transliteration for search queries.

        Automatically detects if transliteration is needed and applies it.
        This is the main method to use in search endpoints.

        Logic:
        - If query is predominantly Latin → transliterate to Greek
        - If query is already Greek → return unchanged
        - If query is mixed/neutral → return unchanged

        Args:
            query: Search query

        Returns:
            Transliterated query (if needed)

        Examples:
            >>> TransliterationService.transliterate_query("DHMOS")
            "ΔΗΜΟΣ"
            >>> TransliterationService.transliterate_query("ΔΗΜΟΣ")
            "ΔΗΜΟΣ"
        """
        return GreekTransliterationService.transliterate_query(query)

    @classmethod
    def get_search_rank_weights(cls, query: str) -> list[float]:
        """
        Get Django SearchRank weights based on query language.

        Used with: SearchRank(F('search_vector'), search_query, weights=weights)

        Returns list of 4 floats for [D, C, B, A] priority fields:
        - Greek query → [0.1, 0.2, 0.4, 1.0] (favor A fields)
        - Latin query → [0.1, 1.0, 0.4, 0.2] (favor C fields)
        - Mixed/neutral → [0.1, 0.2, 0.4, 1.0] (balanced)

        Args:
            query: Search query

        Returns:
            List of weights [D, C, B, A]
        """
        return LanguageDetectionService.get_search_rank_weights(query)

    @classmethod
    def get_search_weights(cls, query: str) -> Tuple[str, str]:
        """
        Get PostgreSQL FTS letter weights based on query language.

        Returns tuple of (greek_field_weight, latin_field_weight).
        Higher letter = lower priority: A > B > C > D

        - Greek query → ('A', 'C') - prioritize Greek fields
        - Latin query → ('C', 'A') - prioritize Latin fields
        - Mixed/neutral → ('A', 'B') - balanced

        Args:
            query: Search query

        Returns:
            Tuple of (greek_weight, latin_weight)
        """
        return LanguageDetectionService.get_search_weights(query)

    # ==================== UTILITY METHODS ====================

    @classmethod
    def expand_search_query(cls, query: str) -> Tuple[str, str, LanguageType]:
        """
        Expand search query with transliteration variants.

        Returns:
            - Original query
            - Transliterated variant (if Greek, convert to Latin; otherwise same as original)
            - Detected language

        Example:
            >>> TransliterationService.expand_search_query("ΔΗΜΟΣ")
            ("ΔΗΜΟΣ", "DIMOS", "greek")
        """
        detected_lang = cls.detect_language(query)

        if detected_lang == "greek":
            transliterated = cls.greek_to_latin(query)
        else:
            transliterated = query

        return (query, transliterated, detected_lang)


# Convenience singleton instance (optional, class methods are preferred)
transliteration_service = TransliterationService()
