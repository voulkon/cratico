"""
Re-dispatch store_decisions_from_redis tasks for chunks still in Redis.

Use case: After a worker re-deploy, Celery/RabbitMQ task messages may be lost
while the Redis chunks still exist. This command finds all surviving chunks for
a given ImportJob and re-dispatches the processing tasks.

Usage:
    # Dry-run: see how many chunks are left without dispatching
    python manage.py redispatch_redis_chunks 1122 --dry-run

    # Actually re-dispatch all remaining chunks
    python manage.py redispatch_redis_chunks 1122

    # Limit how many tasks are dispatched at once
    python manage.py redispatch_redis_chunks 1122 --limit 100
"""

import random

from api.redis_keys import IMPORT_CHUNK_PREFIX
from core.models.import_jobs import ImportJob, ImportJobStatus
from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django.core.management.base import BaseCommand, CommandError
from django_redis import get_redis_connection
from loguru import logger


class Command(BaseCommand):
    help = "Re-dispatch store_decisions_from_redis tasks for chunks still in Redis after a worker restart"

    def add_arguments(self, parser):
        parser.add_argument(
            "job_id",
            type=int,
            help="ImportJob ID whose remaining Redis chunks should be re-dispatched",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only scan and report — do not dispatch any tasks",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Maximum number of tasks to dispatch (0 = no limit)",
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        dry_run = options["dry_run"]
        limit = options["limit"]

        # Verify the ImportJob exists
        try:
            job = ImportJob.objects.get(pk=job_id)
        except ImportJob.DoesNotExist:
            raise CommandError(f"ImportJob #{job_id} not found")

        self.stdout.write(
            self.style.SUCCESS(f"\n=== Re-dispatch Redis Chunks for ImportJob #{job_id} ===\n")
        )
        self.stdout.write(f"  Date:   {job.start_date}")
        self.stdout.write(f"  Status: {job.status}")
        self.stdout.write(
            f"  Chunks: {job.chunks_completed} completed + {job.chunks_failed} failed "
            f"out of {job.total_chunks} total\n"
        )

        if job.status not in (
            ImportJobStatus.PROCESSING,
            ImportJobStatus.SPLITTING,
            ImportJobStatus.RUNNING,
            ImportJobStatus.FETCHING,
        ):
            self.stdout.write(
                self.style.WARNING(
                    f"Job is in status '{job.status}' — only PROCESSING/SPLITTING jobs "
                    f"typically need re-dispatch. Continuing anyway..."
                )
            )

        # Scan Redis for remaining chunks
        redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)
        pattern = f"{IMPORT_CHUNK_PREFIX}{job_id}_*"

        self.stdout.write(f"Scanning Redis pattern: {pattern}")

        chunk_keys = []
        for key in redis_client.scan_iter(match=pattern, count=500):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            chunk_keys.append(key_str)

        self.stdout.write(
            self.style.SUCCESS(f"Found {len(chunk_keys)} chunks still in Redis\n")
        )

        if not chunk_keys:
            self.stdout.write(
                self.style.WARNING(
                    "No chunks found in Redis. They may have already been processed "
                    "or the 72h TTL has expired.\n"
                    "If the job is stuck in PROCESSING, run:\n"
                    "  python manage.py import_queue clear-stale"
                )
            )
            return

        # Extract chunk_ids from Redis keys
        # Key format: import:chunk:<chunk_id>  →  strip the prefix
        prefix = IMPORT_CHUNK_PREFIX  # "import:chunk:"
        chunk_ids = [k[len(prefix):] for k in chunk_keys]

        if limit > 0:
            chunk_ids = chunk_ids[:limit]
            self.stdout.write(
                self.style.WARNING(f"--limit applied: dispatching only {len(chunk_ids)} chunks\n")
            )

        if dry_run:
            self.stdout.write(self.style.SUCCESS("[DRY RUN] Would dispatch:"))
            for cid in chunk_ids[:20]:
                self.stdout.write(f"  store_decisions_from_redis({cid!r}, job_id={job_id})")
            if len(chunk_ids) > 20:
                self.stdout.write(f"  ... and {len(chunk_ids) - 20} more")
            self.stdout.write(
                f"\n[DRY RUN] Total to dispatch: {len(chunk_ids)} tasks (not dispatched)"
            )
            return

        # Dispatch tasks
        from core.tasks.tasks_decisions_import import store_decisions_from_redis

        dispatched = 0
        failed = 0

        for chunk_id in chunk_ids:
            try:
                delay_seconds = random.uniform(0.1, 2.0)
                store_decisions_from_redis.apply_async(
                    args=[chunk_id, job_id],
                    kwargs={"delay_seconds": delay_seconds},
                )
                dispatched += 1
                if dispatched % 100 == 0:
                    self.stdout.write(f"  Dispatched {dispatched}/{len(chunk_ids)}...")
            except Exception as e:
                failed += 1
                logger.error(f"Failed to dispatch chunk {chunk_id}: {e}")
                self.stdout.write(self.style.ERROR(f"  Failed to dispatch {chunk_id}: {e}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nDone. Dispatched {dispatched} tasks, {failed} failures.\n"
                f"Monitor progress at /admin/core/importjob/{job_id}/change/"
            )
        )
