"""
Ground-truth tests for an amount that is **absent from the document text**.

Real case: ADA ``ΨΘΚΧ46ΝΚΟΤ-6ΤΞ`` records ``€997,379,264`` in the API payload,
while the document says ``25.000,00 €`` (and separately ``3.000,00€``).  There
is no ×100/÷100 relationship between the recorded value and any text amount,
so the correction service cannot repair it.

Policy pinned here: the service must **not take the recorded value on trust**.
When cents-bearing amounts exist in the text but none matches the recorded
value, the row is marked ``amount_not_in_text`` (no guessed
``verified_amount``) and leaves every monetary aggregation until the real
amount is established.

The same decision is also a *self-as-counterpart*: the ``donationGiver`` AFM
equals the issuing organization's VAT.  That is a decision-level counterpart
signal and must not be interpreted as "the amount is correct" — the two
verdicts are independent.

Fixtures live in ``data/amount_correction/amount_not_in_text``:
  - ``<ADA>_api.json``          the raw Diavgeia API response
  - ``<ADA>_extraction.json``   the extracted document text
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.services.amount_correction_service import (
    DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT,
    AmountCorrectionService,
)
from core.services.grouped_amount_detection import (
    extract_grouped_amounts,
    verify_amounts_against_grouped,
)

pytestmark = pytest.mark.django_db

DATA_DIR = (
    Path(__file__).parent.parent / "data" / "amount_correction" / "amount_not_in_text"
)
API_JSON = DATA_DIR / "ΨΘΚΧ46ΝΚΟΤ-6ΤΞ_api.json"
EXTRACTION_JSON = DATA_DIR / "ΨΘΚΧ46ΝΚΟΤ-6ΤΞ_extraction.json"

ADA = "ΨΘΚΧ46ΝΚΟΤ-6ΤΞ"
ORG_UID = "100081912"
#: Org VAT, read from the DB in production — NOT from the payload.
ORG_VAT = "090283815"
#: ``extraFieldValues.amountWithVAT.amount`` (9.97379264E8).
RECORDED_AMOUNT = Decimal("997379264.00")
#: The only two cents-bearing amounts in the document.
DOC_PRIMARY_AMOUNT = Decimal("25000.00")
DOC_SECONDARY_AMOUNT = Decimal("3000.00")


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _raw_text() -> str:
    return _load(EXTRACTION_JSON)["core_documentextraction"][0]["raw_text"]


@pytest.fixture
def decision(db):
    """Build the real decision (org + metadata + amount field + text)."""
    from conftest import (
        DecisionFactory,
        DocumentExtractionFactory,
        OrganizationFactory,
    )
    from core.services.entity_amount_extraction_service import (
        EntityAmountExtractionService,
    )

    payload = _load(API_JSON)
    organization = OrganizationFactory(uid=ORG_UID, vat_number=ORG_VAT)
    decision = DecisionFactory(
        ada=ADA,
        organization=organization,
        extra_field_values_json=payload["extraFieldValues"],
    )
    EntityAmountExtractionService().extract_from_decision(decision)
    DocumentExtractionFactory(decision=decision, raw_text=_raw_text())
    return decision


class TestDocumentDetection:
    def test_cents_detector_finds_the_amounts_written_in_the_document(self):
        amounts = [g.amount for g in extract_grouped_amounts(_raw_text())]

        assert DOC_PRIMARY_AMOUNT in amounts
        assert DOC_SECONDARY_AMOUNT in amounts
        assert RECORDED_AMOUNT not in amounts

    def test_recorded_amount_is_neither_present_nor_a_decimal_clone(self):
        result = verify_amounts_against_grouped(_raw_text(), [RECORDED_AMOUNT])

        match = result.matches[0]
        assert match.found_exact is False
        assert match.clone_factor is None
        assert match.matched_text_amount is None

    def test_amounts_with_cents_process_exposes_the_document_amounts(self):
        """The UI's "Amounts with Cents" text process sees 25.000 and 3.000."""
        from core.services.text_processes.amount_grouped import GroupedAmountProcess

        result = GroupedAmountProcess().detect(_raw_text())
        values = [Decimal(span.value["amount"]) for span in result.spans]

        assert DOC_PRIMARY_AMOUNT in values
        assert DOC_SECONDARY_AMOUNT in values
        assert RECORDED_AMOUNT not in values


class TestCorrectionRefusesToTrustTheRecordedAmount:
    def test_dry_run_reports_unconfirmed_without_writing(self, decision):
        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision, dry_run=True
        )

        assert result["status"] == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        assert result["corrections"] == []
        assert [u["db_amount"] for u in result["unconfirmed"]] == [str(RECORDED_AMOUNT)]

        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount is None
        assert field.invalid_amount_reason is None

    def test_applying_marks_the_row_unconfirmed_and_never_guesses(self, decision):
        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )

        assert result["status"] == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        assert result["corrections"] == []
        assert result["unconfirmed"]

        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount is None
        assert field.amount_verified_at is None
        assert field.invalid_amount_reason == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        assert field.invalid_amount_value is None

    def test_unconfirmed_amount_leaves_monetary_totals(self, decision):
        from core.services.financial_calculation_service import financial_service

        assert financial_service.get_decision_total_amount(decision) == RECORDED_AMOUNT

        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        assert financial_service.get_decision_total_amount(decision) == Decimal("0.00")

    def test_mixed_decision_corrects_one_field_and_flags_the_other(self, decision):
        """A repair on one field must not suppress another field's flag."""
        from conftest import DecisionAmountFieldFactory

        recorded_field = decision.amount_fields.get()
        corrected_field = DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].otherAmount",
            source_field_name="otherAmount",
            amount=Decimal("300000.00"),  # text says 3.000,00 → ÷100 clone
        )

        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )

        assert result["status"] == "corrected"
        assert [c["field_id"] for c in result["corrections"]] == [corrected_field.id]
        assert [u["field_id"] for u in result["unconfirmed"]] == [recorded_field.id]

        corrected_field.refresh_from_db()
        recorded_field.refresh_from_db()
        assert corrected_field.verified_amount == Decimal("3000.00")
        assert recorded_field.verified_amount is None
        assert (
            recorded_field.invalid_amount_reason
            == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        )

    def test_batch_counts_the_case_and_does_not_reselect_it(self, decision):
        summary = AmountCorrectionService(
            threshold=Decimal("0")
        ).correct_high_value_decisions()

        assert summary["amount_not_in_text"] == 1
        assert summary["corrected"] == 0
        assert summary["results"][0]["status"] == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT

        second = AmountCorrectionService(
            threshold=Decimal("0")
        ).correct_high_value_decisions()
        assert second["total_candidates"] == 0


class TestDetectorFramework:
    def test_decimal_shift_detector_reports_unconfirmed(self, decision):
        from core.services.data_quality import (
            get_detector,
            run_detectors,
            summarize,
        )

        detector = get_detector("decimal-shift")
        outcome = detector.scan(decision)

        assert outcome.detected
        assert all(
            f.reason == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT for f in outcome.findings
        )
        assert all(f.suggested == "" for f in outcome.findings)

        summary = summarize(run_detectors(decision, [detector], dry_run=False))
        assert summary["status"] == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        assert summary["corrections"] == []
        assert summary["flagged"]

        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.invalid_amount_reason == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT


class TestDetailApiDoesNotClaimTheAmountIsCorrect:
    def test_detail_exposes_both_independent_signals(self, decision):
        from core.services.non_monetary_value_guard import collect_self_counterparts

        assert collect_self_counterparts(decision) == {ORG_VAT}

        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        from api.views.decisions.details import decision_detail
        from django.test import RequestFactory

        request = RequestFactory().get(f"/api/decisions/{decision.id}/")
        payload = decision_detail(request, decision.id).data

        # The amount is not trusted…
        assert payload["has_invalid_amount"] is True
        assert payload["invalid_amount_reason"] == DISCREPANCY_REASON_AMOUNT_NOT_IN_TEXT
        assert payload["recorded_amount"] == float(RECORDED_AMOUNT)
        assert payload["amount"] is None
        assert payload["has_corrected_amounts"] is False

        # …while the counterpart signal stays independent.
        assert payload["has_self_counterpart"] is True
        assert payload["self_counterpart_afm"] == ORG_VAT
