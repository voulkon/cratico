"""
Tests for ImportJobQueue - Redis-based job queue for import concurrency control

These tests verify:
1. Concurrency control (max concurrent jobs respected)
2. FIFO queue ordering
3. Auto-dispatch behavior
4. Job completion triggers next dispatch
5. Stale job cleanup
6. Redis integration (mocked for unit tests)

Note: Redis is mocked to avoid CI dependencies. These are unit tests, not integration tests.
"""

from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue
from django.utils import timezone
from freezegun import freeze_time

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_redis():
    """Mock Redis connection to avoid dependency on actual Redis instance"""
    mock_redis_client = MagicMock()
    # Mock basic Redis operations
    mock_redis_client.set = MagicMock(return_value=True)
    mock_redis_client.get = MagicMock(return_value=b"test_value")
    mock_redis_client.delete = MagicMock(return_value=1)
    # Mock connection pool for assertions
    mock_redis_client.connection_pool = MagicMock()
    mock_redis_client.connection_pool.connection_kwargs = {"db": 2}

    with patch(
        "core.services.import_job_queue.get_redis_connection",
        return_value=mock_redis_client,
    ):
        yield mock_redis_client


@pytest.fixture
def clear_import_queue():
    """
    Clear all ImportJobs before/after each test.
    Redis is mocked, so no cleanup needed there.
    """
    # Clear before test
    ImportJob.objects.all().delete()

    yield

    # Clear after test
    ImportJob.objects.all().delete()


@pytest.fixture
def queue(mock_redis):
    """Provide a fresh ImportJobQueue instance with mocked Redis"""
    return ImportJobQueue()


@pytest.fixture
def sample_date():
    """Sample target date for import jobs"""
    return date(2024, 1, 15)


@pytest.fixture
def mock_celery_task():
    """Mock the Celery task to prevent actual task dispatch"""
    with patch(
        "core.tasks.tasks_decisions_import.fetch_daily_decisions_distributed"
    ) as mock_task:
        # Mock the .delay() method to return a fake async result
        mock_result = MagicMock()
        mock_result.id = "test-task-id-12345"
        mock_task.delay.return_value = mock_result
        yield mock_task


# ============================================================================
# Test: Basic Queue Operations
# ============================================================================


@pytest.mark.django_db
class TestQueueBasics:
    """Test basic queue operations like counting and capacity checks"""

    def test_empty_queue_can_start_new_job(self, queue, clear_import_queue):
        """Empty queue should allow new jobs"""
        assert queue.can_start_new_job() is True
        assert queue.get_active_jobs_count() == 0
        assert queue.get_pending_jobs_count() == 0

    def test_active_jobs_count_running(self, queue, sample_date, clear_import_queue):
        """Count RUNNING jobs as active"""
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )

        assert queue.get_active_jobs_count() == 1
        assert queue.can_start_new_job() is False  # At capacity (max=1)

    def test_active_jobs_count_all_active_statuses(
        self, queue, sample_date, clear_import_queue
    ):
        """Count all active statuses (FETCHING, PROCESSING, SPLITTING, RUNNING)"""
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.FETCHING,
        )
        ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.PROCESSING,
        )

        assert queue.get_active_jobs_count() == 2

    def test_pending_jobs_not_counted_as_active(
        self, queue, sample_date, clear_import_queue
    ):
        """PENDING jobs should not count as active"""
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.PENDING,
        )

        assert queue.get_active_jobs_count() == 0
        assert queue.get_pending_jobs_count() == 1
        assert queue.can_start_new_job() is True

    def test_completed_jobs_not_counted_as_active(
        self, queue, sample_date, clear_import_queue
    ):
        """COMPLETED jobs should not count as active"""
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.COMPLETED,
        )

        assert queue.get_active_jobs_count() == 0
        assert queue.can_start_new_job() is True


# ============================================================================
# Test: Job Enqueueing
# ============================================================================


@pytest.mark.django_db
class TestEnqueueJob:
    """Test job creation and enqueueing behavior"""

    def test_enqueue_creates_pending_job(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Enqueueing should create a job in PENDING state"""
        job = queue.enqueue_job(
            target_date=sample_date,
            search_params={"force": False},
            auto_dispatch=False,  # Don't auto-dispatch for this test
        )

        assert job.id is not None
        assert job.start_date == sample_date
        assert job.end_date == sample_date
        assert job.status == ImportJobStatus.PENDING
        assert job.search_params == {"force": False}

    def test_enqueue_with_auto_dispatch_starts_immediately(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Auto-dispatch should start job immediately when capacity available"""
        job = queue.enqueue_job(
            target_date=sample_date,
            search_params={"force": True},
            auto_dispatch=True,
        )

        # Job should have been dispatched (status changed to FETCHING)
        job.refresh_from_db()
        assert job.status == ImportJobStatus.FETCHING
        assert job.celery_task_id == "test-task-id-12345"

        # Celery task should have been called
        mock_celery_task.delay.assert_called_once()

    def test_enqueue_without_auto_dispatch_stays_pending(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Job should stay PENDING if auto_dispatch=False"""
        job = queue.enqueue_job(
            target_date=sample_date,
            auto_dispatch=False,
        )

        assert job.status == ImportJobStatus.PENDING
        assert job.celery_task_id is None
        mock_celery_task.delay.assert_not_called()

    def test_enqueue_when_at_capacity_queues_job(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Job should queue if capacity reached, even with auto_dispatch=True"""
        # Create a running job to fill capacity
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )

        # Try to enqueue another job with auto_dispatch
        job = queue.enqueue_job(
            target_date=sample_date + timedelta(days=1),
            auto_dispatch=True,
        )

        # Should stay PENDING (queued)
        assert job.status == ImportJobStatus.PENDING
        assert job.celery_task_id is None
        mock_celery_task.delay.assert_not_called()

    def test_enqueue_with_entity_filters(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Entity filters should be stored in job"""
        job = queue.enqueue_job(
            target_date=sample_date,
            organization_id=123,
            unit_id=456,
            signer_id=789,
            auto_dispatch=False,
        )

        assert job.organization_id == 123
        assert job.unit_id == 456
        assert job.signer_id == 789


# ============================================================================
# Test: Job Dispatching
# ============================================================================


@pytest.mark.django_db
class TestDispatchNextJob:
    """Test dispatching jobs from the queue"""

    def test_dispatch_next_job_fifo_order(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Jobs should be dispatched in FIFO order (oldest first)"""
        # Create 3 pending jobs
        job1 = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.PENDING,
            created_at=timezone.now() - timedelta(minutes=3),
        )
        job2 = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.PENDING,
            created_at=timezone.now() - timedelta(minutes=2),
        )
        job3 = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=2),
            end_date=sample_date + timedelta(days=2),
            status=ImportJobStatus.PENDING,
            created_at=timezone.now() - timedelta(minutes=1),
        )

        # Dispatch next job
        dispatched = queue.dispatch_next_job()

        # Should dispatch job1 (oldest)
        assert dispatched.id == job1.id
        job1.refresh_from_db()
        assert job1.status == ImportJobStatus.FETCHING
        assert job1.celery_task_id is not None

    def test_dispatch_when_at_capacity_returns_none(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Should not dispatch if at capacity"""
        # Fill capacity with a running job
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )

        # Create a pending job
        ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.PENDING,
        )

        # Try to dispatch
        dispatched = queue.dispatch_next_job()

        # Should return None (at capacity)
        assert dispatched is None
        mock_celery_task.delay.assert_not_called()

    def test_dispatch_with_no_pending_jobs_returns_none(
        self, queue, mock_celery_task, clear_import_queue
    ):
        """Should return None if no pending jobs"""
        dispatched = queue.dispatch_next_job()

        assert dispatched is None
        mock_celery_task.delay.assert_not_called()

    def test_dispatch_sets_status_before_celery_call(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Status should be set to FETCHING BEFORE Celery task dispatch (race condition prevention)"""
        job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.PENDING,
        )

        # Verify status is updated before Celery task is called
        celery_called = [False]
        original_delay = mock_celery_task.delay

        def track_celery_call(*args, **kwargs):
            # When Celery is called, job should already be in FETCHING status
            job.refresh_from_db()
            assert (
                job.status == ImportJobStatus.FETCHING
            ), "Job status should be FETCHING before Celery task dispatch"
            celery_called[0] = True
            return original_delay.return_value

        mock_celery_task.delay.side_effect = track_celery_call

        queue.dispatch_next_job()

        # Verify Celery was called and assertion passed
        assert celery_called[0], "Celery task should have been called"

        # Final verification
        job.refresh_from_db()
        assert job.status == ImportJobStatus.FETCHING

    def test_dispatch_includes_entity_filters_in_search_params(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Entity filters should be passed to Celery task"""
        job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.PENDING,
            organization_id=111,
            unit_id=222,
            signer_id=333,
            search_params={"force": True},
        )

        queue.dispatch_next_job()

        # Check search_params passed to Celery
        call_kwargs = mock_celery_task.delay.call_args[1]
        search_params = call_kwargs["search_params"]

        # Entity IDs are converted to strings in search params
        assert search_params["org"] == "111"
        assert search_params["unit"] == "222"
        assert search_params["signer"] == "333"
        assert search_params["force"] is True


# ============================================================================
# Test: Job Completion Handling
# ============================================================================


@pytest.mark.django_db
class TestOnJobCompleted:
    """Test auto-dispatch on job completion"""

    def test_on_completion_dispatches_next_queued_job(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Completing a job should auto-dispatch next pending job"""
        # Create a completed job
        completed_job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.COMPLETED,
        )

        # Create a pending job
        pending_job = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.PENDING,
        )

        # Simulate job completion notification
        queue.on_job_completed(completed_job.id)

        # Pending job should be dispatched
        pending_job.refresh_from_db()
        assert pending_job.status == ImportJobStatus.FETCHING
        assert pending_job.celery_task_id is not None
        mock_celery_task.delay.assert_called_once()

    def test_on_completion_with_no_pending_jobs(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Should handle completion gracefully when queue is empty"""
        job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.COMPLETED,
        )

        # No exception should be raised
        queue.on_job_completed(job.id)

        mock_celery_task.delay.assert_not_called()

    def test_on_completion_when_still_at_capacity(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Should not dispatch if still at capacity (another job running)"""
        # Two active jobs (at/over capacity)
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )
        completed_job = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.COMPLETED,
        )

        # Create pending job
        pending_job = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=2),
            end_date=sample_date + timedelta(days=2),
            status=ImportJobStatus.PENDING,
        )

        queue.on_job_completed(completed_job.id)

        # Pending job should NOT be dispatched (still at capacity)
        pending_job.refresh_from_db()
        assert pending_job.status == ImportJobStatus.PENDING
        mock_celery_task.delay.assert_not_called()


# ============================================================================
# Test: Queue Status
# ============================================================================


@pytest.mark.django_db
class TestQueueStatus:
    """Test queue status reporting"""

    def test_get_queue_status_empty(self, queue, clear_import_queue):
        """Status should show empty queue"""
        status = queue.get_queue_status()

        assert status["max_concurrent"] == 1
        assert status["active_count"] == 0
        assert status["pending_count"] == 0
        assert status["can_start_new"] is True
        assert status["active_jobs"] == []
        assert status["pending_jobs"] == []

    def test_get_queue_status_with_jobs(self, queue, sample_date, clear_import_queue):
        """Status should include job details"""
        active_job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )
        pending_job = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.PENDING,
        )

        status = queue.get_queue_status()

        assert status["active_count"] == 1
        assert status["pending_count"] == 1
        assert status["can_start_new"] is False

        # Check job details
        assert len(status["active_jobs"]) == 1
        assert status["active_jobs"][0]["id"] == active_job.id

        assert len(status["pending_jobs"]) == 1
        assert status["pending_jobs"][0]["id"] == pending_job.id


# ============================================================================
# Test: Stale Job Cleanup
# ============================================================================


@pytest.mark.django_db
class TestStaleJobCleanup:
    """Test cleanup of stuck/stale jobs"""

    def test_clear_stale_jobs_marks_old_running_jobs_as_failed(
        self, queue, sample_date, clear_import_queue
    ):
        """Old running jobs should be marked as failed"""
        # Create a job stuck in RUNNING state for 25 hours
        with freeze_time(timezone.now() - timedelta(hours=25)):
            stale_job = ImportJob.objects.create(
                start_date=sample_date,
                end_date=sample_date,
                status=ImportJobStatus.RUNNING,
            )

        # Clear stale jobs (max age 24 hours)
        count = queue.clear_stale_jobs(max_age_hours=24)

        assert count == 1
        stale_job.refresh_from_db()
        assert stale_job.status == ImportJobStatus.FAILED
        assert "timeout" in stale_job.error_details.lower()
        assert stale_job.completed_at is not None

    def test_clear_stale_jobs_respects_age_threshold(
        self, queue, sample_date, clear_import_queue
    ):
        """Jobs younger than threshold should not be marked as failed"""
        # Create a job that's only 20 hours old
        with freeze_time(timezone.now() - timedelta(hours=20)):
            recent_job = ImportJob.objects.create(
                start_date=sample_date,
                end_date=sample_date,
                status=ImportJobStatus.RUNNING,
            )

        # Clear stale jobs (max age 24 hours)
        count = queue.clear_stale_jobs(max_age_hours=24)

        assert count == 0
        recent_job.refresh_from_db()
        assert recent_job.status == ImportJobStatus.RUNNING

    def test_clear_stale_jobs_all_active_statuses(
        self, queue, sample_date, clear_import_queue
    ):
        """Should clear jobs in FETCHING, PROCESSING, SPLITTING statuses"""
        with freeze_time(timezone.now() - timedelta(hours=25)):
            job1 = ImportJob.objects.create(
                start_date=sample_date,
                end_date=sample_date,
                status=ImportJobStatus.FETCHING,
            )
            job2 = ImportJob.objects.create(
                start_date=sample_date + timedelta(days=1),
                end_date=sample_date + timedelta(days=1),
                status=ImportJobStatus.PROCESSING,
            )
            job3 = ImportJob.objects.create(
                start_date=sample_date + timedelta(days=2),
                end_date=sample_date + timedelta(days=2),
                status=ImportJobStatus.SPLITTING,
            )

        count = queue.clear_stale_jobs(max_age_hours=24)

        assert count == 3
        for job in [job1, job2, job3]:
            job.refresh_from_db()
            assert job.status == ImportJobStatus.FAILED

    def test_clear_stale_jobs_does_not_affect_pending_or_completed(
        self, queue, sample_date, clear_import_queue
    ):
        """PENDING and COMPLETED jobs should not be cleared"""
        with freeze_time(timezone.now() - timedelta(hours=25)):
            pending_job = ImportJob.objects.create(
                start_date=sample_date,
                end_date=sample_date,
                status=ImportJobStatus.PENDING,
            )
            completed_job = ImportJob.objects.create(
                start_date=sample_date + timedelta(days=1),
                end_date=sample_date + timedelta(days=1),
                status=ImportJobStatus.COMPLETED,
            )

        count = queue.clear_stale_jobs(max_age_hours=24)

        assert count == 0
        pending_job.refresh_from_db()
        assert pending_job.status == ImportJobStatus.PENDING
        completed_job.refresh_from_db()
        assert completed_job.status == ImportJobStatus.COMPLETED


# ============================================================================
# Test: Redis Integration
# ============================================================================


@pytest.mark.django_db
class TestRedisIntegration:
    """Test Redis connection setup (mocked for unit tests)"""

    def test_redis_connection_established(self, queue, mock_redis, clear_import_queue):
        """Queue should successfully connect to Redis (mocked)"""
        assert queue.redis_client is not None
        assert queue.redis_client == mock_redis

        # Test basic Redis operation (mocked)
        queue.redis_client.set("test_key", "test_value")
        assert queue.redis_client.get("test_key") == b"test_value"

        # Verify Redis methods were called
        mock_redis.set.assert_called_with("test_key", "test_value")
        mock_redis.get.assert_called_with("test_key")

    def test_queue_uses_correct_redis_database(
        self, queue, mock_redis, clear_import_queue
    ):
        """Queue should use 'import_chunks' Redis connection (DB 2)"""
        # Verify the Redis client has the expected connection pool config
        assert queue.redis_client.connection_pool.connection_kwargs == {"db": 2}


# ============================================================================
# Test: Concurrency Edge Cases
# ============================================================================


@pytest.mark.django_db
class TestConcurrencyEdgeCases:
    """Test edge cases in concurrent scenarios"""

    @patch("core.services.import_job_queue.ImportJobQueue.MAX_CONCURRENT_JOBS", 2)
    def test_multiple_concurrent_jobs_allowed(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Should allow multiple concurrent jobs up to MAX_CONCURRENT_JOBS"""
        # Create 2 running jobs (should be allowed with MAX=2)
        ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.RUNNING,
        )
        ImportJob.objects.create(
            start_date=sample_date + timedelta(days=1),
            end_date=sample_date + timedelta(days=1),
            status=ImportJobStatus.RUNNING,
        )

        # Re-initialize queue to pick up the patched MAX_CONCURRENT_JOBS
        queue_with_new_limit = ImportJobQueue()

        # Should be at capacity
        assert queue_with_new_limit.get_active_jobs_count() == 2
        assert queue_with_new_limit.can_start_new_job() is False

        # Create a pending job
        pending_job = ImportJob.objects.create(
            start_date=sample_date + timedelta(days=2),
            end_date=sample_date + timedelta(days=2),
            status=ImportJobStatus.PENDING,
        )

        # Should not dispatch (at capacity)
        dispatched = queue_with_new_limit.dispatch_next_job()
        assert dispatched is None

    def test_enqueue_and_dispatch_race_condition_prevention(
        self, queue, sample_date, mock_celery_task, clear_import_queue
    ):
        """Status update before Celery dispatch prevents race conditions"""
        # Create pending job
        job = ImportJob.objects.create(
            start_date=sample_date,
            end_date=sample_date,
            status=ImportJobStatus.PENDING,
        )

        # Track that active count is 1 when Celery task is called
        active_count_during_dispatch = None

        def check_active_count(*args, **kwargs):
            nonlocal active_count_during_dispatch
            # Simulate another thread checking capacity during dispatch
            active_count_during_dispatch = queue.get_active_jobs_count()
            # Return a mock result
            mock_result = MagicMock()
            mock_result.id = "test-task-id-12345"
            return mock_result

        mock_celery_task.delay.side_effect = check_active_count

        queue.dispatch_next_job()

        # Job should already be in FETCHING state when Celery was called
        assert (
            active_count_during_dispatch == 1
        ), "Job status should be updated BEFORE Celery call"

        # Verify the job is in FETCHING state
        job.refresh_from_db()
        assert job.status == ImportJobStatus.FETCHING
