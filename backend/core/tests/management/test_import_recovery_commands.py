"""Tests for import recovery management commands.

These pin the two regressions that made the incident hard to diagnose:
commands must scan the producer's Redis namespace, and retry actions must
reopen/clear per-chunk state before redispatching.
"""

from datetime import date
from io import StringIO
from unittest.mock import MagicMock, Mock, patch

import pytest
from core.models.import_jobs import ImportJob, ImportJobStatus
from django.core.management import call_command


@pytest.mark.django_db
class TestRetryImportChunksCommand:
    def test_redispatches_recoverable_chunks(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=2,
            chunks_completed=0,
        )

        cache = MagicMock()
        cache.chunk_exists.return_value = True
        cache.get_chunk_state.return_value = None

        recovery = MagicMock()
        recovery.inspect_job.return_value = {
            "recoverable": [0, 1],
            "lost": [],
            "missing": 2,
            "accounted": {},
        }

        with (
            patch(
                "core.management.commands.retry_import_chunks.RedisDecisionCache",
                return_value=cache,
            ),
            patch(
                "core.management.commands.retry_import_chunks.ImportChunkRecoveryService",
                return_value=recovery,
            ),
            patch(
                "core.management.commands.retry_import_chunks.store_decisions_from_redis"
            ) as store_task,
        ):
            call_command(
                "retry_import_chunks",
                job.id,
                "--all-missing",
                stdout=StringIO(),
            )

        assert store_task.delay.call_count == 2
        chunk_ids = [
            call.kwargs["chunk_id"] for call in store_task.delay.call_args_list
        ]
        assert chunk_ids == [f"{job.id}_chunk_0", f"{job.id}_chunk_1"]
        cache.clear_chunk_state.assert_any_call(job.id, 0)
        cache.clear_chunk_state.assert_any_call(job.id, 1)


@pytest.mark.django_db
class TestImportQueueCommand:
    def test_set_limit_persists_for_other_processes(self):
        queue = MagicMock()
        queue.MAX_CONCURRENT_JOBS = 1
        queue.SETTINGS_KEY = "import_job_queue:settings"

        with patch(
            "core.management.commands.import_queue.ImportJobQueue",
            return_value=queue,
        ):
            call_command(
                "import_queue",
                "set-limit",
                "--limit",
                "3",
                stdout=StringIO(),
            )

        queue.set_max_concurrent_jobs.assert_called_once_with(3)


@pytest.mark.django_db
class TestDiagnoseImportJobCommand:
    def test_uses_producer_chunk_scan(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=2,
            chunks_completed=1,
        )

        cache = MagicMock()
        cache.list_job_chunk_ids.return_value = [f"{job.id}_chunk_1"]

        with patch(
            "core.management.commands.diagnose_import_job.RedisDecisionCache",
            return_value=cache,
        ):
            output = StringIO()
            call_command("diagnose_import_job", job.id, stdout=output)

        cache.list_job_chunk_ids.assert_called_once_with(job.id)
        assert "Chunks Remaining: 1" in output.getvalue()


@pytest.mark.django_db
class TestInspectRedisChunksCommand:
    def test_inspects_chunks_through_producer_helper(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=1,
        )

        cache = MagicMock()
        cache.list_job_chunk_ids.return_value = [f"{job.id}_chunk_0"]
        cache.get_chunk_ttl.return_value = 3600
        cache.redis_client.memory_usage.return_value = 1024

        with patch(
            "core.management.commands.inspect_redis_chunks.RedisDecisionCache",
            return_value=cache,
        ):
            output = StringIO()
            call_command(
                "inspect_redis_chunks",
                "2026-11-17",
                stdout=output,
            )

        cache.list_job_chunk_ids.assert_any_call(job.id)
        assert "Found 1 chunks in Redis" in output.getvalue()


@pytest.mark.django_db
class TestRedispatchRedisChunksCommand:
    def test_dispatches_recoverable_chunks(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=1,
        )

        recovery = MagicMock()
        recovery.inspect_job.return_value = {
            "recoverable": [0],
            "lost": [],
            "missing": 1,
            "accounted": {},
        }

        with (
            patch(
                "core.management.commands.redispatch_redis_chunks.RedisDecisionCache"
            ),
            patch(
                "core.management.commands.redispatch_redis_chunks.ImportChunkRecoveryService",
                return_value=recovery,
            ),
            patch(
                "core.tasks.tasks_decisions_import.store_decisions_from_redis.apply_async"
            ) as apply_async,
        ):
            call_command(
                "redispatch_redis_chunks",
                job.id,
                stdout=StringIO(),
            )

        apply_async.assert_called_once()
        args = apply_async.call_args.kwargs["args"]
        assert args == [f"{job.id}_chunk_0", job.id]
