"""
Tests for the generic text process framework (TextProcessService + processes).

Covers:
- The date-detection process (the "second algorithm" guinea pig).
- The generic run/span persistence via TextProcessService.
- The process registry metadata endpoint helper.
"""

from decimal import Decimal

import pytest
from core.services.text_process_service import (
    TextProcessService,
    get_available_processes,
)
from core.services.text_processes.dates import DateProcess

pytestmark = pytest.mark.django_db


# ── Date process (pure, no DB) ───────────────────────────────────────────────


class TestDateProcess:
    def test_numeric_date(self):
        result = DateProcess().detect("Ημερομηνία 12/05/2024.")
        assert result.success
        assert len(result.spans) == 1
        span = result.spans[0]
        assert span.label == "date"
        assert span.value["date"] == "2024-05-12"
        assert span.text_snippet == "12/05/2024"
        assert span.end > span.start

    def test_iso_date(self):
        result = DateProcess().detect("Στις 2024-05-12 υπογράφηκε.")
        assert result.spans[0].value["date"] == "2024-05-12"

    def test_written_greek_date(self):
        result = DateProcess().detect("Αθήνα, 12 Μαΐου 2024.")
        assert result.spans[0].value["date"] == "2024-05-12"
        assert result.spans[0].text_snippet == "12 Μαΐου 2024"

    def test_two_digit_year(self):
        result = DateProcess().detect("12/05/24")
        assert result.spans[0].value["date"] == "2024-05-12"

    def test_invalid_date_rejected(self):
        # Month 13 is invalid
        result = DateProcess().detect("12/13/2024")
        assert result.spans == []

    def test_multiple_dates(self):
        result = DateProcess().detect(
            "Από 01/01/2024 έως 31/12/2024 και 15 Μαρτίου 2024."
        )
        assert len(result.spans) == 3
        assert result.spans[0].start < result.spans[1].start < result.spans[2].start

    def test_empty_text(self):
        assert DateProcess().detect("").spans == []


# ── Registry metadata ────────────────────────────────────────────────────────


class TestRegistry:
    def test_available_processes(self):
        processes = get_available_processes()
        slugs = {p["slug"] for p in processes}
        assert "amount" in slugs
        assert "dates" in slugs
        for p in processes:
            assert p["name"]
            assert p["methods"]


# ── Generic service persistence ──────────────────────────────────────────────


class TestTextProcessService:
    def test_run_process_persists_spans(self):
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.document_analysis import TextProcessRun, TextSpan

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision,
            raw_text="Απόφαση της 12/05/2024 με ποσό 30.000,00 €.",
        )

        svc = TextProcessService()
        run = svc.run_process(extraction, "dates")

        assert run.status == "COMPLETED"
        assert run.process == "dates"
        assert run.provider == "REGEX"

        spans = TextSpan.objects.filter(run=run)
        assert spans.count() == 1
        span = spans.first()
        assert span.label == "date"
        assert span.value["date"] == "2024-05-12"
        # Offsets must slice the raw text back to the snippet
        assert extraction.raw_text[span.start : span.end] == span.text_snippet

    def test_idempotent_second_run(self):
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.document_analysis import TextProcessRun

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="12/05/2024"
        )

        svc = TextProcessService()
        first = svc.run_process(extraction, "dates")
        second = svc.run_process(extraction, "dates")

        assert first.id == second.id
        assert TextProcessRun.objects.filter(
            extraction=extraction, process="dates"
        ).count() == 1

    def test_force_rerun_replaces_spans(self):
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.document_analysis import TextSpan

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="12/05/2024"
        )

        svc = TextProcessService()
        run = svc.run_process(extraction, "dates")
        assert TextSpan.objects.filter(run=run).count() == 1

        # Change the text, force re-run → spans replaced
        extraction.raw_text = "12/05/2024 και 13/06/2024"
        extraction.save()
        run2 = svc.run_process(extraction, "dates", force=True)
        assert run2.id == run.id
        assert TextSpan.objects.filter(run=run2).count() == 2

    def test_unknown_process_raises(self):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(decision=decision, raw_text="x")

        svc = TextProcessService()
        with pytest.raises(ValueError, match="Unknown text process"):
            svc.run_process(extraction, "nonexistent")

    def test_runs_payload_serialization(self):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="12/05/2024"
        )

        svc = TextProcessService()
        svc.run_process(extraction, "dates")

        payload = svc.get_runs_payload(extraction)
        assert len(payload) == 1
        run = payload[0]
        assert run["process"] == "dates"
        assert run["status"] == "COMPLETED"
        assert len(run["spans"]) == 1
        assert run["spans"][0]["value"]["date"] == "2024-05-12"

    def test_amount_process_via_generic_service(self):
        """The amount process works through the generic service too."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.document_analysis import TextSpan

        decision = DecisionFactory()
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Δαπάνη 30.000,00 €."
        )

        svc = TextProcessService()
        run = svc.run_process(extraction, "amount")

        assert run.status == "COMPLETED"
        span = TextSpan.objects.get(run=run, label="amount")
        assert span.value["amount"] == "30000.00"
        assert extraction.raw_text[span.start : span.end] == "30.000,00"
