"""
Unit tests for the Diavgeia feedback batch job orchestration
(``core/tasks/tasks_diavgeia_feedback.py``).

Covers ``run_feedback_job`` candidate selection — in particular that a
decision flagged as a **non-monetary value** (``invalid_amount_reason`` set)
is a candidate even though it has no ``verified_amount``.  This mirrors
``DiavgeiaFeedbackService.pending_decisions()``; without it such decisions
would never reach the Diavgeia admins.

All Celery ``.delay()`` fan-out calls are mocked — no broker needed.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db


def _make_job(**kwargs):
    from core.models.diavgeia_feedback_job import DiavgeiaFeedbackJob

    return DiavgeiaFeedbackJob.objects.create(**kwargs)


def _run(job):
    from core.tasks.tasks_diavgeia_feedback import run_feedback_job

    with patch(
        "core.tasks.tasks_diavgeia_feedback.report_single_decision_feedback.delay"
    ) as mock_delay:
        result = run_feedback_job.run(str(job.job_id))
    return result, mock_delay


class TestRunFeedbackJobCandidateSelection:
    def test_corrected_decision_is_candidate(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision,
            amount=Decimal("30000.00"),
            verified_amount=Decimal("300.00"),
        )
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 1
        assert result["total"] == 1
        assert mock_delay.call_count == 1

    def test_flagged_decision_is_candidate(self):
        """A flagged (non-monetary) decision has no verified_amount but must
        still reach the feedback pool so Diavgeia can fix it at the source."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision,
            amount=Decimal("99370337.00"),
            verified_amount=None,
            invalid_amount_reason="afm_as_amount",
            invalid_amount_value="099370337",
        )
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 1
        assert result["total"] == 1
        assert mock_delay.call_count == 1

    def test_clean_decision_is_not_candidate(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("30000.00"))
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 0
        assert result == {"status": "completed", "total": 0}
        mock_delay.assert_not_called()

    def test_already_reported_decision_is_excluded(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision,
            amount=Decimal("99370337.00"),
            invalid_amount_reason="afm_as_amount",
            invalid_amount_value="099370337",
        )
        DiavgeiaFeedbackReport.objects.create(decision=decision, reported=True)
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 0
        assert result["total"] == 0
        mock_delay.assert_not_called()

    def test_limit_is_honoured(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        for _ in range(3):
            d = DecisionFactory()
            DecisionAmountFieldFactory(
                decision=d, amount=Decimal("30000.00"),
                verified_amount=Decimal("300.00"),
            )
        job = _make_job(limit=2)

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 2
        assert result["total"] == 2
        assert mock_delay.call_count == 2
