"""
Unit tests for the amount-correction batch job orchestration
(``core/tasks/tasks_amount_correction.py``).

Covers ``run_amount_correction_job`` candidate selection — in particular that
a row already flagged as a **non-monetary value** (``invalid_amount_reason``
set) is not treated as "uncorrected".  Such a row can never be corrected
automatically (its real amount is unknown), so re-selecting it would make the
job re-flag the same decisions on every run.

All Celery ``.delay()`` fan-out calls are mocked — no broker needed.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.django_db

THRESHOLD = Decimal("100000")


def _make_job(**kwargs):
    from core.models.amount_correction_job import AmountCorrectionJob

    return AmountCorrectionJob.objects.create(threshold=THRESHOLD, **kwargs)


def _run(job):
    from core.tasks.tasks_amount_correction import run_amount_correction_job

    with patch(
        "core.tasks.tasks_amount_correction.correct_single_decision.delay"
    ) as mock_delay:
        result = run_amount_correction_job.run(str(job.job_id))
    return result, mock_delay


class TestRunAmountCorrectionJobCandidateSelection:
    def test_uncorrected_decision_is_candidate(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("500000.00"))
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 1
        assert result["total"] == 1
        assert mock_delay.call_count == 1

    def test_flagged_only_decision_is_not_reselected(self):
        """The only amount row is flagged → nothing left to correct."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision,
            amount=Decimal("500000.00"),
            verified_amount=None,
            invalid_amount_reason="afm_as_amount",
            invalid_amount_value="099370337",
        )
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 0
        assert result == {"status": "completed", "total": 0}
        mock_delay.assert_not_called()

    def test_flagged_row_does_not_keep_corrected_decision_in_pool(self):
        """A corrected decision that also has a flagged row must not be
        re-selected purely because of the (never-correctable) flagged row."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            amount=Decimal("500000.00"),
            verified_amount=Decimal("500000.00"),
        )
        DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[1].expenseAmount",
            amount=Decimal("400000.00"),
            verified_amount=None,
            invalid_amount_reason="kae_as_amount",
            invalid_amount_value="706273001",
        )
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 0
        assert result["total"] == 0
        mock_delay.assert_not_called()

    def test_below_threshold_decision_is_not_candidate(self):
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        decision = DecisionFactory()
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("1000.00"))
        job = _make_job()

        result, mock_delay = _run(job)

        job.refresh_from_db()
        assert job.total_candidates == 0
        mock_delay.assert_not_called()


class TestBeatTaskNames:
    """Beat schedule strings must match the tasks' REGISTERED names.

    ``tasks_amount_correction`` declares explicit short names via
    ``@shared_task(name=...)``.  Referencing the module path in beat instead
    silently drops the job ("Received unregistered task of type …") — the task
    never runs and produces no logs.
    """

    def test_daily_amount_correction_has_no_beat_entry(self):
        """WI-3: correction runs after each import, not on a schedule."""
        from diavgeia_project.celery import app

        assert "daily-amount-correction" not in app.conf.beat_schedule
        assert "amount_correction.daily" not in {
            entry["task"] for entry in app.conf.beat_schedule.values()
        }

    def test_sweeper_beat_entry_matches_registered_name(self):
        from diavgeia_project.celery import app

        from core.tasks.tasks_amount_correction import (
            sweep_amount_correction_jobs,
        )

        entry = app.conf.beat_schedule["amount-correction-finalize-sweeper"]
        assert entry["task"] == sweep_amount_correction_jobs.name

    def test_all_active_beat_entries_resolve_to_registered_tasks(self):
        import importlib

        from diavgeia_project.celery import app

        def _import_defining_module(task_name: str) -> None:
            """Best-effort import of the module holding a dotted task name.

            Celery's autodiscovery is lazy, so a beat entry whose module has
            not been imported yet would look "unregistered" in a test process
            even though the worker has it.  Import the longest importable
            prefix so the check reflects reality.
            """
            parts = task_name.split(".")
            for cut in range(len(parts) - 1, 0, -1):
                try:
                    importlib.import_module(".".join(parts[:cut]))
                    return
                except ImportError:
                    continue

        for entry in app.conf.beat_schedule.values():
            _import_defining_module(entry["task"])
        app.finalize()

        missing = {
            entry["task"]
            for entry in app.conf.beat_schedule.values()
            if entry["task"] not in app.tasks
        }
        assert missing == set()


class TestFinalizerSweeper:
    """WI-4: beat finalises RUNNING jobs whose results are all settled."""

    def test_settled_job_is_completed_and_caches_invalidated(self):
        from core.models.amount_correction_job import CorrectionJobStatus
        from core.services.response_cache_service import response_cache
        from core.tasks.tasks_amount_correction import sweep_amount_correction_jobs

        job = _make_job(
            status=CorrectionJobStatus.RUNNING,
            total_candidates=2,
            processed_count=2,
            corrected=1,
        )

        with patch.object(
            response_cache, "invalidate_prefix"
        ) as mock_invalidate:
            result = sweep_amount_correction_jobs()

        job.refresh_from_db()
        assert job.status == CorrectionJobStatus.COMPLETED
        assert job.completed_at is not None
        assert result["finalized"] == 1
        mock_invalidate.assert_called_once_with("top_")

    def test_in_progress_job_stays_running(self):
        from core.models.amount_correction_job import CorrectionJobStatus
        from core.tasks.tasks_amount_correction import sweep_amount_correction_jobs

        job = _make_job(
            status=CorrectionJobStatus.RUNNING,
            total_candidates=2,
            processed_count=1,
        )

        result = sweep_amount_correction_jobs()

        job.refresh_from_db()
        assert job.status == CorrectionJobStatus.RUNNING
        assert result["finalized"] == 0

    def test_no_change_job_does_not_invalidate(self):
        from core.models.amount_correction_job import CorrectionJobStatus
        from core.services.response_cache_service import response_cache
        from core.tasks.tasks_amount_correction import sweep_amount_correction_jobs

        job = _make_job(
            status=CorrectionJobStatus.RUNNING,
            total_candidates=1,
            processed_count=1,
        )

        with patch.object(
            response_cache, "invalidate_prefix"
        ) as mock_invalidate:
            sweep_amount_correction_jobs()

        job.refresh_from_db()
        assert job.status == CorrectionJobStatus.COMPLETED
        mock_invalidate.assert_not_called()
