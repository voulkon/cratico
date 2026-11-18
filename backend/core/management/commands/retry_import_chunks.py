"""
Management command to manually retry chunks for stuck import jobs

Usage:
    # Retry all missing chunks for job 849
    python manage.py retry_import_chunks 849

    # Retry specific chunk IDs
    python manage.py retry_import_chunks 849 --chunk-ids 849_chunk_100 849_chunk_101

    # Check which chunks are missing without retrying
    python manage.py retry_import_chunks 849 --dry-run
"""

from api.redis_keys import get_import_chunk_scan_pattern
from core.models.import_jobs import ImportJob
from core.services.import_chunk_recovery import ImportChunkRecoveryService
from core.services.redis_decision_cache import (
    RedisDecisionCache,
    parse_chunk_index,
)
from core.tasks.tasks_decisions_import import store_decisions_from_redis
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Retry chunks for stuck import jobs"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int, help="ImportJob ID to retry chunks for")
        parser.add_argument(
            "--chunk-ids",
            nargs="+",
            help="Specific chunk IDs to retry (e.g., 849_chunk_100)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be retried without actually retrying",
        )
        parser.add_argument(
            "--all-missing",
            action="store_true",
            help="Retry all chunks that exist in Redis but haven't completed",
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        chunk_ids = options.get("chunk_ids", [])
        dry_run = options["dry_run"]
        all_missing = options["all_missing"]

        # Get the import job
        try:
            job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            raise CommandError(f"ImportJob {job_id} does not exist")

        self.stdout.write(self.style.SUCCESS(f"\n=== Import Job #{job.id} ==="))
        self.stdout.write(f"Status: {job.status}")
        self.stdout.write(f"Date: {job.start_date}")
        self.stdout.write(f"Created: {job.created_at}")

        age = timezone.now() - job.created_at
        self.stdout.write(f"Age: {age.seconds//3600}h {(age.seconds%3600)//60}m")

        # Show chunk statistics
        self.stdout.write(f"\n=== Chunk Statistics ===")
        self.stdout.write(f"Total chunks: {job.total_chunks}")
        self.stdout.write(f"Completed: {job.chunks_completed}")
        self.stdout.write(f"Failed: {job.chunks_failed}")
        missing = job.total_chunks - job.chunks_completed - job.chunks_failed
        self.stdout.write(f"Missing: {missing}")

        # Show pipeline statistics
        self.stdout.write(f"\n=== Pipeline Statistics ===")
        self.stdout.write(f"Total decisions: {job.total_decisions}")
        self.stdout.write(f"Restored from Redis: {job.decisions_restored_from_redis}")
        self.stdout.write(f"Assigned to pipeline: {job.decisions_assigned_to_pipeline}")

        # Discover chunks through the same helper the producer uses.  The old
        # hand-written ``decision_chunk:<date>_*`` pattern scanned a namespace
        # that no longer exists.
        redis_cache = RedisDecisionCache()
        recovery = ImportChunkRecoveryService(redis_cache)
        snapshot = recovery.inspect_job(job)
        redis_chunks = [f"{job.id}_chunk_{index}" for index in snapshot["recoverable"]]

        self.stdout.write(f"\n=== Redis Chunk Discovery ===")
        self.stdout.write(f"Scanning pattern: {get_import_chunk_scan_pattern(job.id)}")
        self.stdout.write(f"Recoverable chunks in Redis: {len(redis_chunks)}")
        self.stdout.write(f"Lost chunks (no payload): {len(snapshot['lost'])}")

        # Determine which chunks to retry
        chunks_to_retry = []

        if chunk_ids:
            # Retry specific chunk IDs
            chunks_to_retry = chunk_ids
            self.stdout.write(f"\nRetrying {len(chunks_to_retry)} specific chunks")
        elif all_missing:
            # Retry all chunks found in Redis
            chunks_to_retry = redis_chunks
            self.stdout.write(
                f"\nRetrying all {len(chunks_to_retry)} chunks found in Redis"
            )
        else:
            # Show what's available but don't retry
            if redis_chunks:
                self.stdout.write(f"\n=== Available chunks in Redis ===")
                for i, chunk_id in enumerate(redis_chunks[:20], 1):
                    self.stdout.write(f"  {i}. {chunk_id}")
                if len(redis_chunks) > 20:
                    self.stdout.write(f"  ... and {len(redis_chunks) - 20} more")

            self.stdout.write(
                self.style.WARNING(
                    f"\nUse --all-missing to retry all {len(redis_chunks)} chunks, "
                    f"or specify --chunk-ids to retry specific chunks"
                )
            )
            if snapshot["lost"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"{len(snapshot['lost'])} chunk(s) have no payload and cannot "
                        f"be retried; run the watchdog or re-import the date."
                    )
                )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\n=== DRY RUN - No chunks will be retried ===")
            )
            for i, chunk_id in enumerate(chunks_to_retry, 1):
                self.stdout.write(f"  {i}. Would retry: {chunk_id}")
            return

        # Actually retry the chunks
        self.stdout.write(
            self.style.SUCCESS(f"\n=== Retrying {len(chunks_to_retry)} chunks ===")
        )

        retried = 0
        failed = 0

        for i, chunk_id in enumerate(chunks_to_retry, 1):
            try:
                chunk_index = parse_chunk_index(chunk_id)

                # Verify chunk exists in Redis
                if not redis_cache.chunk_exists(chunk_id):
                    self.stdout.write(
                        self.style.WARNING(
                            f"  {i}/{len(chunks_to_retry)} SKIP: {chunk_id} (not in Redis)"
                        )
                    )
                    continue

                # A previously failed chunk is already counted in
                # chunks_failed.  Reopen it so the retry can count as
                # completed instead of double-counting the job.
                previous_state = redis_cache.get_chunk_state(job.id, chunk_index)
                if previous_state == "failed":
                    job.reopen_chunk_failure()
                redis_cache.clear_chunk_state(job.id, chunk_index)

                # Dispatch retry task with delay to avoid overwhelming the system
                delay_seconds = i * 0.5  # Stagger by 0.5s each

                result = store_decisions_from_redis.delay(
                    chunk_id=chunk_id,
                    job_id=job.id,
                    skip_opensearch=False,
                    delay_seconds=delay_seconds,
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f"  {i}/{len(chunks_to_retry)} [OK] Dispatched: {chunk_id} (task: {result.id[:8]}..., delay: {delay_seconds:.1f}s)"
                    )
                )
                retried += 1

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {i}/{len(chunks_to_retry)} [FAIL] Failed: {chunk_id} - {str(e)}"
                    )
                )
                failed += 1

        # Summary
        self.stdout.write(f"\n=== Summary ===")
        self.stdout.write(
            self.style.SUCCESS(f"[OK] Successfully dispatched: {retried}")
        )
        if failed > 0:
            self.stdout.write(self.style.ERROR(f"[FAIL] Failed to dispatch: {failed}"))

        self.stdout.write(
            f"\nMonitor progress at: /api/admin/core/importjob/{job.id}/change/"
        )
        self.stdout.write(f"Or use queue monitor: /api/admin/core/importjob/monitor/")
