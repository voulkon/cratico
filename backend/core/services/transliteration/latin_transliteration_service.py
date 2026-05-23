"""
Service for transliterating Greek letters to Latin/English letters (Romanization).
Converts Greek text like "ΔΗΜΟΣ" → "DIMOS" for Latin-alphabet searches.

Uses a simple, reliable character mapping for predictable results.
"""


class LatinTransliterationService:
    """
    Transliterates Greek letters to their Latin/English equivalents (Romanization).

    This is useful for:
    - Creating searchable Latin versions of Greek names
    - Generating URL-friendly slugs
    - Cross-language search matching

    Uses a simple, reliable character mapping based on common Greek romanization standards.

    Examples:
        - "ΔΗΜΟΣ" → "DIMOS"
        - "ΑΘΗΝΑ" → "ATHINA"
        - "ΠΕΡΙΦΕΡΕΙΑ" → "PERIFEREIA"
    """

    # Greek to Latin character mapping
    # Based on common romanization standards (Greeklish/Beta Code style)
    CHAR_MAP = {
        # Uppercase Greek to Latin
        "Α": "A",
        "Β": "B",
        "Γ": "G",
        "Δ": "D",
        "Ε": "E",
        "Ζ": "Z",
        "Η": "I",
        "Θ": "TH",
        "Ι": "I",
        "Κ": "K",
        "Λ": "L",
        "Μ": "M",
        "Ν": "N",
        "Ξ": "X",
        "Ο": "O",
        "Π": "P",
        "Ρ": "R",
        "Σ": "S",
        "Τ": "T",
        "Υ": "Y",
        "Φ": "F",
        "Χ": "CH",
        "Ψ": "PS",
        "Ω": "O",
        # Lowercase Greek to Latin
        "α": "a",
        "β": "b",
        "γ": "g",
        "δ": "d",
        "ε": "e",
        "ζ": "z",
        "η": "i",
        "θ": "th",
        "ι": "i",
        "κ": "k",
        "λ": "l",
        "μ": "m",
        "ν": "n",
        "ξ": "x",
        "ο": "o",
        "π": "p",
        "ρ": "r",
        "σ": "s",
        "τ": "t",
        "υ": "y",
        "φ": "f",
        "χ": "ch",
        "ψ": "ps",
        "ω": "o",
        # Final sigma
        "ς": "s",
        # Common diacritics (with accent marks) - strip accents and convert
        "Ά": "A",
        "Έ": "E",
        "Ή": "I",
        "Ί": "I",
        "Ό": "O",
        "Ύ": "Y",
        "Ώ": "O",
        "ά": "a",
        "έ": "e",
        "ή": "i",
        "ί": "i",
        "ό": "o",
        "ύ": "y",
        "ώ": "o",
        "ΐ": "i",
        "ΰ": "y",
        "ϊ": "i",
        "ϋ": "y",
    }

    @classmethod
    def transliterate(cls, text: str, preserve_original: bool = False) -> str:
        """
        Transliterate Greek letters to Latin using a simple character map.

        Args:
            text: The Greek text to transliterate
            preserve_original: If True, returns original text unchanged

        Returns:
            Romanized/Latin text

        Examples:
            >>> LatinTransliterationService.transliterate("ΔΗΜΟΣ")
            "DIMOS"
            >>> LatinTransliterationService.transliterate("Αθήνα")
            "Athina"

        Note:
            Uses a simple, reliable character-by-character mapping.
            Multi-character conversions (Θ→TH, Χ→CH, Ψ→PS) are handled.
        """
        if not text or preserve_original:
            return text

        result = []

        for char in text:
            if char in cls.CHAR_MAP:
                result.append(cls.CHAR_MAP[char])
            else:
                # Keep non-mappable characters as-is (numbers, spaces, punctuation, Latin chars)
                result.append(char)

        return "".join(result)

    @classmethod
    def needs_transliteration(cls, text: str) -> bool:
        """
        Check if text contains Greek characters that should be transliterated.

        Args:
            text: The text to check

        Returns:
            True if text appears to be in Greek script and needs transliteration
        """
        if not text:
            return False

        # Check if text contains Greek characters
        # Greek characters are in the Unicode range 0x0370-0x03FF
        greek_count = 0
        latin_count = 0

        for char in text:
            code = ord(char)
            # Greek Unicode range
            if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
                greek_count += 1
            # Latin ASCII range A-Z, a-z
            elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
                latin_count += 1

        # If we have more Greek than Latin, it needs transliteration
        return greek_count > latin_count and greek_count > 0

    @classmethod
    def romanize(cls, text: str) -> str:
        """
        Alias for transliterate - more semantic for Greek → Latin conversion.

        Args:
            text: Greek text to romanize

        Returns:
            Romanized text
        """
        return cls.transliterate(text)
