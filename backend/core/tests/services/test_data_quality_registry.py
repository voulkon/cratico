"""
Tests for the data-quality detector framework
(``core/services/data_quality``).

Two layers:

* **Registry invariants** — every registered detector is discoverable, its
  ``mode_key`` is a declared mode, and an unknown mode raises rather than
  silently correcting nothing.  These are what keep "add a detector" a
  one-file change.
* **End-to-end contract** — ``run_detectors`` + ``summarize`` over the two real
  detectors: the decimal-shift detector plans a repair and writes
  ``verified_amount``; the non-monetary detector flags a row and never writes a
  monetary value.
"""

from decimal import Decimal

import pytest

pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# Registry invariants
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_registers_both_detectors(self):
        from core.services.data_quality import REGISTRY

        assert list(REGISTRY) == ["decimal-shift", "non-monetary-value"]

    def test_every_mode_key_is_a_declared_mode(self):
        from core.services.data_quality import MODES, REGISTRY

        for detector in REGISTRY.values():
            assert detector.mode_key in MODES
            assert detector.slug
            assert detector.name
            assert detector.description

    def test_only_the_repairing_detector_declares_can_repair(self):
        """``can_repair`` is the contract the admin/pool rely on: a detector
        that cannot repair must never write a monetary value."""
        from core.services.data_quality import get_detector

        assert get_detector("decimal-shift").can_repair is True
        assert get_detector("non-monetary-value").can_repair is False

    def test_resolve_detectors_expands_modes(self):
        from core.services.data_quality import resolve_detectors

        assert [d.slug for d in resolve_detectors("decimal_shift")] == ["decimal-shift"]
        assert [d.slug for d in resolve_detectors("non_monetary")] == [
            "non-monetary-value"
        ]
        assert [d.slug for d in resolve_detectors("both")] == [
            "decimal-shift",
            "non-monetary-value",
        ]

    def test_unknown_mode_raises(self):
        from core.services.data_quality import resolve_detectors

        with pytest.raises(ValueError, match="unknown detector mode"):
            resolve_detectors("typo")

    def test_duplicate_slug_is_rejected(self):
        from core.services.data_quality import DecimalShiftDetector, register

        with pytest.raises(ValueError, match="duplicate detector slug"):
            register(DecimalShiftDetector())

    def test_resolve_mode_bounds_narrows_to_the_intersection(self):
        from core.services.data_quality import resolve_mode_bounds

        assert resolve_mode_bounds("decimal_shift")[1] is None
        assert resolve_mode_bounds("non_monetary")[1] == Decimal("100000000000")
        # "both" contains an unbounded detector → unbounded overall.
        assert resolve_mode_bounds("both")[1] is None

    def test_describe_detectors_shape(self):
        from core.services.data_quality import describe_detectors

        described = describe_detectors()
        assert {d["slug"] for d in described} == {"decimal-shift", "non-monetary-value"}
        assert all({"slug", "name", "mode", "needs_text"} <= set(d) for d in described)


class TestModeVocabularyStaysInSync:
    """The job model, the registry and the admin form must agree on modes.

    A new detector adds a ``mode_key``; forgetting to add it to
    ``CorrectionJobMode`` would make the admin form unable to select it.
    """

    def test_every_choice_mode_resolves_to_at_least_one_detector(self):
        from core.models.amount_correction_job import CorrectionJobMode
        from core.services.data_quality import resolve_detectors

        for value, _label in CorrectionJobMode.choices:
            assert resolve_detectors(value), f"mode {value!r} resolves to nothing"

    def test_every_detector_mode_is_offered_by_the_job_model(self):
        from core.models.amount_correction_job import CorrectionJobMode
        from core.services.data_quality import REGISTRY

        offered = {value for value, _label in CorrectionJobMode.choices}
        for detector in REGISTRY.values():
            assert detector.mode_key in offered

    def test_admin_form_offers_the_model_choices(self):
        from admin_custom.admin_classes.decisions import AmountCorrectionForm
        from core.models.amount_correction_job import CorrectionJobMode

        form = AmountCorrectionForm()
        assert list(form.fields["mode"].choices) == list(CorrectionJobMode.choices)
        assert "max_amount" in form.fields
        # Both amount bounds are optional-safe: only the minimum is required.
        assert form.fields["threshold"].required is True
        assert form.fields["max_amount"].required is False


# ---------------------------------------------------------------------------
# Decimal-shift detector
# ---------------------------------------------------------------------------


class TestDecimalShiftDetector:
    def _shifted_decision(self, db_amount="3000000.00", text="30.000,00"):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal(db_amount))
        DocumentExtractionFactory(decision=decision, raw_text=text)
        return decision

    def test_scan_plans_a_repair_without_writing(self):
        from core.services.data_quality import get_detector

        decision = self._shifted_decision()
        outcome = get_detector("decimal-shift").scan(decision)

        assert outcome.detected
        assert outcome.written == 0
        finding = outcome.findings[0]
        assert finding.reason == "decimal_shift"
        assert finding.recorded == "3000000.00"
        assert finding.suggested == "30000.00"

        # Nothing was persisted by the scan.
        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount is None

    def test_run_detectors_applies_the_repair(self):
        from core.services.data_quality import resolve_detectors, run_detectors, summarize

        decision = self._shifted_decision()
        runs = run_detectors(decision, resolve_detectors("decimal_shift"))
        result = summarize(runs)

        assert result["status"] == "corrected"
        assert result["written"] == 1
        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount == Decimal("30000.00")

    def test_dry_run_reports_would_correct_and_writes_nothing(self):
        from core.services.data_quality import resolve_detectors, run_detectors, summarize

        decision = self._shifted_decision()
        runs = run_detectors(
            decision, resolve_detectors("decimal_shift"), dry_run=True
        )
        result = summarize(runs)

        assert result["status"] == "would_correct"
        assert result["written"] == 0
        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount is None

    def test_consistent_decision_is_not_a_finding(self):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        DocumentExtractionFactory(decision=decision, raw_text="30.000,00")

        outcome = get_detector("decimal-shift").scan(decision)
        assert not outcome.detected

    def test_candidates_require_threshold_and_an_uncorrected_row(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.services.data_quality import get_detector

        detector = get_detector("decimal-shift")

        above = DecisionFactory()
        DecisionAmountFieldFactory(decision=above, amount=Decimal("500000.00"))
        below = DecisionFactory()
        DecisionAmountFieldFactory(decision=below, amount=Decimal("10.00"))
        flagged = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=flagged,
            amount=Decimal("500000.00"),
            invalid_amount_reason="afm_as_amount",
            invalid_amount_value="099370337",
        )

        ids = detector.candidate_ids(min_amount=Decimal("100000"))
        assert above.id in ids
        assert below.id not in ids
        assert flagged.id not in ids


# ---------------------------------------------------------------------------
# Non-monetary detector
# ---------------------------------------------------------------------------


class TestNonMonetaryValueDetector:
    def _afm_decision(self, amount="99370337.00"):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [{"sponsorAFMName": {"afm": "099370337"}}]
            }
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal(amount))
        return decision

    def test_scan_flags_without_suggesting_a_value(self):
        from core.services.data_quality import get_detector

        decision = self._afm_decision()
        outcome = get_detector("non-monetary-value").scan(decision)

        assert outcome.detected
        finding = outcome.findings[0]
        assert finding.kind == "afm"
        assert finding.reason == "afm_as_amount"
        # The real amount is unknown — a detector must never guess one.
        assert finding.suggested == ""
        assert finding.payload["matched_value"] == "099370337"

    def test_apply_writes_only_the_marker(self):
        from conftest import DecisionAmountFieldFactory
        from core.services.data_quality import get_detector

        decision = self._afm_decision()
        detector = get_detector("non-monetary-value")
        outcome = detector.scan(decision)
        written = detector.apply(decision, outcome)

        assert written == 1
        field = decision.amount_fields.get()
        field.refresh_from_db()
        assert field.verified_amount is None  # never a monetary guess
        assert field.invalid_amount_reason == "afm_as_amount"
        assert field.invalid_amount_value == "099370337"
        assert field.invalid_amount_flagged_at is not None

        # Idempotent: a second run rewrites the same marker.
        assert detector.apply(decision, detector.scan(decision)) == 1

    def test_run_detectors_summarizes_the_flag(self):
        from core.services.data_quality import resolve_detectors, run_detectors, summarize

        decision = self._afm_decision()
        result = summarize(
            run_detectors(decision, resolve_detectors("non_monetary"))
        )

        assert result["status"] == "afm_as_amount"
        assert result["written"] == 1
        assert result["flagged"][0]["detector"] == "non-monetary-value"
        assert result["corrections"] == []

    def test_already_flagged_rows_are_not_reselected(self):
        from core.services.data_quality import get_detector

        decision = self._afm_decision()
        detector = get_detector("non-monetary-value")
        assert decision.id in detector.candidate_ids()

        detector.apply(decision, detector.scan(decision))
        assert decision.id not in detector.candidate_ids()

    def test_small_amounts_are_out_of_bounds(self):
        from core.services.data_quality import get_detector

        decision = self._afm_decision(amount="1234.00")
        detector = get_detector("non-monetary-value")
        assert decision.id not in detector.candidate_ids()

    def test_self_counterpart_small_amount_is_still_a_candidate(self):
        """
        The self-counterpart structural signal bypasses the amount bounds: a
        well-formed €10 amount on a self-referencing decision must surface even
        though it is far below ``default_min_amount``.  This is what the
        ``OR entity.afm = organization.vat_number`` branch is for.
        """
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
            OrganizationFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="090064864")
        )
        entity = AFMEntityFactory(afm="090064864")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="person"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))

        detector = get_detector("non-monetary-value")
        assert decision.id in detector.candidate_ids()

    def test_non_self_counterpart_small_amount_is_not_a_candidate(self):
        """A small amount whose counterpart AFM ≠ org VAT stays out of bounds."""
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
            OrganizationFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="090064864")
        )
        other = AFMEntityFactory(afm="099999999")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=other, role="person"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))

        detector = get_detector("non-monetary-value")
        assert decision.id not in detector.candidate_ids()

    def test_truncated_org_vat_prefix_is_a_candidate(self):
        """
        The Παίδων case at the SQL level: an 8-digit org VAT whose prefix the
        9-digit counterpart AFM carries must surface via the candidate query's
        prefix branch, even below the amount bounds.
        """
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
            OrganizationFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="09000980")
        )
        entity = AFMEntityFactory(afm="090009802")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="person"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))

        detector = get_detector("non-monetary-value")
        assert decision.id in detector.candidate_ids()

    def test_short_junk_org_vat_is_not_a_candidate(self):
        """A junk short VAT (``011``) must not prefix-match via the SQL branch."""
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
            OrganizationFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="011")
        )
        entity = AFMEntityFactory(afm="011999999")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="person"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))

        detector = get_detector("non-monetary-value")
        assert decision.id not in detector.candidate_ids()

    def test_all_zeros_org_vat_is_not_a_candidate(self):
        """Placeholder VAT ``00000000`` must not match via either SQL branch."""
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
            OrganizationFactory,
        )
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="00000000")
        )
        entity = AFMEntityFactory(afm="000000001")
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="person"
        )
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))

        detector = get_detector("non-monetary-value")
        assert decision.id not in detector.candidate_ids()

    def test_self_counterpart_flags_every_amount_without_suggesting_a_value(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory, OrganizationFactory
        from core.services.data_quality import get_detector

        decision = DecisionFactory(
            organization=OrganizationFactory(vat_number="090064864"),
            extra_field_values_json={
                "sponsor": [{"sponsorAFMName": {"afm": "090064864"}}]
            },
        )
        first = DecisionAmountFieldFactory(decision=decision, amount=Decimal("10.00"))
        second = DecisionAmountFieldFactory(decision=decision, amount=Decimal("20.00"))

        detector = get_detector("non-monetary-value")
        outcome = detector.scan(decision)
        assert outcome.detected
        assert {finding.kind for finding in outcome.findings} == {"self_counterpart"}
        assert {finding.reason for finding in outcome.findings} == {"self_as_counterpart"}
        assert {finding.suggested for finding in outcome.findings} == {""}

        assert detector.apply(decision, outcome) == 2
        for field in (first, second):
            field.refresh_from_db()
            assert field.verified_amount is None
            assert field.invalid_amount_reason == "self_as_counterpart"
            assert field.invalid_amount_value == "090064864"


# ---------------------------------------------------------------------------
# "both" mode
# ---------------------------------------------------------------------------


class TestBothMode:
    def test_both_mode_reports_both_findings(self):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.services.data_quality import resolve_detectors, run_detectors, summarize

        decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [{"sponsorAFMName": {"afm": "099370337"}}]
            }
        )
        # AFM-as-amount row (flagged) plus a shifted row (repaired).
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("99370337.00"))
        DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[1].expenseAmount",
            amount=Decimal("3000000.00"),
        )
        DocumentExtractionFactory(decision=decision, raw_text="30.000,00")

        result = summarize(
            run_detectors(decision, resolve_detectors("both"))
        )

        # One repair beats the flag for the summary status…
        assert result["status"] == "corrected"
        assert len(result["corrections"]) == 1
        assert len(result["flagged"]) == 1
        assert {f["detector"] for f in result["flagged"]} == {"non-monetary-value"}

    def test_a_failing_detector_does_not_abort_the_others(self):
        from core.services.data_quality import BaseDetector, run_detectors, summarize

        class ExplodingDetector(BaseDetector):
            slug = "exploding"
            mode_key = "exploding"
            name = "Exploding"

            def candidate_ids(self, **kwargs):
                return []

            def scan(self, decision, **kwargs):
                raise RuntimeError("boom")

        from core.services.data_quality import STATUS_ERROR

        runs = run_detectors(object(), [ExplodingDetector()])
        assert runs[0].outcome.status == STATUS_ERROR
        assert summarize(runs)["status"] == "error"
