"""
Transliteration Package - Unified interface for text transliteration and language detection.

This package provides comprehensive transliteration services:
- Latin ↔ Greek transliteration
- Language detection (Greek, Latin, Mixed, Neutral)
- Search optimization utilities

Main Interface:
    TransliterationService - Unified facade for all transliteration needs

Specialized Services:
    GreekTransliterationService - Latin → Greek transliteration
    LatinTransliterationService - Greek → Latin transliteration

Usage:
    # Recommended - use the unified interface
    from core.services.transliteration import TransliterationService

    result = TransliterationService.transliterate_query("DHMOS")

    # Or import specific services if needed
    from core.services.transliteration import (
        TransliterationService,
        GreekTransliterationService,
        LatinTransliterationService
    )
"""

from .greek_transliteration_service import GreekTransliterationService
from .latin_transliteration_service import LatinTransliterationService
from .transliteration_service import TransliterationService, transliteration_service

__all__ = [
    "TransliterationService",
    "transliteration_service",
    "GreekTransliterationService",
    "LatinTransliterationService",
]
