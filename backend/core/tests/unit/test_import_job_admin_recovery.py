"""Tests for the ImportJob admin recovery/stall actions."""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest
from admin_custom.admin_classes.analytics import ImportJobAdmin
from core.models.import_jobs import ImportFailure, ImportJob, ImportJobStatus
from django.contrib import admin
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _job(**kwargs):
    defaults = dict(
        start_date=date(2026, 11, 17),
        end_date=date(2026, 11, 17),
        status=ImportJobStatus.PROCESSING,
        total_chunks=2,
        chunks_completed=1,
    )
    defaults.update(kwargs)
    return ImportJob.objects.create(**defaults)


def _admin():
    return ImportJobAdmin(ImportJob, admin.site)


class TestStuckIndicator:
    def test_fresh_progress_is_not_stuck(self):
        job = _job()
        ImportJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(hours=5),
            last_progress_at=timezone.now(),
        )
        job.refresh_from_db()

        assert _admin().stuck_indicator(job) == "-"

    def test_old_progress_is_stuck(self):
        job = _job()
        ImportJob.objects.filter(pk=job.pk).update(
            last_progress_at=timezone.now() - timedelta(hours=3)
        )
        job.refresh_from_db()

        assert "STUCK" in _admin().stuck_indicator(job)


class TestRetryFailedChunks:
    def test_reads_chunk_id_from_data_snapshot(self):
        job = _job(
            total_chunks=1,
            chunks_completed=0,
            chunks_failed=1,
            chunk_task_ids=["task-1"],
        )
        chunk_id = f"{job.id}_chunk_0"
        ImportFailure.objects.create(
            import_job=job,
            task_id="task-1",
            failure_type=ImportFailure.FailureType.CHUNK,
            error_message="boom",
            data_snapshot={"chunk_id": chunk_id},
        )

        cache = Mock()
        cache.chunk_exists.return_value = True
        cache.get_chunk_state.return_value = None

        import_admin = _admin()
        import_admin.message_user = Mock()

        with (
            patch(
                "core.services.redis_decision_cache.RedisDecisionCache",
                return_value=cache,
            ),
            patch(
                "core.tasks.tasks_decisions_import.store_decisions_from_redis"
            ) as store_task,
        ):
            import_admin.retry_failed_chunks(
                Mock(), ImportJob.objects.filter(pk=job.pk)
            )

        store_task.delay.assert_called_once()
        assert store_task.delay.call_args.kwargs["chunk_id"] == chunk_id
        cache.clear_chunk_state.assert_called_once_with(job.id, 0)
