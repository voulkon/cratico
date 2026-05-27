"""
Import Job Queue Service - Manages concurrent import job execution

Problem:
    Multiple ImportJobs running simultaneously each load hundreds of thousands
    of decisions into Redis, causing memory exhaustion (1.2GB+ with 530k keys).

Solution:
    - Limit concurrent ImportJobs to prevent Redis/OpenSearch overload
    - Queue pending jobs and process them sequentially (or with limited parallelism)
    - Use Redis-based distributed locking for multi-worker coordination

Usage:
    from core.services.import_job_queue import ImportJobQueue

    queue = ImportJobQueue()

    # Check if we can start a new job
    if queue.can_start_new_job():
        job = queue.enqueue_job(target_date, search_params, ...)
    else:
        # Job will be queued and processed later
        job = queue.enqueue_job(target_date, search_params, ...)
"""

from datetime import date, datetime
from typing import Any, Dict, Optional

from api.redis_keys import (
    IMPORT_JOB_QUEUE_ACTIVE,
    IMPORT_JOB_QUEUE_LOCK,
    IMPORT_JOB_QUEUE_PENDING,
)
from core.models.import_jobs import ImportJob, ImportJobStatus
from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django.conf import settings
from django_redis import get_redis_connection
from loguru import logger


class ImportJobQueue:
    """
    Manages import job queueing and concurrency control.

    Uses Redis for distributed coordination across multiple workers.
    """

    # Redis keys for the import queue (centralized in redis_keys.py)
    QUEUE_KEY = IMPORT_JOB_QUEUE_PENDING
    ACTIVE_KEY = IMPORT_JOB_QUEUE_ACTIVE
    LOCK_KEY = IMPORT_JOB_QUEUE_LOCK

    # Maximum concurrent import jobs (configurable via Django settings)
    MAX_CONCURRENT_JOBS = getattr(settings, "IMPORT_MAX_CONCURRENT_JOBS", 1)

    # Lock timeout (seconds) - prevents stale locks if worker crashes
    LOCK_TIMEOUT = 300  # 5 minutes

    def __init__(self):
        """Initialize Redis connection for queue management"""
        # Reuse Django's connection pool for DB 2 (same as decision chunks)
        # This prevents connection exhaustion and resource leaks
        self.redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)

    def get_active_jobs_count(self) -> int:
        """
        Count currently active (RUNNING/FETCHING/PROCESSING) ImportJobs.

        Returns:
            Number of active jobs in database
        """
        return ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ]
        ).count()

    def get_pending_jobs_count(self) -> int:
        """
        Count pending ImportJobs waiting in queue.

        Returns:
            Number of pending jobs in database
        """
        return ImportJob.objects.filter(status=ImportJobStatus.PENDING).count()

    def can_start_new_job(self) -> bool:
        """
        Check if we can start a new import job immediately.

        Also warns if stale jobs are detected (stuck for >6 hours).

        Returns:
            True if under concurrency limit, False otherwise
        """
        active_count = self.get_active_jobs_count()

        # [WARN]️ CRITICAL FIX: Also check PROCESSING jobs to prevent chunk explosion
        # Without this, jobs can create chunks while previous jobs are still processing,
        # causing worker queue buildup and Redis chunk expiration (24h TTL).
        #
        # Example: 15 jobs × 2,796 chunks = 41,940 tasks queued
        #          With 2 workers, this takes ~15 days → chunks expire!
        processing_count = ImportJob.objects.filter(
            status=ImportJobStatus.PROCESSING
        ).count()

        # Only allow new job if BOTH fetching AND processing are below limit
        can_start = (
            active_count < self.MAX_CONCURRENT_JOBS
            and processing_count < self.MAX_CONCURRENT_JOBS
        )

        # Check for potentially stale jobs (stuck for >6 hours)
        if active_count > 0:
            from datetime import timedelta

            from django.utils import timezone

            stale_cutoff = timezone.now() - timedelta(hours=6)
            stale_count = ImportJob.objects.filter(
                status__in=[
                    ImportJobStatus.RUNNING,
                    ImportJobStatus.FETCHING,
                    ImportJobStatus.PROCESSING,
                    ImportJobStatus.SPLITTING,
                ],
                created_at__lt=stale_cutoff,
            ).count()

            if stale_count > 0:
                logger.warning(
                    f"ImportJobQueue: {stale_count} potentially stale jobs detected "
                    f"(stuck for >6 hours). Run 'python manage.py import_queue clear-stale' "
                    f"to clean them up."
                )

        logger.debug(
            f"ImportJobQueue: Active jobs={active_count}, "
            f"Processing jobs={processing_count}, "
            f"Max concurrent={self.MAX_CONCURRENT_JOBS}, "
            f"Can start new={can_start}"
        )

        return can_start

    def enqueue_job(
        self,
        target_date: date,
        search_params: Optional[Dict[str, Any]] = None,
        created_by=None,
        organization_id: Optional[int] = None,
        unit_id: Optional[int] = None,
        signer_id: Optional[int] = None,
        auto_dispatch: bool = True,
        skip_duplicates: bool = True,
    ) -> ImportJob:
        """
        Create an ImportJob and optionally dispatch it if capacity available.

        Args:
            target_date: Date to import
            search_params: API search parameters
            created_by: User who initiated the import
            organization_id: Optional organization filter
            unit_id: Optional unit filter
            signer_id: Optional signer filter
            auto_dispatch: If True, dispatch immediately if capacity available
            skip_duplicates: If True, return existing job instead of creating duplicate

        Returns:
            Created or existing ImportJob instance
        """
        # Check for duplicate jobs (same date + filters, not yet completed/failed)
        if skip_duplicates:
            existing_job = ImportJob.objects.filter(
                start_date=target_date,
                end_date=target_date,
                organization_id=organization_id,
                unit_id=unit_id,
                signer_id=signer_id,
                status__in=[
                    ImportJobStatus.PENDING,
                    ImportJobStatus.RUNNING,
                    ImportJobStatus.FETCHING,
                    ImportJobStatus.PROCESSING,
                    ImportJobStatus.SPLITTING,
                ],
            ).first()

            if existing_job:
                logger.info(
                    f"ImportJobQueue: Skipping duplicate - Job #{existing_job.id} "
                    f"already exists for {target_date} (status: {existing_job.status})"
                )
                return existing_job

        # Create ImportJob in PENDING state
        job = ImportJob.objects.create(
            start_date=target_date,
            end_date=target_date,
            organization_id=organization_id,
            unit_id=unit_id,
            signer_id=signer_id,
            status=ImportJobStatus.PENDING,
            created_by=created_by,
            created_at=datetime.now(),
            search_params=search_params or {},
        )

        logger.info(f"ImportJobQueue: Created ImportJob #{job.id} for {target_date}")

        # Try to dispatch immediately if capacity available
        if auto_dispatch and self.can_start_new_job():
            self.dispatch_next_job()
        else:
            logger.info(
                f"ImportJobQueue: Job #{job.id} queued (active jobs at capacity)"
            )

        return job

    def dispatch_next_job(self) -> Optional[ImportJob]:
        """
        Dispatch the next pending job if capacity available.

        This is called:
        1. After enqueueing a new job (if capacity available)
        2. After a job completes (to process the queue)

        Returns:
            Dispatched ImportJob or None if no job dispatched
        """
        # Check capacity
        if not self.can_start_new_job():
            logger.debug("ImportJobQueue: At capacity, cannot dispatch new job")
            return None

        # Get next pending job (FIFO by creation time)
        next_job = (
            ImportJob.objects.filter(status=ImportJobStatus.PENDING)
            .order_by("created_at")
            .first()
        )

        if not next_job:
            logger.debug("ImportJobQueue: No pending jobs to dispatch")
            return None

        # Dispatch the job
        from core.tasks.tasks_decisions_import import fetch_daily_decisions_distributed

        logger.info(
            f"ImportJobQueue: Dispatching Job #{next_job.id} for {next_job.start_date}"
        )

        # Build search params
        search_params = next_job.search_params or {}

        # Add entity filters if present
        if next_job.organization_id:
            search_params["org"] = next_job.organization_id
        if next_job.unit_id:
            search_params["unit"] = next_job.unit_id
        if next_job.signer_id:
            search_params["signer"] = next_job.signer_id

        # [WARN]️ CRITICAL: Update status to FETCHING BEFORE dispatching to prevent race conditions
        # This ensures concurrent calls to dispatch_next_job() see this job as "active"
        next_job.status = ImportJobStatus.FETCHING
        next_job.save(update_fields=["status"])

        # Dispatch Celery task
        async_result = fetch_daily_decisions_distributed.delay(
            target_date_str=next_job.start_date.isoformat(),
            chunk_size=10,
            force=search_params.get("force", False),
            job_id=next_job.id,
            search_params=search_params,
        )

        # Update job with task ID
        next_job.celery_task_id = async_result.id
        next_job.save(update_fields=["celery_task_id"])

        logger.info(
            f"ImportJobQueue: Dispatched Job #{next_job.id}, "
            f"Task ID: {async_result.id}"
        )

        return next_job

    def on_job_completed(self, job_id: int):
        """
        Called when an ImportJob completes (success or failure).

        Triggers dispatch of next queued job if capacity available.
        Also triggers continuous backfill if AUTO_BACKFILL_ENABLED is true.

        Args:
            job_id: ID of completed ImportJob
        """
        logger.info(f"ImportJobQueue: Job #{job_id} completed, checking queue")

        # Try to dispatch next job from the pending queue
        dispatched = self.dispatch_next_job()

        if dispatched:
            logger.info(f"ImportJobQueue: Auto-dispatched next job #{dispatched.id}")
        else:
            pending_count = self.get_pending_jobs_count()
            if pending_count > 0:
                logger.info(
                    f"ImportJobQueue: {pending_count} jobs pending, "
                    f"waiting for capacity"
                )
            else:
                # No pending jobs - trigger continuous backfill if enabled
                # This creates the autofarming loop
                from core.tasks.tasks_auto_import import trigger_next_backfill

                logger.info(
                    "ImportJobQueue: No pending jobs, triggering backfill check"
                )
                trigger_next_backfill.delay()

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status for monitoring.

        Returns:
            Dict with active, pending, and completed job counts
        """
        active_jobs = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ]
        ).values("id", "start_date", "status", "created_at")

        pending_jobs = ImportJob.objects.filter(status=ImportJobStatus.PENDING).values(
            "id", "start_date", "created_at"
        )

        return {
            "max_concurrent": self.MAX_CONCURRENT_JOBS,
            "active_count": len(active_jobs),
            "pending_count": len(pending_jobs),
            "can_start_new": self.can_start_new_job(),
            "active_jobs": list(active_jobs),
            "pending_jobs": list(pending_jobs),
        }

    def clear_stale_jobs(self, max_age_hours: int = 24) -> int:
        """
        Mark stuck jobs as failed (e.g., worker crashed mid-processing).

        Args:
            max_age_hours: Jobs older than this are considered stale

        Returns:
            Number of jobs marked as failed
        """
        from datetime import timedelta

        from django.utils import timezone

        cutoff = timezone.now() - timedelta(hours=max_age_hours)

        stale_jobs = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ],
            created_at__lt=cutoff,
        )

        count = stale_jobs.count()

        if count > 0:
            stale_jobs.update(
                status=ImportJobStatus.FAILED,
                error_details=f"Job marked as failed after {max_age_hours}h timeout",
                completed_at=timezone.now(),
            )
            logger.warning(f"ImportJobQueue: Marked {count} stale jobs as failed")

        return count
