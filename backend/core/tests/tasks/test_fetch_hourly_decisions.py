"""
Task-Level Tests for ``fetch_hourly_decisions_to_redis`` (T06).

Verifies the hourly fetch task:
1. Recomputes the window at execution time from the live watermark.
2. Advances the watermark only after Redis storage + dispatch succeeds.
3. Treats zero-decision windows as a first-class success.
4. Records structured FETCH failures and never advances on error.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry
from core.constants.decision_import_constants import (
    HOURLY_IMPORT_OVERLAP_MINUTES,
    HOURLY_IMPORT_SYNC_TYPE,
)
from core.models.import_jobs import ImportFailure, ImportJobStatus
from core.models.sync_status import SyncStatus
from core.tasks.tasks_decisions_import import fetch_hourly_decisions_to_redis
from diavgeia_api.models.decisions import Decision, DecisionStatus
from django.utils import timezone

SERVICE = "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
REDIS = "core.tasks.tasks_decisions_import.RedisDecisionCache"
STORE_TASK = "core.tasks.tasks_decisions_import.store_decisions_from_redis"
QUEUE = "core.services.import_job_queue.ImportJobQueue"


def _make_decisions(count: int):
    return [
        Decision(
            ada=f"HOURLY{i:04d}ADA",
            subject=f"Hourly Decision {i}",
            decisionTypeId="Β.1.1",
            organizationId="99999999",
            unitIds=["1111111"],
            signerIds=["SIGNER001"],
            issueDate=datetime(2026, 10, 6, 10, 0, 0),
            submissionTimestamp=datetime(2026, 10, 6, 10, 0, 0),
            versionId=f"v{i}",
            thematicCategoryIds=[],
            privateData=False,
            status=DecisionStatus.PUBLISHED,
        )
        for i in range(1, count + 1)
    ]


RECONCILIATION = {
    "window_from": "2026-10-06T09:00:00+00:00",
    "window_to": "2026-10-06T10:00:00+00:00",
    "official_count": None,
    "api_reported_total": 1,
    "our_count": 1,
    "our_vs_api_diff": 0,
    "types_filtered": False,
    "status": "window_match",
}


def _seed_watermark(timestamp, processed=0):
    return SyncStatus.objects.create(
        sync_type=HOURLY_IMPORT_SYNC_TYPE,
        last_sync_timestamp=timestamp,
        last_sync_date=timestamp.date(),
        total_processed=processed,
        last_run_status="completed",
    )


@contextmanager
def _direct_request(task_id="test-task-id", retries=0):
    """Provide a task request context so ``self.request.id`` is populated.

    Calling ``.run()`` directly otherwise leaves ``request.id`` as None, which
    cannot be stored in the non-null ``ImportFailure.task_id`` column.
    """
    task = fetch_hourly_decisions_to_redis
    task.push_request(id=task_id, retries=retries, called_directly=True)
    try:
        yield
    finally:
        task.pop_request()


@pytest.mark.django_db(transaction=True)
class TestFetchHourlyDecisions:
    @pytest.fixture
    def import_job(self):
        from conftest import ImportJobFactory

        return ImportJobFactory(
            status=ImportJobStatus.PENDING,
            search_params={"window_from_estimate": "2000-01-01T00:00:00+00:00"},
        )

    def test_window_recomputed_from_watermark_at_execution(self, import_job):
        """The window is watermark − overlap → now, never the enqueue estimate."""
        watermark = timezone.now() - timedelta(minutes=70)
        _seed_watermark(watermark)

        with patch(SERVICE) as MockService, patch(REDIS):
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.return_value = (
                _make_decisions(1),
                1,
                False,
            )
            mock_service.reconcile_window.return_value = dict(RECONCILIATION)

            before = timezone.now()
            fetch_hourly_decisions_to_redis.run(job_id=import_job.id)
            after = timezone.now()

        from_dt, to_dt = mock_service.fetch_decisions_for_window.call_args.args[:2]
        expected_from = watermark - timedelta(minutes=HOURLY_IMPORT_OVERLAP_MINUTES)
        assert abs((from_dt - expected_from).total_seconds()) < 5
        assert before <= to_dt <= after + timedelta(seconds=5)

        # The stale estimate was never used as the window start.
        assert from_dt.year != 2000
        import_job.refresh_from_db()
        assert import_job.search_params["window_from"] == from_dt.isoformat()

    def test_watermark_advanced_on_success(self, import_job):
        watermark = timezone.now() - timedelta(hours=1)
        _seed_watermark(watermark, processed=5)

        with patch(SERVICE) as MockService, patch(REDIS), patch(STORE_TASK) as store:
            mock_service = MockService.return_value
            decisions = _make_decisions(1)
            mock_service.fetch_decisions_for_window.return_value = (decisions, 1, False)
            mock_service.reconcile_window.return_value = dict(RECONCILIATION)
            store.apply_async.side_effect = [MagicMock(id="store-1")]

            fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

        to_dt = mock_service.reconcile_window.call_args.args[1]
        assert SyncStatus.get_last_hourly_sync() == to_dt
        row = SyncStatus.objects.get(sync_type=HOURLY_IMPORT_SYNC_TYPE)
        assert row.total_processed == 6

    def test_watermark_not_advanced_on_failure(self, import_job):
        watermark = timezone.now() - timedelta(hours=2)
        _seed_watermark(watermark, processed=3)

        with patch(SERVICE) as MockService, patch(REDIS):
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.side_effect = RuntimeError(
                "api down"
            )

            with _direct_request(), pytest.raises((RuntimeError, Retry)):
                fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

        assert SyncStatus.get_last_hourly_sync() == watermark
        import_job.refresh_from_db()
        assert import_job.status == ImportJobStatus.FAILED

    def test_zero_decisions_completes_and_notifies_queue(self, import_job):
        watermark = timezone.now() - timedelta(hours=1)
        _seed_watermark(watermark)

        with (
            patch(SERVICE) as MockService,
            patch(REDIS) as MockRedis,
            patch(STORE_TASK) as store,
            patch(QUEUE) as MockQueue,
        ):
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.return_value = ([], 0, False)
            mock_service.reconcile_window.return_value = dict(
                RECONCILIATION, our_count=0
            )

            result = fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

            MockRedis.return_value.store_chunk.assert_not_called()
            store.apply_async.assert_not_called()
            MockQueue.return_value.on_job_completed.assert_called_once_with(
                import_job.id
            )

        assert result["status"] == "success"
        assert result["decisions_count"] == 0
        import_job.refresh_from_db()
        assert import_job.status == ImportJobStatus.COMPLETED
        assert import_job.completed_at is not None
        assert SyncStatus.get_last_hourly_sync() > watermark

    def test_chunks_stored_and_storage_tasks_dispatched(self, import_job):
        watermark = timezone.now() - timedelta(hours=1)
        _seed_watermark(watermark)

        decisions = _make_decisions(25)
        with (
            patch(SERVICE) as MockService,
            patch(REDIS) as MockRedis,
            patch(STORE_TASK) as store,
        ):
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.return_value = (
                decisions,
                25,
                False,
            )
            mock_service.reconcile_window.return_value = dict(RECONCILIATION)
            store.apply_async.side_effect = [
                MagicMock(id=f"store-{i}") for i in range(1, 4)
            ]

            fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

            mock_redis = MockRedis.return_value
            assert mock_redis.store_chunk.call_count == 3
            for call in mock_redis.store_chunk.call_args_list:
                metadata = call.kwargs["metadata"]
                assert metadata["job_id"] == import_job.id
                assert "search_params" in metadata
                assert metadata["search_params"]["window_from"]

            assert store.apply_async.call_count == 3

        import_job.refresh_from_db()
        assert import_job.status == ImportJobStatus.PROCESSING
        assert import_job.total_chunks == 3
        assert import_job.total_decisions == 25
        assert import_job.chunk_task_ids == ["store-1", "store-2", "store-3"]

    def test_fetch_started_at_and_window_persisted(self, import_job):
        watermark = timezone.now() - timedelta(hours=1)
        _seed_watermark(watermark)

        with patch(SERVICE) as MockService, patch(REDIS), patch(STORE_TASK) as store:
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.return_value = (
                _make_decisions(1),
                1,
                False,
            )
            mock_service.reconcile_window.return_value = dict(RECONCILIATION)
            store.apply_async.side_effect = [MagicMock(id="store-1")]

            fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

        import_job.refresh_from_db()
        params = import_job.search_params
        assert set(["fetch_started_at", "window_from", "window_to"]).issubset(params)
        assert params["fetch_started_at"]
        assert params["window_from"]
        assert params["window_to"]

    def test_import_failure_recorded_on_fetch_error(self, import_job):
        _seed_watermark(timezone.now() - timedelta(hours=1))

        with patch(SERVICE) as MockService, patch(REDIS):
            mock_service = MockService.return_value
            mock_service.fetch_decisions_for_window.side_effect = RuntimeError("boom")

            with _direct_request(), pytest.raises((RuntimeError, Retry)):
                fetch_hourly_decisions_to_redis.run(job_id=import_job.id)

        failure = ImportFailure.objects.get(import_job=import_job)
        assert failure.failure_type == ImportFailure.FailureType.FETCH
        assert "window_from" in failure.data_snapshot
        assert "window_to" in failure.data_snapshot
