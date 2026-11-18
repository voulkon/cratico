"""Tests for import-chunk recovery and the watchdog.

Covers:
- redispatch of surviving payloads,
- per-tick redispatch cap,
- reconciliation from recorded chunk outcomes,
- abandonment when payloads are gone,
- legacy counter-gap handling and counter clamping,
- stalled chunk/fetch job selection.
"""

from datetime import date, timedelta
from unittest.mock import Mock, patch

import pytest
from api.redis_keys import IMPORT_CHUNK_PREFIX
from core.models.import_jobs import ImportJob, ImportJobStatus, ImportJobType
from core.services.import_chunk_recovery import ImportChunkRecoveryService
from core.tasks.tasks_auto_import import recover_stalled_import_jobs_task
from django.utils import timezone

from ._chunk_test_helpers import FakeRedis, make_cache


@pytest.mark.django_db
class TestImportChunkRecoveryService:
    def _job(self, **kwargs):
        defaults = dict(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            import_type=ImportJobType.HOURLY,
            total_chunks=2,
            chunks_completed=1,
            last_progress_at=timezone.now() - timedelta(minutes=30),
        )
        defaults.update(kwargs)
        return ImportJob.objects.create(**defaults)

    def test_redispatches_surviving_chunks(self):
        job = self._job()
        fake = FakeRedis(
            keys=[f"{IMPORT_CHUNK_PREFIX}{job.id}_chunk_1"],
            states={f"import:chunk_state:{job.id}": {"0": "completed"}},
        )
        service = ImportChunkRecoveryService(cache=make_cache(fake))

        with patch(
            "core.tasks.tasks_decisions_import.store_decisions_from_redis"
        ) as task:
            result = service.recover_job(job)

        assert result["status"] == "redispatched"
        assert result["dispatched"] == [f"{job.id}_chunk_1"]
        task.delay.assert_called_once()
        job.refresh_from_db()
        assert job.last_progress_at is not None

    def test_redispatch_is_capped_per_tick(self):
        job = self._job(total_chunks=200, chunks_completed=100)
        fake = FakeRedis(
            keys=[
                f"{IMPORT_CHUNK_PREFIX}{job.id}_chunk_{index}"
                for index in range(200)
            ],
        )
        service = ImportChunkRecoveryService(cache=make_cache(fake))

        with patch(
            "core.tasks.tasks_decisions_import.store_decisions_from_redis"
        ) as task:
            result = service.recover_job(job)

        assert result["status"] == "redispatched"
        assert len(result["dispatched"]) == 50
        assert result["remaining"] == 50
        assert task.delay.call_count == 50

    def test_reconciles_counters_from_chunk_state(self):
        job = self._job(chunks_completed=0)
        fake = FakeRedis(
            keys=[],
            states={
                f"import:chunk_state:{job.id}": {
                    "0": "completed",
                    "1": "completed",
                }
            },
        )
        service = ImportChunkRecoveryService(cache=make_cache(fake))

        with patch(
            "core.services.import_job_queue.ImportJobQueue.on_job_completed"
        ) as on_completed:
            result = service.recover_job(job)

        assert result["status"] == "reconciled"
        job.refresh_from_db()
        assert job.status == ImportJobStatus.COMPLETED
        assert job.chunks_completed == 2
        on_completed.assert_called_once_with(job.id)

    def test_abandons_job_when_payload_is_gone(self):
        job = self._job()
        fake = FakeRedis(
            keys=[],
            states={f"import:chunk_state:{job.id}": {"0": "completed"}},
        )
        service = ImportChunkRecoveryService(cache=make_cache(fake))

        with patch(
            "core.services.import_job_queue.ImportJobQueue.on_job_completed"
        ) as on_completed:
            result = service.recover_job(job)

        assert result["status"] == "abandoned"
        assert result["terminal_status"] == ImportJobStatus.PARTIALLY_COMPLETED
        job.refresh_from_db()
        assert job.status == ImportJobStatus.PARTIALLY_COMPLETED
        assert "no recoverable payload" in job.error_details
        on_completed.assert_called_once_with(job.id)

    def test_legacy_job_accounts_only_for_the_counter_gap(self):
        """Jobs predating the chunk-state hash (empty hash) must lose exactly
        the unreported chunks, not every chunk."""
        job = self._job(
            total_chunks=80,
            chunks_completed=66,
            chunks_failed=0,
        )
        fake = FakeRedis(keys=[], states={})
        service = ImportChunkRecoveryService(cache=make_cache(fake))

        with patch(
            "core.services.import_job_queue.ImportJobQueue.on_job_completed"
        ):
            result = service.recover_job(job)

        assert result["status"] == "abandoned"
        assert len(result["lost"]) == 14
        job.refresh_from_db()
        assert job.chunks_completed == 66
        assert job.chunks_failed == 14
        assert job.status == ImportJobStatus.PARTIALLY_COMPLETED

    def test_counter_reconciliation_is_clamped_to_total(self):
        """Recorded outcomes from both sides of a deploy must not exceed total."""
        job = self._job(
            total_chunks=80,
            chunks_completed=66,
            chunks_failed=20,
        )
        with patch(
            "core.services.import_job_queue.ImportJobQueue.on_job_completed"
        ):
            job.reconcile_chunk_counters(completed=80, failed=20)
        job.refresh_from_db()

        assert job.chunks_completed == 80
        assert job.chunks_failed == 0
        assert job.chunks_completed + job.chunks_failed == 80


@pytest.mark.django_db
class TestRecoverStalledImportJobsTask:
    def test_examines_only_stalled_incomplete_jobs(self):
        stale = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=2,
            chunks_completed=1,
            last_progress_at=timezone.now() - timedelta(minutes=30),
        )
        # Fresh progress -> not stalled.
        ImportJob.objects.create(
            start_date=date(2026, 11, 18),
            end_date=date(2026, 11, 18),
            status=ImportJobStatus.PROCESSING,
            total_chunks=2,
            chunks_completed=1,
            last_progress_at=timezone.now(),
        )
        # Complete -> not selected.
        ImportJob.objects.create(
            start_date=date(2026, 11, 16),
            end_date=date(2026, 11, 16),
            status=ImportJobStatus.PROCESSING,
            total_chunks=1,
            chunks_completed=1,
            last_progress_at=timezone.now() - timedelta(hours=2),
        )

        service = Mock()
        service.recover_job.return_value = {"status": "redispatched"}

        with patch(
            "core.services.import_chunk_recovery.ImportChunkRecoveryService",
            return_value=service,
        ):
            result = recover_stalled_import_jobs_task()

        assert result["examined"] == 1
        service.recover_job.assert_called_once()
        assert service.recover_job.call_args.args[0].id == stale.id

    def test_redispatches_stalled_fetch_job(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.FETCHING,
            import_type=ImportJobType.DAILY,
            total_chunks=0,
        )
        old = timezone.now() - timedelta(minutes=100)
        ImportJob.objects.filter(pk=job.id).update(created_at=old)

        service = Mock()
        with (
            patch(
                "core.services.import_chunk_recovery.ImportChunkRecoveryService",
                return_value=service,
            ),
            patch(
                "core.tasks.tasks_decisions_import.fetch_daily_decisions_distributed"
            ) as fetch_task,
        ):
            fetch_task.delay.return_value = Mock(id="fetch-task-id")
            result = recover_stalled_import_jobs_task()

        assert result["fetch_results"][0]["status"] == "redispatched"
        fetch_task.delay.assert_called_once()
        job.refresh_from_db()
        assert job.celery_task_id == "fetch-task-id"

    def test_abandons_fetch_job_after_longer_threshold(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.FETCHING,
            import_type=ImportJobType.DAILY,
            total_chunks=0,
        )
        old = timezone.now() - timedelta(hours=7)
        ImportJob.objects.filter(pk=job.id).update(created_at=old)

        service = Mock()
        with (
            patch(
                "core.services.import_chunk_recovery.ImportChunkRecoveryService",
                return_value=service,
            ),
            patch(
                "core.services.import_job_queue.ImportJobQueue.on_job_completed"
            ),
        ):
            result = recover_stalled_import_jobs_task()

        assert result["fetch_results"][0]["status"] == "abandoned"
        job.refresh_from_db()
        assert job.status == ImportJobStatus.FAILED
