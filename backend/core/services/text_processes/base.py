"""
Text process framework — base types.

A *text process* is any algorithm that scans a ``DocumentExtraction``'s
``raw_text`` and emits labeled spans (``TextSpanData``).  Processes are pure:
text in, spans out.  Persistence, resolution (picking a "winner"), and
cost tracking live in the service layer.

Offests are char offsets into the raw text — inclusive ``start``, exclusive
``end`` — counting every character (including markdown markers like ``#``
or ``**`` that some extractors emit).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextSpanData:
    """A labeled region of text produced by a process."""

    label: str
    start: int
    end: int
    text_snippet: str
    value: dict[str, Any] = field(default_factory=dict)
    confidence: float | None = None
    occurrence_count: int = 1


@dataclass
class TextProcessResult:
    """The outcome of running a process over a text."""

    spans: list[TextSpanData] = field(default_factory=list)
    # Run-level metadata (params, raw response, computed totals, ...)
    meta: dict[str, Any] = field(default_factory=dict)
    success: bool = True
    error: str | None = None


class BaseTextProcess:
    """Base class for text processes."""

    slug: str = ""
    name: str = ""
    description: str = ""
    #: Which execution methods this process supports ("regex", "ai").
    methods: tuple[str, ...] = ("regex",)

    def detect(self, text: str, method: str = "regex", **params) -> TextProcessResult:
        raise NotImplementedError
