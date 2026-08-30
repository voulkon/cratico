"""
Date detection text process.

Detects dates in Greek government decision text:
  - numeric:   12/05/2024, 12-05-2024, 12.05.2024, 12/05/24
  - ISO:       2024-05-12
  - written:   12 Μαΐου 2024, 12 ΜΑΪΟΥ 2024, 12 May 2024

Purely regex-based; emits a span per date with a normalized ISO value.
"""

from __future__ import annotations

import re

from .base import BaseTextProcess, TextProcessResult, TextSpanData

# Greek month names (nominative & genitive — decisions use genitive: "Μαΐου")
_MONTHS = {
    "ιανουαριου": 1, "ιανουαρίου": 1, "ιαν": 1, "january": 1, "jan": 1,
    "φεβρουαριου": 2, "φεβρουαρίου": 2, "φεβ": 2, "february": 2, "feb": 2,
    "μαρτιου": 3, "μαρτίου": 3, "μαρ": 3, "march": 3, "mar": 3,
    "απριλιου": 4, "απριλίου": 4, "απρ": 4, "april": 4, "apr": 4,
    "μαιου": 5, "μαΐου": 5, "μαι": 5, "may": 5,
    "ιουνιου": 6, "ιουνίου": 6, "ιουν": 6, "june": 6, "jun": 6,
    "ιουλιου": 7, "ιουλίου": 7, "ιουλ": 7, "july": 7, "jul": 7,
    "αυγουστου": 8, "αυγούστου": 8, "αυγ": 8, "august": 8, "aug": 8,
    "σεπτεμβριου": 9, "σεπτεμβρίου": 9, "σεπ": 9, "september": 9, "sep": 9,
    "οκτωβριου": 10, "οκτωβρίου": 10, "οκτ": 10, "october": 10, "oct": 10,
    "νοεμβριου": 11, "νοεμβρίου": 11, "νοε": 11, "november": 11, "nov": 11,
    "δεκεμβριου": 12, "δεκεμβρίου": 12, "δεκ": 12, "december": 12, "dec": 12,
}

_MONTH_PATTERN = "|".join(sorted(_MONTHS, key=len, reverse=True))

# 12/05/2024, 12-05-2024, 12.05.2024, 12/05/24
# The leading lookbehind rejects a digit/dot/hyphen immediately before the
# day (numeric continuation), but deliberately ALLOWS a preceding '/': in
# Diavgeia text dates are routinely embedded in reference numbers
# ("ΓΔΟΥ/173041/19.04.2021", "ΦΕΚ 4498/Β/29.09.2021", "ΕΞ 2021/30.09.2021")
# and those are real dates.  Garbage chains like "5665/11887" can't match
# anyway because the pattern requires DD<sep>MM<sep>YYYY with valid ranges.
# The trailing lookahead only rejects a separator FOLLOWED BY A DIGIT (an
# actual numeric continuation); a lone '.' at the end of a sentence is fine.
_NUMERIC_RE = re.compile(
    r"(?<![\d.\-])"
    r"(?P<day>\d{1,2})(?P<sep>[/.-])(?P<month>\d{1,2})(?P=sep)(?P<year>\d{2,4})"
    r"(?![/.-]?\d)"
)

# 2024-05-12
_ISO_RE = re.compile(
    r"(?<![\d\-])(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(?![\d\-])"
)

# 12 Μαΐου 2024  /  12 May 2024
_WRITTEN_RE = re.compile(
    r"(?<!\w)(?P<day>\d{1,2})\s+(?P<month>" + _MONTH_PATTERN + r")\s+(?P<year>\d{4})(?!\w)",
    re.IGNORECASE,
)


def _normalize_year(year: str) -> int:
    y = int(year)
    if y < 100:  # two-digit year → 20xx (decisions are recent)
        y += 2000
    return y


def _valid(day: int, month: int, year: int) -> bool:
    return 1 <= day <= 31 and 1 <= month <= 12 and 1900 <= year <= 2100


class DateProcess(BaseTextProcess):
    slug = "dates"
    name = "Date Detection"
    description = (
        "Detect dates in numeric (12/05/2024), ISO (2024-05-12), and written "
        "(12 Μαΐου 2024) forms. Normalized to ISO in span value."
    )
    methods = ("regex",)
    color = "#1976D2"  # blue

    def detect(self, text: str, method: str = "regex", **params) -> TextProcessResult:
        if not text:
            return TextProcessResult(spans=[], success=True)

        spans: list[TextSpanData] = []
        seen: set[tuple[int, int]] = set()

        def add(match: re.Match, day: int, month: int, year: int):
            key = (match.start(), match.end())
            if key in seen:
                return
            seen.add(key)
            snippet = match.group(0)
            spans.append(
                TextSpanData(
                    label="date",
                    start=match.start(),
                    end=match.end(),
                    text_snippet=snippet,
                    value={"date": f"{year:04d}-{month:02d}-{day:02d}"},
                )
            )

        for m in _NUMERIC_RE.finditer(text):
            day, month, year = (
                int(m.group("day")),
                int(m.group("month")),
                _normalize_year(m.group("year")),
            )
            if _valid(day, month, year):
                add(m, day, month, year)

        for m in _ISO_RE.finditer(text):
            day, month, year = (
                int(m.group("day")),
                int(m.group("month")),
                int(m.group("year")),
            )
            if _valid(day, month, year):
                add(m, day, month, year)

        for m in _WRITTEN_RE.finditer(text):
            month = _MONTHS.get(m.group("month").lower())
            day, year = int(m.group("day")), int(m.group("year"))
            if month and _valid(day, month, year):
                add(m, day, month, year)

        spans.sort(key=lambda s: s.start)
        return TextProcessResult(
            spans=spans,
            meta={"detected_count": len(spans)},
            success=True,
        )
