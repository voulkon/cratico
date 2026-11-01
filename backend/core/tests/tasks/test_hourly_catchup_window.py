"""
Hourly catch-up window cap (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §5.9 / WI-5).

The hourly window is recomputed from the live watermark at execution time.  A
long outage used to make the next job span the entire gap, blocking the shared
import queue (MAX_CONCURRENT_JOBS=1) behind one huge fetch.  The window is now
capped at ``HOURLY_IMPORT_MAX_WINDOW_HOURS`` and the watermark advances only to
the capped end, so later runs catch up in bounded steps.

The fetch service is mocked — no API, broker, or Redis is involved.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from core.constants.decision_import_constants import (
    HOURLY_IMPORT_MAX_WINDOW_HOURS,
    HOURLY_IMPORT_OVERLAP_MINUTES,
    HOURLY_IMPORT_SYNC_TYPE,
)
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.models.sync_status import SyncStatus
from core.tasks.tasks_decisions_import import fetch_hourly_decisions_to_redis
from django.utils import timezone
from freezegun import freeze_time

pytestmark = pytest.mark.django_db

FETCH_SERVICE = (
    "core.services.decision_fetch_reconcile_service."
    "DecisionFetchReconcileService"
)
QUEUE_COMPLETED = "core.services.import_job_queue.ImportJobQueue.on_job_completed"


def _make_job():
    today = timezone.localdate()
    return ImportJob.objects.create(
        start_date=today,
        end_date=today,
        status=ImportJobStatus.PENDING,
    )


def _seed_watermark(timestamp):
    return SyncStatus.objects.create(
        sync_type=HOURLY_IMPORT_SYNC_TYPE,
        last_sync_timestamp=timestamp,
        last_sync_date=timestamp.date(),
        last_run_status="completed",
    )


def _run_task(job):
    """Run the fetch task synchronously with an empty (successful) window."""
    service = MagicMock()
    service.fetch_decisions_for_window.return_value = ([], 0, 0)
    service.reconcile_window.return_value = {}

    with (
        patch(FETCH_SERVICE, return_value=service),
        patch(QUEUE_COMPLETED, return_value=None),
    ):
        return fetch_hourly_decisions_to_redis.run(job.id)


@freeze_time("2026-05-30 12:00:00")
class TestHourlyCatchupWindow:
    def test_no_watermark_starts_one_hour_back(self):
        job = _make_job()
        now = timezone.now()

        result = _run_task(job)

        assert result["status"] == "success"
        expected_from = now - timedelta(hours=1) - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )
        assert datetime.fromisoformat(result["window_from"]) == expected_from
        assert datetime.fromisoformat(result["window_to"]) == now

    def test_recent_watermark_uses_overlap_then_now(self):
        now = timezone.now()
        watermark = now - timedelta(minutes=30)
        _seed_watermark(watermark)
        job = _make_job()

        result = _run_task(job)

        expected_from = watermark - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )
        assert datetime.fromisoformat(result["window_from"]) == expected_from
        assert datetime.fromisoformat(result["window_to"]) == now

        watermark_row = SyncStatus.objects.get(sync_type=HOURLY_IMPORT_SYNC_TYPE)
        assert watermark_row.last_sync_timestamp == now

    def test_old_watermark_is_capped_and_watermark_advances_in_steps(self):
        now = timezone.now()
        # A 48-hour outage.
        _seed_watermark(now - timedelta(hours=48))
        job = _make_job()

        result = _run_task(job)

        window_from = datetime.fromisoformat(result["window_from"])
        window_to = datetime.fromisoformat(result["window_to"])
        expected_from = now - timedelta(hours=48) - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )
        assert window_from == expected_from
        assert window_to - window_from == timedelta(
            hours=HOURLY_IMPORT_MAX_WINDOW_HOURS
        )
        # The watermark advanced only to the capped end, not to "now".
        watermark_row = SyncStatus.objects.get(sync_type=HOURLY_IMPORT_SYNC_TYPE)
        assert watermark_row.last_sync_timestamp == window_to
        assert watermark_row.last_sync_timestamp < now

        # The next run resumes from the capped end and takes another bounded
        # step; the gap closes over a few runs instead of one unbounded job.
        next_job = _make_job()
        second = _run_task(next_job)
        second_from = datetime.fromisoformat(second["window_from"])
        second_to = datetime.fromisoformat(second["window_to"])
        assert second_from == window_to - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )
        assert second_to - second_from == timedelta(
            hours=HOURLY_IMPORT_MAX_WINDOW_HOURS
        )

        third_job = _make_job()
        third = _run_task(third_job)
        assert datetime.fromisoformat(third["window_to"]) == now

    def test_failed_fetch_does_not_advance_the_watermark(self):
        now = timezone.now()
        old_watermark = now - timedelta(hours=3)
        _seed_watermark(old_watermark)
        job = _make_job()

        service = MagicMock()
        service.fetch_decisions_for_window.side_effect = RuntimeError("api down")

        with (
            patch(FETCH_SERVICE, return_value=service),
            # Running via ``.run`` has no Celery request id; the failure row's
            # task_id is not what this test is about.
            patch(
                "core.tasks.tasks_decisions_import.ImportFailure.objects.create"
            ),
        ):
            with pytest.raises((Retry, RuntimeError)):
                fetch_hourly_decisions_to_redis.run(job.id)

        watermark_row = SyncStatus.objects.get(sync_type=HOURLY_IMPORT_SYNC_TYPE)
        assert watermark_row.last_sync_timestamp == old_watermark

        job.refresh_from_db()
        assert job.status == ImportJobStatus.FAILED
