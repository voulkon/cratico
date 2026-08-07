"""
Tests for AmountCorrectionService — group correction of ×100/÷100 typos.

Covers the scenario where ALL amounts in a decision were uniformly
mis-typed (e.g. each ×100 too high), so no individual amount matches
the text, but the SUM does.  The service should re-scale each field
proportionally so the corrected total equals the text amount.

Test data:
  - org_same_as_sponsor_multiple_times.json  (21 amounts, each ×100 too high)
  - org_same_as_sponsor_multiple_times_text.json  (document text with correct total)
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from django.utils import timezone

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import DecisionAmountField
from core.models.types import ActType
from core.services.amount_correction_service import AmountCorrectionService
from core.services.financial_calculation_service import financial_service

# ── Test data paths ──────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent / "data" / "afm_test_patterns" / "extraction" / "payments"
EXTRACTION_JSON = DATA_DIR / "org_same_as_sponsor_multiple_times.json"
TEXT_JSON = (
    Path(__file__).parent.parent / "data" / "amount_correction"
    / "org_same_as_sponsor_multiple_times_text.json"
)

# ── Expected values from the test data ───────────────────────────────
EXPECTED_DB_TOTAL = Decimal("999997.19")
EXPECTED_CORRECTED_TOTAL = Decimal("9999.97")
EXPECTED_FIELD_COUNT = 21


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture
def decision_with_amounts(db):
    """
    Create a Decision with 21 DecisionAmountField rows matching the
    org_same_as_sponsor_multiple_times test data (each ×100 too high).
    """
    data = _load_json(EXTRACTION_JSON)
    sponsor_entries = data["extra_field_values_json"]["sponsor"]

    # Create minimal required FK objects
    act_type, _ = ActType.objects.get_or_create(
        uid="Β.2.2", defaults={"label": "Ανάθεση"}
    )

    decision = Decision.objects.create(
        ada=data["ada"],
        version_id="v1",
        subject="Test decision for amount correction",
        issue_date=timezone.now(),
        submission_timestamp=timezone.now(),
        decision_type=act_type,
        status="PUBLISHED",
        extra_field_values_json=data["extra_field_values_json"],
    )

    # Create one DecisionAmountField per sponsor entry
    for i, entry in enumerate(sponsor_entries):
        amount = Decimal(str(entry["expenseAmount"]["amount"]))
        DecisionAmountField.objects.create(
            decision=decision,
            parent_key_path=f"sponsor[{i}].expenseAmount",
            source_field_name="expenseAmount",
            amount=amount,
            currency="EUR",
        )

    return decision


@pytest.fixture
def decision_with_text(decision_with_amounts):
    """Attach a DocumentExtraction with the correct text to the decision."""
    text_data = _load_json(TEXT_JSON)
    DocumentExtraction.objects.create(
        decision=decision_with_amounts,
        extraction_status=ProcessingStatus.COMPLETED,
        raw_text=text_data["document_text"],
    )
    return decision_with_amounts


@pytest.mark.django_db
class TestGroupCorrection:
    """Test the group-correction path: all amounts ×100 too high."""

    def test_initial_amounts_are_wrong(self, decision_with_amounts):
        """Verify the initial DB state: 21 fields summing to ~1M."""
        fields = decision_with_amounts.amount_fields.all()
        assert fields.count() == EXPECTED_FIELD_COUNT

        total = sum(f.amount for f in fields)
        assert total == EXPECTED_DB_TOTAL

        # FinancialCalculationService should return the wrong total
        svc_total = financial_service.get_decision_total_amount(
            decision_with_amounts
        )
        assert svc_total == EXPECTED_DB_TOTAL

    def test_correction_detects_group_typo(self, decision_with_text):
        """The service should detect that the total is ×100 too high."""
        svc = AmountCorrectionService(threshold=Decimal("0"))
        result = svc.correct_decision(decision_with_text, dry_run=True)

        assert result["status"] == "would_correct"
        assert result["fields_corrected"] == EXPECTED_FIELD_COUNT
        assert result["group_correction"] is True

        # Verify each correction is approximately ÷100.  The last field
        # absorbs the rounding remainder, so its ratio may deviate slightly
        # from exactly 100 — a 1% tolerance accommodates that.
        for c in result["corrections"]:
            assert c["group_correction"] is True
            db_val = Decimal(c["db_amount"])
            corrected_val = Decimal(c["corrected_to"])
            ratio = db_val / corrected_val
            assert abs(ratio - Decimal("100")) < Decimal("1"), (
                f"Field {c['source_field']}: expected ~÷100, got ratio {ratio}"
            )

        # The corrected total must equal the text amount exactly.
        corrected_total = sum(
            Decimal(c["corrected_to"]) for c in result["corrections"]
        )
        assert corrected_total == EXPECTED_CORRECTED_TOTAL

    def test_correction_persists_verified_amounts(self, decision_with_text):
        """After correction, verified_amount should be set on all fields."""
        svc = AmountCorrectionService(threshold=Decimal("0"))
        result = svc.correct_decision(decision_with_text)

        assert result["status"] == "corrected"
        assert result["fields_corrected"] == EXPECTED_FIELD_COUNT

        # All fields should now have verified_amount set
        fields = decision_with_text.amount_fields.all()
        for f in fields:
            assert f.verified_amount is not None
            assert f.amount_verified_at is not None

        # The corrected total should match the text amount
        corrected_total = sum(f.verified_amount for f in fields)
        assert corrected_total == EXPECTED_CORRECTED_TOTAL

    def test_financial_service_uses_corrected_amounts(self, decision_with_text):
        """FinancialCalculationService should return the corrected total."""
        svc = AmountCorrectionService(threshold=Decimal("0"))
        svc.correct_decision(decision_with_text)

        # Refresh from DB to pick up the changes
        decision_with_text.refresh_from_db()

        corrected_total = financial_service.get_decision_total_amount(
            decision_with_text
        )
        assert corrected_total == EXPECTED_CORRECTED_TOTAL

    def test_effective_amount_sum_uses_verified(self, decision_with_text):
        """The effective_amount_sum helper should use verified_amount."""
        from core.services.decision_facets import effective_amount_sum

        svc = AmountCorrectionService(threshold=Decimal("0"))
        svc.correct_decision(decision_with_text)

        # Annotate the decision queryset with effective_amount_sum
        qs = Decision.objects.filter(pk=decision_with_text.pk).annotate(
            total=effective_amount_sum()
        )
        assert qs.first().total == EXPECTED_CORRECTED_TOTAL

    def test_no_correction_when_amounts_match(self, db):
        """When DB amounts match the text, no correction should happen."""
        act_type, _ = ActType.objects.get_or_create(
            uid="Β.2.2", defaults={"label": "Ανάθεση"}
        )
        decision = Decision.objects.create(
            ada="TEST-OK-001",
            version_id="v1",
            subject="Correct decision",
            issue_date=timezone.now(),
            submission_timestamp=timezone.now(),
            decision_type=act_type,
            status="PUBLISHED",
        )
        DecisionAmountField.objects.create(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=Decimal("30000.00"),
        )
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status=ProcessingStatus.COMPLETED,
            raw_text="Εγκρίνεται δαπάνη 30.000,00 €.",
        )

        svc = AmountCorrectionService(threshold=Decimal("0"))
        result = svc.correct_decision(decision)

        assert result["status"] == "consistent"

    def test_no_correction_without_text(self, decision_with_amounts):
        """Without document text (and reading disabled), correction skips."""
        svc = AmountCorrectionService(threshold=Decimal("0"))
        result = svc.correct_decision(
            decision_with_amounts, read_if_missing=False
        )

        assert result["status"] == "skipped"
        assert result["reason"] == "no_text"

    def test_read_if_missing_triggers_extraction(self, db):
        """
        With read_if_missing=True (default), a decision without extracted
        text has its document read first, then correction proceeds.
        """
        from unittest.mock import patch

        act_type, _ = ActType.objects.get_or_create(
            uid="Β.2.2", defaults={"label": "Ανάθεση"}
        )
        decision = Decision.objects.create(
            ada="TEST-READ-001",
            version_id="v1",
            subject="Read document before correcting",
            issue_date=timezone.now(),
            submission_timestamp=timezone.now(),
            decision_type=act_type,
            status="PUBLISHED",
        )
        DecisionAmountField.objects.create(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=Decimal("30000.00"),
        )

        # No DocumentExtraction exists yet — the service must read it.
        def fake_extract(decision_id, provider=None):
            d = Decision.objects.get(id=decision_id)
            DocumentExtraction.objects.create(
                decision=d,
                extraction_status=ProcessingStatus.COMPLETED,
                raw_text="Εγκρίνεται η καταβολή δαπάνης ύψους 300,00 €.",
            )
            return {"status": "extracted"}

        with patch(
            "core.tasks.tasks_decision_ai.extract_decision_text",
            side_effect=fake_extract,
        ) as mock_extract:
            svc = AmountCorrectionService(threshold=Decimal("0"))
            result = svc.correct_decision(decision)

        # Extraction was triggered AND the field got corrected (30.000,00 → 300,00)
        mock_extract.assert_called_once()
        assert result["status"] == "corrected"
        assert result["fields_corrected"] == 1

        decision.refresh_from_db()
        field = decision.amount_fields.first()
        assert field.verified_amount == Decimal("300.00")
        assert field.amount_verified_at is not None

    def test_batch_correction(self, decision_with_text):
        """Batch correction should find and fix the decision."""
        svc = AmountCorrectionService(threshold=Decimal("50000"))
        result = svc.correct_high_value_decisions()

        assert result["corrected"] >= 1
        assert result["total_candidates"] >= 1

        # Verify the decision was actually corrected
        decision_with_text.refresh_from_db()
        fields = decision_with_text.amount_fields.all()
        assert all(f.verified_amount is not None for f in fields)

    def test_batch_skips_already_corrected(self, decision_with_text):
        """Batch correction should skip decisions that are already corrected."""
        svc = AmountCorrectionService(threshold=Decimal("0"))

        # First pass: correct
        svc.correct_decision(decision_with_text)

        # Second pass: should skip (all fields have verified_amount)
        result = svc.correct_high_value_decisions()
        assert result["corrected"] == 0

    def test_group_correction_rejected_when_ratio_outside_tolerance(self, db):
        """
        Group correction must NOT fire when the implied scale factor is not
        ~×100/÷100.  E.g. text total = db_total / 50 → ratio 50, outside
        [99, 101] — the service should refuse to correct.
        """
        act_type, _ = ActType.objects.get_or_create(
            uid="Β.2.2", defaults={"label": "Ανάθεση"}
        )
        decision = Decision.objects.create(
            ada="TEST-REJECT-001",
            version_id="v1",
            subject="Should not be group-corrected",
            issue_date=timezone.now(),
            submission_timestamp=timezone.now(),
            decision_type=act_type,
            status="PUBLISHED",
        )
        # Two fields summing to 50000.00; text says 1000.00 (÷50, not ÷100)
        DecisionAmountField.objects.create(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=Decimal("30000.00"),
        )
        DecisionAmountField.objects.create(
            decision=decision,
            parent_key_path="sponsor[1].expenseAmount",
            source_field_name="expenseAmount",
            amount=Decimal("20000.00"),
        )
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status=ProcessingStatus.COMPLETED,
            raw_text="Εγκρίνεται δαπάνη συνολικού ύψους 1.000,00 €.",
        )

        svc = AmountCorrectionService(threshold=Decimal("0"))
        result = svc.correct_decision(decision)

        # No correction should be applied — ratio 50 is not ~100
        assert result["status"] != "corrected"
        assert result["status"] != "would_correct"
        decision.refresh_from_db()
        assert all(
            f.verified_amount is None for f in decision.amount_fields.all()
        )
