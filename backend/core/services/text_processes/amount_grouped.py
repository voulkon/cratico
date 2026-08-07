"""
Cents-based amount detection text process.

Uses ``grouped_amount_detection.extract_grouped_amounts()`` — only matches
amounts that include 2 decimal places (cents), e.g. ``1.234.567,89``,
``30.000,00``, ``30000,00``.  In Greek official documents, monetary amounts
virtually always include the cents — this is the defining signal that
separates money from other numbers (protocol IDs, dates, page refs).

Because the pattern is unambiguous (no other numeric pattern in Greek
administrative text ends with ``,00``), any mismatch between these
detections and the ``DecisionAmountField`` amounts is a high-confidence
discrepancy signal.
"""

from __future__ import annotations

from core.services.grouped_amount_detection import extract_grouped_amounts

from .base import BaseTextProcess, TextProcessResult, TextSpanData


class GroupedAmountProcess(BaseTextProcess):
    slug = "amount-cents"
    name = "Amounts with Cents"
    description = (
        "Detect only amounts with 2 decimal places (cents: ,00) — "
        "the defining signal of monetary values in Greek documents. "
        "High-precision, near-zero false positives."
    )
    methods = ("regex",)
    color = "#4CAF50"  # green

    def detect(self, text: str, method: str = "regex", **params) -> TextProcessResult:
        detected = extract_grouped_amounts(text)
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
            meta={
                "detected_count": len(spans),
                "detector": "cents-based",
            },
            success=True,
        )
