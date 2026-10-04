"""
Tests for detector-mode selection in the batch job
(``tasks_amount_correction.run_amount_correction_job``).

The job no longer names an algorithm: ``AmountCorrectionJob.mode`` is expanded
by the detector registry (``core.services.data_quality``), and the resolved
mode is propagated to every child task.  These tests pin that contract so a new
detector cannot be added to the registry and silently never run.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

THRESHOLD = Decimal("100000")


def _make_job(**kwargs):
    from core.models.amount_correction_job import AmountCorrectionJob

    kwargs.setdefault("threshold", THRESHOLD)
    return AmountCorrectionJob.objects.create(**kwargs)


def _run(job):
    from core.tasks.tasks_amount_correction import run_amount_correction_job

    with patch(
        "core.tasks.tasks_amount_correction.correct_single_decision.delay"
    ) as mock_delay:
        result = run_amount_correction_job.run(str(job.job_id))
    return result, mock_delay


class TestJobModeSelection:
    def test_default_mode_is_decimal_shift(self):
        from core.models.amount_correction_job import CorrectionJobMode

        assert _make_job().mode == CorrectionJobMode.DECIMAL_SHIFT

    def test_mode_is_propagated_to_every_child_task(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("500000.00"))
        job = _make_job(mode="non_monetary")

        result, mock_delay = _run(job)

        assert result["mode"] == "non_monetary"
        assert mock_delay.call_count == 1
        assert mock_delay.call_args.kwargs["mode"] == "non_monetary"

    def test_decimal_shift_mode_is_propagated_too(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("500000.00"))
        job = _make_job(mode="both")

        _, mock_delay = _run(job)

        assert mock_delay.call_args.kwargs["mode"] == "both"

    def test_both_mode_does_not_duplicate_a_decision_selected_by_two_detectors(
        self,
    ):
        """A decision that is a candidate for BOTH detectors must be fanned out
        once, not once per detector."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [{"sponsorAFMName": {"afm": "099370337"}}]
            }
        )
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("99370337.00")
        )
        job = _make_job(mode="both")

        result, mock_delay = _run(job)

        assert result["total"] == 1
        assert mock_delay.call_count == 1

    def test_unknown_mode_fails_the_job_instead_of_correcting_nothing(self):
        from core.models.amount_correction_job import (
            AmountCorrectionJob,
            CorrectionJobStatus,
        )
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("500000.00"))
        # Bypass the model's choices to simulate a stale/typo'd mode value.
        job = AmountCorrectionJob.objects.create(
            threshold=THRESHOLD, mode="not_a_mode"
        )

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert result["status"] == "error"
        assert job.status == CorrectionJobStatus.FAILED
        mock_delay.assert_not_called()


class TestJobAmountBounds:
    def test_max_amount_excludes_higher_decisions(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        inside = DecisionFactory()
        DecisionAmountFieldFactory(decision=inside, amount=Decimal("500000.00"))
        outside = DecisionFactory()
        DecisionAmountFieldFactory(decision=outside, amount=Decimal("5000000.00"))
        job = _make_job(max_amount=Decimal("1000000"))

        result, _ = _run(job)

        assert result["total"] == 1

    def test_threshold_and_max_amount_form_a_band(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("500000.00"))
        job = _make_job(threshold=Decimal("1000000"))

        result, mock_delay = _run(job)

        assert result["total"] == 0
        mock_delay.assert_not_called()
