"""
Greek Tax Number (ΑΦΜ) detection text process.

Detects 9-digit Greek tax registration numbers (ΑΦΜ / VAT) in decision text
and validates each candidate against the official checksum algorithm.  The
checksum is the *core* mechanism — a random 9-digit number has roughly a
1-in-11 chance of passing — and the word ``ΑΦΜ`` (or ``AFM``) nearby is used
as an extra proximity signal that is recorded on the span (and can optionally
be required via ``require_keyword=True``).
"""

from __future__ import annotations

import re

from .base import BaseTextProcess, TextProcessResult, TextSpanData

# Checksum weights: digit i (0-indexed, i = 0..7) × 2 ** (8 - i)
_WEIGHTS = (256, 128, 64, 32, 16, 8, 4, 2)

# A 9-digit candidate that is not embedded in a longer run of digits
# (this also keeps phone numbers / protocol IDs out of the candidate list).
_CANDIDATE_RE = re.compile(r"(?<!\d)(\d{9})(?!\d)")

# "ΑΦΜ" may appear accented or not, Greek or Latin, dotted or not.
_KEYWORD_RE = re.compile(r"ΑΦΜ|Α\.Φ\.Μ\.|AFM", re.IGNORECASE)

# Default window (chars) around a candidate in which we look for the keyword.
_DEFAULT_WINDOW = 40


def normalize_afm(value: str | int | None) -> str | None:
    """
    Normalize a raw value to a 9-digit AFM string, or ``None`` if impossible.

    Handles integers, surrounding whitespace, an optional ``EL``/``GR`` VAT
    prefix, and the usual formatting characters (spaces, dots, hyphens).
    """
    if value is None:
        return None

    if isinstance(value, int):
        s = str(value)
    else:
        s = value.strip()

    # Optional EU VAT country prefix sometimes present in structured data.
    if len(s) > 2 and s[:2].upper() in ("EL", "GR"):
        s = s[2:]

    # Drop formatting characters.
    s = re.sub(r"[\s.\-]", "", s)

    if len(s) != 9 or not s.isdigit():
        return None
    return s


def is_valid_afm(value: str | int | None) -> bool:
    """
    Validate a Greek ΑΦΜ using the official checksum algorithm.

    ``(sum(first 8 digits × 2**(8-i)) % 11) % 10`` must equal the 9th digit
    (the check digit).  The classic special case where the remainder is 10 is
    handled implicitly by the outer ``% 10`` (10 → 0).
    """
    s = normalize_afm(value)
    if s is None:
        return False

    # "000000000" passes the pure arithmetic but is not a real AFM.
    if int(s) == 0:
        return False

    total = sum(int(d) * w for d, w in zip(s[:8], _WEIGHTS))
    check_digit = (total % 11) % 10
    return check_digit == int(s[8])


class AfmProcess(BaseTextProcess):
    slug = "afm"
    name = "AFM Detection"
    description = (
        "Detect Greek tax numbers (ΑΦΜ) using the official checksum "
        "algorithm, with the 'ΑΦΜ' keyword proximity as an extra signal."
    )
    methods = ("regex",)
    color = "#9C27B0"  # purple

    def detect(self, text: str, method: str = "regex", **params) -> TextProcessResult:
        if not text:
            return TextProcessResult(spans=[], success=True)

        window = int(params.get("window", _DEFAULT_WINDOW))
        require_keyword = bool(params.get("require_keyword", False))

        spans: list[TextSpanData] = []
        for m in _CANDIDATE_RE.finditer(text):
            candidate = m.group(1)
            if not is_valid_afm(candidate):
                continue

            start, end = m.start(1), m.end(1)
            context = text[max(0, start - window) : min(len(text), end + window)]
            keyword_match = _KEYWORD_RE.search(context)

            if require_keyword and not keyword_match:
                continue

            spans.append(
                TextSpanData(
                    label="afm",
                    start=start,
                    end=end,
                    text_snippet=candidate,
                    value={
                        "afm": candidate,
                        "near_keyword": keyword_match is not None,
                        "keyword": (
                            keyword_match.group(0).upper()
                            if keyword_match
                            else None
                        ),
                    },
                    confidence=0.95 if keyword_match else 0.85,
                )
            )

        spans.sort(key=lambda s: s.start)
        return TextProcessResult(
            spans=spans,
            meta={"detected_count": len(spans)},
            success=True,
        )
