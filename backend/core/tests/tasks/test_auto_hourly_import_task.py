"""
Task-level tests for ``auto_hourly_import_task`` (T09).

The task is the hourly heartbeat: gate on the flag, guard against
too-frequent triggers, then enqueue exactly one HOURLY job for today.
``ImportJobQueue`` and ``feature_flags`` are patched on the source module;
``SyncStatus`` is exercised for real against the database.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from core.constants.decision_import_constants import (
    HOURLY_IMPORT_MIN_INTERVAL_MINUTES,
    HOURLY_IMPORT_OVERLAP_MINUTES,
    HOURLY_IMPORT_SYNC_TYPE,
)
from core.models.import_jobs import ImportJobType
from core.models.sync_status import SyncStatus
from core.tasks.tasks_auto_import import auto_hourly_import_task
from django.utils import timezone

QUEUE = "core.tasks.tasks_auto_import.ImportJobQueue"
FLAGS = "core.tasks.tasks_auto_import.feature_flags"


def _seed_watermark(timestamp):
    return SyncStatus.objects.create(
        sync_type=HOURLY_IMPORT_SYNC_TYPE,
        last_sync_timestamp=timestamp,
        last_sync_date=timestamp.date(),
        last_run_status="completed",
    )


@pytest.mark.django_db
class TestAutoHourlyImportTask:
    def test_flag_disabled_skips(self):
        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = False

            result = auto_hourly_import_task()

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
        mock_queue.assert_not_called()

    def test_too_soon_skips(self):
        _seed_watermark(timezone.now() - timedelta(minutes=2))

        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = True

            result = auto_hourly_import_task()

        assert result == {"status": "skipped", "reason": "too_soon"}
        mock_queue.assert_not_called()

    def test_enqueues_hourly_job_for_today(self):
        watermark = timezone.now() - timedelta(minutes=70)
        _seed_watermark(watermark)
        mock_job = MagicMock(id=42, status="PENDING")

        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = True
            mock_queue.return_value.enqueue_job.return_value = mock_job

            result = auto_hourly_import_task()

        today = timezone.localdate()
        assert result == {
            "status": "success",
            "date": str(today),
            "job_id": 42,
            "job_status": "PENDING",
        }

        kwargs = mock_queue.return_value.enqueue_job.call_args.kwargs
        assert kwargs["target_date"] == today
        assert kwargs["import_type"] == ImportJobType.HOURLY
        assert kwargs["auto_dispatch"] is True
        assert kwargs["skip_duplicates"] is True
        assert kwargs["created_by"] is None
        assert kwargs["search_params"]["force"] is False

        expected_from = watermark - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )
        assert (
            kwargs["search_params"]["window_from_estimate"]
            == expected_from.isoformat()
        )

    def test_too_soon_boundary_uses_min_interval_constant(self):
        """A watermark exactly at the min-interval boundary is not skipped."""
        _seed_watermark(
            timezone.now() - timedelta(minutes=HOURLY_IMPORT_MIN_INTERVAL_MINUTES + 1)
        )
        mock_job = MagicMock(id=1, status="PENDING")

        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = True
            mock_queue.return_value.enqueue_job.return_value = mock_job

            result = auto_hourly_import_task()

        assert result["status"] == "success"
        mock_queue.return_value.enqueue_job.assert_called_once()

    def test_enqueue_error_returns_error_dict(self):
        _seed_watermark(timezone.now() - timedelta(minutes=70))

        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = True
            mock_queue.return_value.enqueue_job.side_effect = RuntimeError("boom")

            result = auto_hourly_import_task()

        assert result == {"status": "error", "error": "boom"}

    def test_second_call_dedupes_via_queue(self):
        """Dedupe is existing ImportJobQueue behavior driven by
        skip_duplicates=True — the task must always pass it."""
        _seed_watermark(timezone.now() - timedelta(minutes=70))
        mock_job = MagicMock(id=7, status="PENDING")

        with (
            patch(FLAGS) as mock_flags,
            patch(QUEUE) as mock_queue,
        ):
            mock_flags.is_enabled.return_value = True
            mock_queue.return_value.enqueue_job.return_value = mock_job

            auto_hourly_import_task()
            auto_hourly_import_task()

        assert mock_queue.return_value.enqueue_job.call_count == 2
        for call in mock_queue.return_value.enqueue_job.call_args_list:
            assert call.kwargs["skip_duplicates"] is True
