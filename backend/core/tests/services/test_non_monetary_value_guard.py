"""
Tests for the non-monetary-value-as-amount guard (synthetic factory-based).

Two canonical cases:

- **AFM**: decision ``Ψ0Α74690Β9-52Ρ`` — sponsor AFM ``099370337``
  (VIOLAK INTERNATIONAL) recorded as ``expenseAmount`` ``9.9370337E7``
  = €99,370,337.00.  The document text literally contains ``99.370.337,00``,
  so without the guard the "exact match wins" policy confirms the bogus value.
- **KAE**: the budget KAE ``70.6273.001`` recorded as ``expenseAmount``,
  ``7.06273001E8`` = €706,273,001.00 — while a sibling entry is correct
  (amount ``27910.03``, kae ``25.6211.001``).

These use factories to exercise the guard in isolation.  For the same cases
driven from **real Diavgeia API payloads** end-to-end, see
``test_non_monetary_value_pipeline.py``.

Covered:
  - guard primitives (formatting variants, leading zeros, near-misses)
  - ``verify_decision`` (regex) flags ``afm_as_amount`` / ``kae_as_amount``
  - ``verify_with_grouped`` returns the same verdict
  - ``AmountCorrectionService`` never writes such a value into verified_amount
  - DB-only discovery helper + ``find_amount_anomalies`` command (JSON/CSV)
  - decisions without AFMs/KAEs behave unchanged
"""

from decimal import Decimal

import pytest

from core.services.non_monetary_value_guard import (
    DISCREPANCY_REASON_AFM,
    DISCREPANCY_REASON_KAE,
    KIND_AFM,
    KIND_KAE,
    collect_non_monetary_values,
    collect_counterpart_afms,
    collect_kae_codes,
    extract_afm_amount_spans,
    is_afm_amount,
    match_afm_amount,
    match_kae_amount,
)
from core.services.amount_correction_service import AmountCorrectionService
from core.services.amount_verification_service import AmountVerificationService

pytestmark = pytest.mark.django_db

AFM = "099370337"
AFM_AMOUNT = Decimal("99370337.00")

# ── KAE canonical case ───────────────────────────────────────────────────────
# Two sponsor entries in the same decision: the first has the KAE
# "70.6273.001" recorded as expenseAmount (7.06273001E8 = €706,273,001); the
# second is correct (amount 27910.03, kae "25.6211.001").
KAE_MISPLACED = "70.6273.001"  # → digits 706273001 == 7.06273001E8
KAE_MISPLACED_AMOUNT = Decimal("706273001.00")
KAE_CORRECT = "25.6211.001"  # → digits 256211001
KAE_CORRECT_AMOUNT = Decimal("27910.03")

REAL_KAE_CASE_EXTRACTION_JSON = {
    "ada": "TEST-KAE-1",
    "extra_field_values_json": {
        "sponsor": [
            {
                "sponsorAFMName": {"afm": "090000045", "afmType": "EL"},
                "expenseAmount": {
                    "amount": 7.06273001e8,
                    "currency": "EUR",
                    "kae": KAE_MISPLACED,
                },
            },
            {
                "sponsorAFMName": {"afm": "090000045", "afmType": "EL"},
                "expenseAmount": {
                    "amount": 27910.03,
                    "currency": "EUR",
                    "kae": KAE_CORRECT,
                },
            },
        ],
    },
}

# Real Diavgeia API payload for Ψ0Α74690Β9-52Ρ (trimmed)
REAL_CASE_EXTRACTION_JSON = {
    "ada": "Ψ0Α74690Β9-52Ρ",
    "extra_field_values_json": {
        "org": {"afm": "997162988", "name": "ΓΕΝΙΚΟ ΝΟΣΟΚΟΜΕΙΟ ΔΙΔΥΜΟΤΕΙΧΟΥ"},
        "sponsor": [
            {
                "sponsorAFMName": {
                    "afm": AFM,
                    "afmType": "EL",
                    "name": "VIOLAK INTERNATIONAL ΝΟΣΟΚΟΜΕΙΑΚΟΥ "
                    "ΕΞΟΠΛΙΣΜΟΥ ΑΝΩΝΥΜΗ ΕΜΠΟΡΙΚΗ ΕΤΑΙΡΕΙΑ",
                },
                "expenseAmount": {"amount": 9.9370337e7, "currency": "EUR"},
                "kae": "1311",
            }
        ],
    },
}


# ── Guard primitives (no DB) ─────────────────────────────────────────────────


class TestMatchAfmAmount:
    def test_exact_numeric_match(self):
        assert match_afm_amount(Decimal("99370337.00"), {AFM}) == AFM

    def test_leading_zero_insensitive(self):
        assert match_afm_amount(Decimal("99370337.00"), {AFM}) == AFM
        assert match_afm_amount(Decimal("99370337"), {AFM}) == AFM

    def test_amount_with_cents_is_never_afm(self):
        assert match_afm_amount(Decimal("99370337.50"), {AFM}) is None

    def test_near_miss_is_not_afm(self):
        """A legitimate amount coincidentally near an AFM still confirms."""
        assert match_afm_amount(Decimal("99370338.00"), {AFM}) is None

    def test_empty_afm_set(self):
        assert match_afm_amount(AFM_AMOUNT, set()) is None


class TestSpanFormattingVariants:
    """AFM formatted as amount in the document text."""

    @pytest.mark.parametrize(
        "span",
        [
            "99.370.337,00",  # Greek format (the real case)
            "99,370,337.00",  # English format
            "99370337,00",  # bare integer + Greek cents
            "99370337.00",  # bare integer + English cents
            "099.370.337,00",  # leading zero preserved
            "099370337,00",  # leading zero, bare
            "99.370.337",  # no cents at all
        ],
    )
    def test_afm_formatted_variants(self, span):
        assert match_afm_amount(None, {AFM}, raw_span=span) == AFM
        assert is_afm_amount(None, {AFM}, raw_span=span)

    def test_non_zero_cents_rejected(self):
        assert match_afm_amount(None, {AFM}, raw_span="99.370.337,50") is None

    def test_extract_spans_from_text(self):
        text = "Πληρωμή ποσού 99.370.337,00 € προς τον προμηθευτή."
        hits = extract_afm_amount_spans(text, {AFM})
        assert len(hits) == 1
        assert hits[0]["afm"] == AFM
        assert hits[0]["raw"] == "99.370.337,00"

    def test_extract_spans_no_match(self):
        text = "Πληρωμή ποσού 99.370.338,00 € προς τον προμηθευτή."
        assert extract_afm_amount_spans(text, {AFM}) == []


# ── AFM collection ───────────────────────────────────────────────────────────


class TestCollectCounterpartAfms:
    def test_from_sponsor_metadata(self):
        from conftest import DecisionFactory

        decision = DecisionFactory(
            extra_field_values_json=REAL_CASE_EXTRACTION_JSON[
                "extra_field_values_json"
            ]
        )
        assert collect_counterpart_afms(decision) == {AFM}

    def test_from_entity_relationship(self):
        from conftest import (
            AFMEntityFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
        )

        decision = DecisionFactory()
        entity = AFMEntityFactory(afm=AFM)
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="sponsorAFMName"
        )
        assert collect_counterpart_afms(decision) == {AFM}

    def test_no_afms(self):
        from conftest import DecisionFactory

        decision = DecisionFactory()
        assert collect_counterpart_afms(decision) == set()


# ── Verification service (regex path) ────────────────────────────────────────


def _make_violak_decision(text: str, amount: Decimal = AFM_AMOUNT):
    """Build the canonical Ψ0Α74690Β9-52Ρ scenario as a test decision."""
    from conftest import (
        DecisionAmountFieldFactory,
        DecisionFactory,
        DocumentExtractionFactory,
    )

    decision = DecisionFactory(
        extra_field_values_json=REAL_CASE_EXTRACTION_JSON[
            "extra_field_values_json"
        ]
    )
    DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="sponsor[0].expenseAmount",
        source_field_name="expenseAmount",
        amount=amount,
    )
    DocumentExtractionFactory(decision=decision, raw_text=text)
    return decision


def _make_kae_decision(text: str, amount: Decimal = KAE_MISPLACED_AMOUNT):
    """Build the canonical KAE-as-amount scenario as a test decision."""
    from conftest import (
        DecisionAmountFieldFactory,
        DecisionFactory,
        DocumentExtractionFactory,
    )

    decision = DecisionFactory(
        extra_field_values_json=REAL_KAE_CASE_EXTRACTION_JSON[
            "extra_field_values_json"
        ]
    )
    DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="sponsor[0].expenseAmount",
        source_field_name="expenseAmount",
        amount=amount,
    )
    DocumentExtractionFactory(decision=decision, raw_text=text)
    return decision


class TestVerifyDecisionAfmGuard:
    def test_real_case_flagged_as_afm_as_amount(self):
        """Canonical case: text contains 99.370.337,00 — must NOT confirm."""
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 € "
            "προς VIOLAK INTERNATIONAL (ΑΦΜ 099370337)."
        )
        result = AmountVerificationService().verify_decision(
            decision, method="regex"
        )

        assert result["status"] == "completed"
        assert result["has_discrepancy"] is True
        assert result["discrepancy_reason"] == DISCREPANCY_REASON_AFM

        from core.models.document_analysis import (
            TextProcessResolution,
            TextProcessRun,
        )

        run = TextProcessRun.objects.get(
            extraction=decision.text_extraction, process="amount"
        )
        assert run.meta["discrepancy_reason"] == DISCREPANCY_REASON_AFM
        assert run.meta["counterpart_afm"] == AFM
        assert "[AFM-AS-AMOUNT]" in run.meta["discrepancy_note"]

        resolution = TextProcessResolution.objects.get(
            decision=decision, process="amount"
        )
        assert resolution.has_discrepancy is True
        assert "[AFM-AS-AMOUNT]" in resolution.note

    def test_legitimate_large_amount_still_confirmed(self):
        """AFM 099370337 but amount €99,370,338.00 → no AFM flag."""
        decision = _make_violak_decision(
            text="Εγκρίνεται δαπάνη ποσού 99.370.338,00 €.",
            amount=Decimal("99370338.00"),
        )
        result = AmountVerificationService().verify_decision(
            decision, method="regex"
        )

        assert result["status"] == "completed"
        assert result["has_discrepancy"] is False
        assert result["discrepancy_reason"] is None

    def test_decision_without_afm_unchanged(self):
        """No sponsor/counterpart AFM → behaviour unchanged."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("30000.00")
        )
        DocumentExtractionFactory(
            decision=decision, raw_text="Εγκρίνεται δαπάνη 30.000,00 €."
        )
        result = AmountVerificationService().verify_decision(
            decision, method="regex"
        )

        assert result["status"] == "completed"
        assert result["has_discrepancy"] is False
        assert result["discrepancy_reason"] is None

    def test_european_format_variants_flagged(self):
        """English and bare formatting variants of the AFM are flagged."""
        for text in (
            "Εγκρίνεται δαπάνη 99,370,337.00 €.",
            "Εγκρίνεται δαπάνη 99370337,00 €.",
            "Εγκρίνεται δαπάνη 099.370.337,00 €.",
        ):
            decision = _make_violak_decision(text)
            result = AmountVerificationService().verify_decision(
                decision, method="regex"
            )
            assert result["discrepancy_reason"] == DISCREPANCY_REASON_AFM, text


class TestVerifyWithGroupedAfmGuard:
    def test_cents_detector_path_same_verdict(self):
        """verify_with_grouped reports the same afm_as_amount verdict."""
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        result = AmountVerificationService().verify_with_grouped(decision)

        assert result["status"] == "completed"
        assert result["has_discrepancy"] is True
        assert result["discrepancy_reason"] == DISCREPANCY_REASON_AFM

    def test_cents_detector_no_afm_unchanged(self):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("30000.00")
        )
        DocumentExtractionFactory(
            decision=decision, raw_text="Εγκρίνεται δαπάνη 30.000,00 €."
        )
        result = AmountVerificationService().verify_with_grouped(decision)
        assert result["status"] == "completed"
        assert result["has_discrepancy"] is False
        assert result["discrepancy_reason"] is None


# ── Correction service ───────────────────────────────────────────────────────


class TestCorrectionAfmGuard:
    def test_correction_never_writes_afm_into_verified_amount(self):
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )

        # Not corrected to the AFM value
        decision.refresh_from_db()
        for field in decision.amount_fields.all():
            assert field.verified_amount is None
            assert field.amount_verified_at is None

        # Every amount is the AFM → reported as flagged, never as corrected
        assert result["status"] == DISCREPANCY_REASON_AFM
        assert "fields_corrected" not in result
        assert result["matched_values"]

    def test_correction_flags_field_as_invalid(self):
        """The row is marked invalid so facets exclude it from totals."""
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.invalid_amount_reason == DISCREPANCY_REASON_AFM
        assert field.invalid_amount_value == AFM
        assert field.invalid_amount_flagged_at is not None
        # ...but no monetary value was invented
        assert field.verified_amount is None

    def test_dry_run_does_not_flag(self):
        """dry_run must report the flag without persisting it."""
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        result = AmountCorrectionService(
            threshold=Decimal("0")
        ).correct_decision(decision, dry_run=True)

        assert result["status"] == DISCREPANCY_REASON_AFM
        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.invalid_amount_reason is None
        assert field.invalid_amount_flagged_at is None

    def test_all_anomaly_skips_document_read(self):
        """
        When every recorded amount is an AFM/KAE, correction must not
        download/extract the document — the DB-only guard is enough.
        """
        from unittest.mock import patch

        # No DocumentExtractionFactory on purpose: only the guard can answer.
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory(
            extra_field_values_json=REAL_CASE_EXTRACTION_JSON[
                "extra_field_values_json"
            ]
        )
        DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=AFM_AMOUNT,
        )

        with patch.object(
            AmountCorrectionService, "_ensure_text_extraction"
        ) as mock_extract, patch.object(
            AmountCorrectionService, "_get_text", return_value=None
        ):
            result = AmountCorrectionService(
                threshold=Decimal("0")
            ).correct_decision(decision)

        mock_extract.assert_not_called()
        assert result["status"] == DISCREPANCY_REASON_AFM
        assert result["matched_values"]

    def test_anomaly_alongside_real_correction(self):
        """
        One AFM field + one genuinely mis-typed amount: the real field is
        corrected, the AFM is only flagged, and the status is ``corrected``.

        Guards against the bug where a flagged (never-written) AFM field made
        the result claim a correction that did not happen.
        """
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory(
            extra_field_values_json=REAL_CASE_EXTRACTION_JSON[
                "extra_field_values_json"
            ]
        )
        afm_field = DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=AFM_AMOUNT,
        )
        real_field = DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].otherAmount",
            source_field_name="otherAmount",
            amount=Decimal("300000.00"),
        )
        DocumentExtractionFactory(
            decision=decision, raw_text="Εγκρίνεται δαπάνη ποσού 3.000,00 €."
        )

        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )

        assert result["status"] == "corrected"
        assert result["fields_corrected"] == 1
        assert [c["field_id"] for c in result["corrections"]] == [real_field.id]
        assert [f["field_id"] for f in result["flagged"]] == [afm_field.id]

        afm_field.refresh_from_db()
        real_field.refresh_from_db()
        assert afm_field.verified_amount is None
        assert real_field.verified_amount == Decimal("3000.00")

    def test_correction_afm_only_case_status(self):
        """When the only 'match' is the AFM itself, status reflects it."""
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )
        assert result["status"] == "afm_as_amount"
        assert all(
            field.verified_amount is None
            for field in decision.amount_fields.all()
        )

    def test_correction_normal_shift_still_works(self):
        """Non-AFM decimal shifts are still corrected as before."""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("30000.00")
        )
        DocumentExtractionFactory(
            decision=decision, raw_text="Εγκρίνεται δαπάνη 300,00 €."
        )
        result = AmountCorrectionService(threshold=Decimal("0")).correct_decision(
            decision
        )
        assert result["status"] == "corrected"
        field = decision.amount_fields.first()
        assert field.verified_amount == Decimal("300.00")


# ── Batch summary counting ───────────────────────────────────────────────────


class TestBatchSummary:
    def test_verify_batch_counts_afm_cases(self):
        service = AmountVerificationService(threshold=Decimal("1"))
        # One AFM case + one good case
        _make_violak_decision("Εγκρίνεται δαπάνη ποσού 99.370.337,00 €.")

        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        good = DecisionFactory()
        DecisionAmountFieldFactory(decision=good, amount=Decimal("30000.00"))
        DocumentExtractionFactory(
            decision=good, raw_text="Εγκρίνεται δαπάνη 30.000,00 €."
        )

        summary = service.verify_high_value_decisions()
        assert summary["afm_as_amount_discrepancies"] == 1
        assert summary["discrepancies"] >= 1
        assert summary["verified"] == 2


# ── DB-only discovery (helper + management command) ──────────────────────────


class TestFindAfmAmountFields:
    def test_finds_field_matching_counterpart_afm(self):
        from core.services.non_monetary_value_guard import find_afm_amount_fields

        decision = _make_violak_decision("irrelevant — DB-only detector")
        hits = find_afm_amount_fields(decision)
        assert len(hits) == 1
        field, afm = hits[0]
        assert afm == AFM
        assert str(field.amount) == str(AFM_AMOUNT)

    def test_ignores_legitimate_amount(self):
        from core.services.non_monetary_value_guard import find_afm_amount_fields

        decision = _make_violak_decision(
            "irrelevant", amount=Decimal("99370338.00")
        )
        assert find_afm_amount_fields(decision) == []

    def test_ignores_decision_without_afms(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.services.non_monetary_value_guard import find_afm_amount_fields

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=AFM_AMOUNT)
        assert find_afm_amount_fields(decision) == []


class TestFindAmountAnomaliesCommand:
    def _run(self, *args):
        import io

        from django.core.management import call_command

        out = io.StringIO()
        call_command("find_amount_anomalies", *args, stdout=out)
        return out.getvalue()

    def test_reports_afm_case(self):
        decision = _make_violak_decision("irrelevant — DB-only detector")
        output = self._run()
        assert decision.ada in output
        assert AFM in output
        assert "1 decision(s)" in output

    def test_reports_kae_case(self):
        decision = _make_kae_decision("irrelevant — DB-only detector")
        output = self._run()
        assert decision.ada in output
        assert KAE_MISPLACED.replace(".", "") in output
        assert "KAE" in output

    def test_kind_filter_excludes_kae(self):
        _make_kae_decision("irrelevant — DB-only detector")
        output = self._run("--kind", "afm")
        assert "No non-monetary-value-as-amount cases found" in output

    def test_json_output(self, tmp_path):
        import json

        decision = _make_violak_decision("irrelevant — DB-only detector")
        out_file = tmp_path / "afm.json"
        self._run("--output", str(out_file))

        data = json.loads(out_file.read_text(encoding="utf-8"))
        assert data["hit_count"] == 1
        assert data["anomaly_count"] == 1
        assert data["hits"][0]["ada"] == decision.ada
        assert data["hits"][0]["anomalies"][0]["matched_value"] == AFM
        assert data["hits"][0]["anomalies"][0]["kind"] == KIND_AFM

    def test_csv_output(self, tmp_path):
        import csv

        decision = _make_kae_decision("irrelevant — DB-only detector")
        out_file = tmp_path / "anomalies.csv"
        self._run("--csv", str(out_file))

        with out_file.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        assert len(rows) == 1
        assert rows[0]["ada"] == decision.ada
        assert rows[0]["kind"] == KIND_KAE
        assert rows[0]["matched_value"] == "706273001"

    def test_ada_targets_single_decision_below_default_bounds(self):
        # 123456 is below the default --min-amount floor, but --ada inspects
        # the decision regardless of amount bounds.
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
        )

        decision = DecisionFactory()
        entity = AFMEntityFactory(afm="000123456")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="sponsorAFMName"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("123456.00"))
        output = self._run("--ada", decision.ada)
        assert decision.ada in output

    def test_skips_small_amounts(self):
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
        )

        # AFM recorded as amount but below the candidate lower bound
        decision = DecisionFactory()
        entity = AFMEntityFactory(afm="000123456")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="sponsorAFMName"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("123456.00"))
        output = self._run("--min-amount", "200000")
        assert decision.ada not in output

    def test_clean_database_reports_none(self):
        output = self._run()
        assert "No non-monetary-value-as-amount cases found" in output

    def test_marks_already_flagged(self):
        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        # Run the guard so a resolution note exists, then discover it.
        AmountVerificationService().verify_decision(decision, method="regex")
        output = self._run()
        assert "[✓ flagged]" in output


# ── KAE-as-amount (budget KAE recorded as the amount) ───────────────────────


def _make_kae_text(amount: str = "706.273.001,00") -> str:
    return f"Εγκρίνεται δαπάνη ποσού {amount} €."


class TestKaeGuardPrimitives:
    def test_collect_kae_codes(self):
        from conftest import DecisionFactory

        decision = DecisionFactory(
            extra_field_values_json=REAL_KAE_CASE_EXTRACTION_JSON[
                "extra_field_values_json"
            ]
        )
        assert collect_kae_codes(decision) == {"706273001", "256211001"}

    def test_no_kae_codes(self):
        from conftest import DecisionFactory

        assert collect_kae_codes(DecisionFactory()) == set()

    def test_match_kae_amount_numeric(self):
        assert match_kae_amount(KAE_MISPLACED_AMOUNT, {"706273001"}) == "706273001"

    def test_match_kae_amount_ignores_correct_amount(self):
        assert match_kae_amount(KAE_CORRECT_AMOUNT, {"706273001"}) is None

    def test_match_kae_amount_rejects_cents(self):
        assert match_kae_amount(Decimal("706273001.50"), {"706273001"}) is None

    def test_match_kae_amount_span_variants(self):
        for span in ("70.6273.001,00", "706273001,00", "706273001.00"):
            assert match_kae_amount(None, {"706273001"}, raw_span=span) == (
                "706273001"
            ), span


class TestKaeAnomalyCollection:
    def test_collects_kae_anomaly(self):
        decision = _make_kae_decision("irrelevant")
        anomalies = collect_non_monetary_values(decision)
        assert len(anomalies) == 1
        assert anomalies[0].kind == KIND_KAE
        assert anomalies[0].reason == DISCREPANCY_REASON_KAE
        assert anomalies[0].matched_value == "706273001"

    def test_raw_context_sibling_match(self):
        """Same-container kae is matched even if the decision-wide set misses."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory(extra_field_values_json={})
        DecisionAmountFieldFactory(
            decision=decision,
            amount=KAE_MISPLACED_AMOUNT,
            raw_context={"amount": 7.06273001e8, "kae": KAE_MISPLACED},
        )
        anomalies = collect_non_monetary_values(decision, use_raw_context=True)
        assert len(anomalies) == 1
        assert anomalies[0].kind == KIND_KAE
        assert anomalies[0].matched_value == "706273001"


class TestKaeVerification:
    def test_kae_flagged_not_confirmed(self):
        decision = _make_kae_decision(_make_kae_text())
        result = AmountVerificationService().verify_decision(
            decision, method="regex"
        )
        assert result["status"] == "completed"
        assert result["has_discrepancy"] is True
        assert result["discrepancy_reason"] == DISCREPANCY_REASON_KAE

        from core.models.document_analysis import (
            TextProcessResolution,
            TextProcessRun,
        )

        run = TextProcessRun.objects.get(
            extraction=decision.text_extraction, process="amount"
        )
        assert run.meta["discrepancy_reason"] == DISCREPANCY_REASON_KAE
        assert run.meta["counterpart_kae"] == "706273001"
        assert "counterpart_afm" not in run.meta
        assert "[KAE-AS-AMOUNT]" in run.meta["discrepancy_note"]

        resolution = TextProcessResolution.objects.get(
            decision=decision, process="amount"
        )
        assert resolution.has_discrepancy is True
        assert "[KAE-AS-AMOUNT]" in resolution.note

    def test_legitimate_amount_below_kae_not_flagged(self):
        """The correct sibling amount (27,910.03) is not flagged."""
        decision = _make_kae_decision(
            "Εγκρίνεται δαπάνη ποσού 27.910,03 €.",
            amount=KAE_CORRECT_AMOUNT,
        )
        result = AmountVerificationService().verify_decision(
            decision, method="regex"
        )
        assert result["discrepancy_reason"] is None

    def test_grouped_path_flags_kae(self):
        decision = _make_kae_decision(_make_kae_text())
        result = AmountVerificationService().verify_with_grouped(decision)
        assert result["status"] == "completed"
        assert result["discrepancy_reason"] == DISCREPANCY_REASON_KAE

    def test_batch_counts_kae(self):
        _make_kae_decision(_make_kae_text(), amount=Decimal("706273001.00"))
        summary = AmountVerificationService(threshold=Decimal("1")).verify_high_value_decisions()
        assert summary["kae_as_amount_discrepancies"] >= 1


class TestKaeCorrection:
    def test_correction_never_writes_kae_into_verified_amount(self):
        decision = _make_kae_decision(_make_kae_text())
        result = AmountCorrectionService(threshold=Decimal("1")).correct_decision(
            decision
        )
        decision.refresh_from_db()
        for field in decision.amount_fields.all():
            assert field.verified_amount is None

        assert result["status"] in ("kae_as_amount", "corrected")
        if result["status"] == "kae_as_amount":
            assert result["discrepancy_reason"] == DISCREPANCY_REASON_KAE
            assert result["matched_values"]




# ── Known-bad amounts are excluded from money, surfaced for review ──────────


class TestInvalidAmountExcludedFromTotals:
    """A flagged (AFM/KAE) amount must never count as money."""

    def test_decision_total_drops_flagged_amount(self):
        from core.services.financial_calculation_service import financial_service

        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        # Before the guard runs, the bogus amount counts (the bug).
        assert financial_service.get_decision_total_amount(decision) == AFM_AMOUNT

        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        # After flagging, the only field is excluded → total is zero.
        assert financial_service.get_decision_total_amount(decision) == Decimal(
            "0.00"
        )

    def test_facet_sum_drops_flagged_amount(self):
        from core.models.decisions import Decision
        from core.services.decision_facets import effective_amount_sum

        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        total = Decision.objects.filter(id=decision.id).aggregate(
            t=effective_amount_sum()
        )["t"]
        assert total in (None, Decimal("0.00"))

    def test_list_projection_hides_invalid_amount(self):
        from core.models.decisions import Decision
        from core.services.decision_projections import paginate_decisions

        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        data = paginate_decisions(
            Decision.objects.filter(id=decision.id), page=1, page_size=10
        )
        row = data["results"][0]
        assert row["amount"] is None
        assert row["has_invalid_amount"] is True


class TestFeedbackPoolIncludesFlagged:
    """Flagged decisions must reach the feedback pool (to be reported back)."""

    def test_pending_decisions_includes_flagged(self):
        from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        pending = set(
            DiavgeiaFeedbackService()
            .pending_decisions()
            .values_list("id", flat=True)
        )
        assert decision.id in pending

    def test_unflagged_decision_not_pending(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))

        pending = set(
            DiavgeiaFeedbackService()
            .pending_decisions()
            .values_list("id", flat=True)
        )
        assert decision.id not in pending


class TestInvalidAmountDetailApi:
    """The detail API must expose why the amount is unusable."""

    def test_detail_reports_invalid_amount(self):
        from api.views.decisions.details import decision_detail

        decision = _make_violak_decision(
            "Εγκρίνεται δαπάνη ποσού 99.370.337,00 €."
        )
        AmountCorrectionService(threshold=Decimal("0")).correct_decision(decision)

        from django.test import RequestFactory

        request = RequestFactory().get(f"/api/decisions/{decision.id}/")
        response = decision_detail(request, decision.id)
        payload = response.data

        assert payload["has_invalid_amount"] is True
        assert payload["invalid_amount_reason"] == DISCREPANCY_REASON_AFM
        assert payload["invalid_amount_value"] == AFM
