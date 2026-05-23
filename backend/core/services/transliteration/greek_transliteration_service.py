"""
Service for transliterating Latin/English letters to Greek letters.
Handles user input like "DHMOS" -> "ΔΗΜΟΣ" for better search results.

Uses a simple, reliable character mapping for predictable results.
"""


class GreekTransliterationService:
    """
    Transliterates Latin/English letters to their Greek equivalents.
    This helps users who don't have Greek keyboard layouts type Greek searches.

    Uses a simple, reliable character mapping for consistent results.

    Examples:
        - "DHMOS" -> "ΔΗΜΟΣ"
        - "YPOURGEIA" -> "ΥΠΟΥΡΓΕΙΑ"
        - "PERIFEREIA" -> "ΠΕΡΙΦΕΡΕΙΑ"
    """

    # Simple Latin to Greek character mapping
    # Handles common transliterations used for Greek words
    CHAR_MAP = {
        # Two-character combinations (MUST be checked first)
        "TH": "Θ",
        "th": "θ",
        "Th": "Θ",
        "CH": "Χ",
        "ch": "χ",
        "Ch": "Χ",
        "PH": "Φ",
        "ph": "φ",
        "Ph": "Φ",
        "PS": "Ψ",
        "ps": "ψ",
        "Ps": "Ψ",
        # Single character mappings
        "A": "Α",
        "a": "α",
        "B": "Β",
        "b": "β",
        "G": "Γ",
        "g": "γ",
        "D": "Δ",
        "d": "δ",
        "E": "Ε",
        "e": "ε",
        "Z": "Ζ",
        "z": "ζ",
        "H": "Η",
        "h": "η",
        "I": "Ι",
        "i": "ι",
        "K": "Κ",
        "k": "κ",
        "L": "Λ",
        "l": "λ",
        "M": "Μ",
        "m": "μ",
        "N": "Ν",
        "n": "ν",
        "X": "Ξ",
        "x": "ξ",
        "O": "Ο",
        "o": "ο",
        "P": "Π",
        "p": "π",
        "R": "Ρ",
        "r": "ρ",
        "S": "Σ",
        "s": "σ",
        "T": "Τ",
        "t": "τ",
        "U": "Υ",
        "u": "υ",
        "Y": "Υ",
        "y": "υ",
        "F": "Φ",
        "f": "φ",
        "W": "Ω",
        "w": "ω",
    }

    @classmethod
    def transliterate(cls, text: str, preserve_original: bool = False) -> str:
        """
        Transliterate Latin/English letters to Greek using a simple character map.

        Args:
            text: The text to transliterate
            preserve_original: If True, returns original text unchanged (useful for toggle feature)

        Returns:
            Transliterated text

        Examples:
            >>> GreekTransliterationService.transliterate("DHMOS")
            "ΔΗΜΟΣ"
            >>> GreekTransliterationService.transliterate("ypourgeia")
            "υπουργεια"

        Note:
            Uses a simple, reliable character-by-character mapping.
        """
        if not text or preserve_original:
            return text

        result = []
        i = 0

        while i < len(text):
            # Check for two-character combinations first
            if i < len(text) - 1:
                two_char = text[i : i + 2]
                if two_char in cls.CHAR_MAP:
                    result.append(cls.CHAR_MAP[two_char])
                    i += 2
                    continue

            # Check for single character
            char = text[i]
            if char in cls.CHAR_MAP:
                result.append(cls.CHAR_MAP[char])
            else:
                # Keep non-mappable characters as-is (numbers, spaces, punctuation, etc.)
                result.append(char)
            i += 1

        return "".join(result)

    @classmethod
    def needs_transliteration(cls, text: str) -> bool:
        """
        Check if text contains Latin characters that should be transliterated.

        Args:
            text: The text to check

        Returns:
            True if text appears to be in Latin script and needs transliteration
        """
        if not text:
            return False

        # Check if text contains mostly Latin characters (not Greek)
        # Greek characters are in the Unicode range 0x0370-0x03FF
        latin_count = 0
        greek_count = 0

        for char in text:
            code = ord(char)
            # Greek Unicode range
            if 0x0370 <= code <= 0x03FF or 0x1F00 <= code <= 0x1FFF:
                greek_count += 1
            # Latin ASCII range A-Z, a-z
            elif (0x0041 <= code <= 0x005A) or (0x0061 <= code <= 0x007A):
                latin_count += 1

        # If we have more Latin than Greek, it needs transliteration
        return latin_count > greek_count and latin_count > 0

    @classmethod
    def transliterate_query(cls, query: str) -> str:
        """
        Intelligent transliteration for search queries.
        Transliterates Latin characters to Greek, keeping already-Greek text unchanged.

        This is the main method to use in search endpoints.

        Args:
            query: The search query

        Returns:
            Transliterated query
        """
        if not query or not cls.needs_transliteration(query):
            return query

        return cls.transliterate(query)
