"""
Management command to cancel in-progress imports.

Cancels ImportJobs, revokes Celery tasks, cleans Redis chunks,
and optionally purges the RabbitMQ queue.

Usage:
    # Cancel ALL in-progress imports (revoke + clean Redis DB 2)
    python manage.py cancel_imports --all

    # Also purge RabbitMQ queue (removes ALL pending Celery tasks)
    python manage.py cancel_imports --all --purge-rabbitmq

    # Cancel a specific job
    python manage.py cancel_imports --job-id 123

    # Dry-run: show what would be cancelled without doing it
    python manage.py cancel_imports --all --dry-run
"""

from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cancel in-progress imports: revoke tasks, clean Redis, optionally purge RabbitMQ"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--all",
            action="store_true",
            help="Cancel ALL in-progress imports",
        )
        group.add_argument(
            "--job-id",
            type=int,
            help="Cancel a specific ImportJob by ID",
        )

        parser.add_argument(
            "--purge-rabbitmq",
            action="store_true",
            help="Also purge the RabbitMQ 'celery' queue (removes ALL pending tasks, not just imports)",
        )
        parser.add_argument(
            "--no-clean-redis",
            action="store_true",
            help="Skip Redis DB 2 cleanup (default: clean Redis)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without actually doing it",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        purge_rabbitmq = options["purge_rabbitmq"]
        clean_redis = not options["no_clean_redis"]

        if options["job_id"]:
            self._cancel_single_job(options["job_id"], dry_run, clean_redis)
        else:
            self._cancel_all(dry_run, purge_rabbitmq, clean_redis)

    def _cancel_single_job(self, job_id: int, dry_run: bool, clean_redis: bool):
        """Cancel a single ImportJob."""
        try:
            job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"ImportJob #{job_id} not found"))
            return

        cancelable = [
            ImportJobStatus.PENDING,
            ImportJobStatus.RUNNING,
            ImportJobStatus.FETCHING,
            ImportJobStatus.SPLITTING,
            ImportJobStatus.PROCESSING,
        ]

        if job.status not in cancelable:
            self.stdout.write(
                self.style.WARNING(
                    f"ImportJob #{job_id} is in terminal state '{job.status}', "
                    f"nothing to cancel"
                )
            )
            return

        self.stdout.write(
            f"\nJob #{job.id} | {job.start_date} | status={job.status}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"  [DRY RUN] Would cancel job #{job.id}, "
                    f"revoke task {job.celery_task_id}, "
                    f"clean Redis chunks"
                )
            )
            return

        result = job.cancel(revoke_task=True, clean_redis=clean_redis)
        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Cancelled ImportJob #{job.id}. Actions: {result['actions']}"
            )
        )

    def _cancel_all(self, dry_run: bool, purge_rabbitmq: bool, clean_redis: bool):
        """Cancel all in-progress imports."""
        cancelable_statuses = [
            ImportJobStatus.PENDING,
            ImportJobStatus.RUNNING,
            ImportJobStatus.FETCHING,
            ImportJobStatus.SPLITTING,
            ImportJobStatus.PROCESSING,
        ]

        jobs = ImportJob.objects.filter(status__in=cancelable_statuses)

        if dry_run:
            self.stdout.write("\n" + "=" * 60)
            self.stdout.write(self.style.WARNING("[DRY RUN] Would cancel:"))
            self.stdout.write("=" * 60)

            for job in jobs:
                self.stdout.write(
                    f"  #{job.id} | {job.start_date} | {job.status} | "
                    f"task={job.celery_task_id or 'N/A'}"
                )

            self.stdout.write(
                f"\nTotal: {jobs.count()} job(s) would be cancelled"
            )
            if purge_rabbitmq:
                self.stdout.write(
                    self.style.WARNING(
                        "  + Would purge RabbitMQ 'celery' queue"
                    )
                )
            if clean_redis:
                self.stdout.write(
                    self.style.WARNING(
                        "  + Would flush Redis DB 2 (import chunks)"
                    )
                )
            return

        # Confirm destructive operation
        if purge_rabbitmq:
            self.stdout.write(
                self.style.WARNING(
                    "\n[WARN]️ --purge-rabbitmq will remove ALL pending Celery tasks, "
                    "not just import ones!"
                )
            )

        self.stdout.write(
            f"\nCancelling {jobs.count()} in-progress import(s)..."
        )

        queue = ImportJobQueue()
        result = queue.cancel_all_in_progress_imports(
            purge_rabbitmq=purge_rabbitmq,
            clean_redis=clean_redis,
        )

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("Cancel complete!"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"  Jobs cancelled:     {result['jobs_cancelled']}")
        self.stdout.write(f"  Tasks revoked:      {result['tasks_revoked']}")
        self.stdout.write(f"  Redis:              {result.get('redis_keys_deleted', 'skipped')}")
        self.stdout.write(f"  RabbitMQ purged:    {result['rabbitmq_purged']}")
        self.stdout.write(f"  Queue metadata:     {'cleaned' if result.get('queue_metadata_cleaned') else 'skipped'}")

        if result.get("redis_cleanup_error"):
            self.stdout.write(
                self.style.ERROR(f"  Redis error: {result['redis_cleanup_error']}")
            )
        if result.get("rabbitmq_purge_error"):
            self.stdout.write(
                self.style.ERROR(f"  RabbitMQ error: {result['rabbitmq_purge_error']}")
            )
