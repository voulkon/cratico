"""
Amount detection text process.

Wraps the existing ``amount_text_detection.extract_amounts()`` — no new
detection logic; it just emits ``TextSpanData`` with ``start``/``end``
instead of only ``position``.  The resolution policy (exact-match-wins,
clone detection) is computed separately by ``AmountVerificationService``
against the persisted spans.
"""

from __future__ import annotations

from core.services.amount_text_detection import extract_amounts

from .base import BaseTextProcess, TextProcessResult, TextSpanData


class AmountProcess(BaseTextProcess):
    slug = "amount"
    name = "Amount Detection"
    description = (
        "Detect monetary amounts in the document text (Greek-formatted "
        "numbers with optional currency markers)."
    )
    methods = ("regex", "ai")
    async_methods = ("ai",)  # LLM calls run on Celery worker
    color = "#FF9800"  # amber

    def detect(self, text: str, method: str = "regex", **params) -> TextProcessResult:
        detected = extract_amounts(text)
        spans = [
            TextSpanData(
                label="amount",
                start=d.position,
                end=d.position + len(d.raw),
                text_snippet=d.raw,
                value={
                    "amount": str(d.amount),
                    "near_keyword": d.near_keyword,
                },
            )
            for d in detected
        ]
        return TextProcessResult(
            spans=spans,
            meta={"detected_count": len(spans)},
            success=True,
        )
