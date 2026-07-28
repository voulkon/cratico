"""
Regex-strip preprocessor — removes configured regex patterns from text.

Config params:
    patterns: list of regex strings to remove (default: common boilerplate)
"""

import re

from .registry import PreprocessorRegistry

_DEFAULT_PATTERNS = [
    # Common Greek government document boilerplate
    r"ΔΙΑΒΓΕΙΑ\s*[-–—]\s*",
    r"Αριθμός\s+Πρωτοκόλλου:\s*\S+",
    r"Ημερομηνία\s+έκδοσης:\s*\S+",
]


def regex_strip(text: str, params: dict | None = None) -> str:
    """Remove configured regex patterns from *text*."""
    if not text:
        return text
    params = params or {}
    patterns = params.get("patterns", _DEFAULT_PATTERNS)
    result = text
    for pattern in patterns:
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)
    return result.strip()


PreprocessorRegistry.register("regex_strip", regex_strip)
