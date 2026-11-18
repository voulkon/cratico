"""Tests for chunk durability, idempotency and at-least-once task options.

Covers:
- at-least-once task options (acks_late / reject_on_worker_lost),
- payload consumption only after successful work,
- idempotent per-chunk accounting,
- producer-consistent Redis key patterns.
"""

import json
from datetime import date
from unittest.mock import patch

import pytest
from api.redis_keys import (
    IMPORT_CHUNK_PREFIX,
    get_import_chunk_key,
    get_import_chunk_scan_pattern,
)
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.redis_decision_cache import parse_chunk_index
from core.tasks.tasks_decisions_import import (
    fetch_daily_decisions_distributed,
    fetch_daily_decisions_to_redis,
    fetch_hourly_decisions_to_redis,
    store_decisions_from_redis,
)
from core.tasks.tasks_documents import run_decision_pipeline_task

from ._chunk_test_helpers import FakeRedis, make_cache


class TestAtLeastOnceTaskOptions:
    @pytest.mark.parametrize(
        "task",
        [
            store_decisions_from_redis,
            fetch_daily_decisions_to_redis,
            fetch_hourly_decisions_to_redis,
            fetch_daily_decisions_distributed,
            run_decision_pipeline_task,
        ],
    )
    def test_task_declares_at_least_once(self, task):
        assert task.acks_late is True
        assert task.reject_on_worker_lost is True


class TestChunkAccounting:
    def test_parse_chunk_index(self):
        assert parse_chunk_index("2839_chunk_14") == 14
        assert parse_chunk_index("not-a-chunk") is None

    def test_get_chunk_does_not_delete_by_default(self):
        chunk_id = "1_chunk_0"
        fake = FakeRedis(
            values={
                get_import_chunk_key(chunk_id): json.dumps(
                    {"decisions": [], "metadata": {}, "decision_count": 0}
                )
            }
        )
        cache = make_cache(fake)

        result = cache.get_chunk(chunk_id)

        assert result["decisions"] == []
        assert fake.deleted == []

    def test_mark_chunk_state_is_idempotent(self):
        fake = FakeRedis()
        cache = make_cache(fake)

        assert cache.mark_chunk_state(1, 0, "completed") is True
        assert cache.mark_chunk_state(1, 0, "completed") is False
        assert cache.get_chunk_state(1, 0) == "completed"

    def test_list_job_chunk_ids_uses_producer_pattern(self):
        fake = FakeRedis(
            keys=[
                f"{IMPORT_CHUNK_PREFIX}5_chunk_2",
                f"{IMPORT_CHUNK_PREFIX}5_chunk_0",
                f"{IMPORT_CHUNK_PREFIX}6_chunk_0",
            ]
        )
        cache = make_cache(fake)

        chunk_ids = cache.list_job_chunk_ids(5)

        assert chunk_ids == ["5_chunk_0", "5_chunk_2"]
        assert fake.last_match == get_import_chunk_scan_pattern(5)
        assert fake.last_match == f"{get_import_chunk_key('5_chunk_')}*"

    @pytest.mark.django_db
    def test_store_task_deletes_payload_after_work_and_counts_once(self):
        job = ImportJob.objects.create(
            start_date=date(2026, 11, 17),
            end_date=date(2026, 11, 17),
            status=ImportJobStatus.PROCESSING,
            total_chunks=1,
        )
        chunk_id = f"{job.id}_chunk_0"
        fake = FakeRedis(
            values={
                get_import_chunk_key(chunk_id): json.dumps(
                    {
                        "decisions": [],
                        "metadata": {"chunk_index": 0, "job_id": job.id},
                        "decision_count": 0,
                    }
                )
            }
        )
        cache = make_cache(fake)

        with (
            patch(
                "core.tasks.tasks_decisions_import.RedisDecisionCache",
                return_value=cache,
            ),
            patch("core.tasks.tasks_decisions_import._log_import_progress"),
            patch(
                "core.services.pipeline_orchestrator.DecisionPipelineOrchestrator"
            ),
            patch(
                "core.services.import_job_queue.ImportJobQueue.on_job_completed"
            ),
        ):
            first = store_decisions_from_redis(chunk_id=chunk_id, job_id=job.id)
            job.refresh_from_db()
            assert job.chunks_completed == 1
            assert fake.deleted == [get_import_chunk_key(chunk_id)]

            # Redelivery: the payload is gone but the chunk is accounted for.
            second = store_decisions_from_redis(chunk_id=chunk_id, job_id=job.id)
            job.refresh_from_db()

        assert first["status"] == "success"
        assert second["reason"] == "duplicate_delivery"
        assert job.chunks_completed == 1
