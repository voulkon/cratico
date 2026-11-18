"""
Management command to inspect Redis chunks for a specific date

Usage:
    # Check chunks for May 13, 2026
    python manage.py inspect_redis_chunks 2026-05-13

    # Check with sample data preview
    python manage.py inspect_redis_chunks 2026-05-13 --preview
"""

import json
from datetime import datetime

from api.redis_keys import get_import_chunk_key, get_import_chunk_scan_pattern
from core.models.import_jobs import ImportJob
from core.services.redis_decision_cache import RedisDecisionCache
from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Inspect Redis chunks for a specific date"

    def add_arguments(self, parser):
        parser.add_argument(
            "date", type=str, help="Date in ISO format (e.g., 2026-05-13)"
        )
        parser.add_argument(
            "--preview", action="store_true", help="Show preview of chunk data"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=10,
            help="Number of chunks to preview (default: 10)",
        )

    def handle(self, *args, **options):
        date_str = options["date"]
        preview = options["preview"]
        limit = options["limit"]

        target_date = datetime.fromisoformat(date_str).date()
        jobs = list(
            ImportJob.objects.filter(start_date=target_date).order_by("-created_at")
        )

        cache = RedisDecisionCache()

        self.stdout.write(
            self.style.SUCCESS(f"\n=== Redis Chunk Inspection for {date_str} ===\n")
        )
        self.stdout.write(f"Redis DB: {IMPORT_CHUNKS_REDIS_DB_NAME}\n")

        if not jobs:
            self.stdout.write(
                self.style.WARNING(f"No import jobs found for {target_date}")
            )
            return

        # Every scan goes through the producer's key helper.  The old
        # ``decision_chunk:<date>_*`` namespace no longer exists.
        chunk_ids = []
        for job in jobs:
            self.stdout.write(f"Scanning job #{job.id}: {get_import_chunk_scan_pattern(job.id)}")
            chunk_ids.extend(cache.list_job_chunk_ids(job.id))

        self.stdout.write(
            self.style.SUCCESS(f"\n[OK] Found {len(chunk_ids)} chunks in Redis\n")
        )

        if not chunk_ids:
            self.stdout.write(
                self.style.WARNING(
                    "No chunks found. They may have been processed or never created."
                )
            )
            return

        # Show statistics
        total_size = 0
        ttl_values = {}
        for chunk_id in chunk_ids:
            key = get_import_chunk_key(chunk_id)
            memory_usage = cache.redis_client.memory_usage(key)
            if memory_usage:
                total_size += memory_usage
            ttl_values[chunk_id] = cache.get_chunk_ttl(chunk_id)

        self.stdout.write(f"Total memory usage: {total_size / 1024 / 1024:.2f} MB")
        self.stdout.write(
            f"Average per chunk: {total_size / len(chunk_ids) / 1024:.2f} KB\n"
        )

        # Show sample keys
        self.stdout.write(self.style.HTTP_INFO("Sample chunk keys:"))
        for i, chunk_id in enumerate(chunk_ids[:10], 1):
            ttl = ttl_values.get(chunk_id)
            ttl_str = "No expiration" if ttl in (None, -1) else f"Expires in {ttl}s"
            self.stdout.write(
                f"  {i}. {get_import_chunk_key(chunk_id)} ({ttl_str})"
            )

        if len(chunk_ids) > 10:
            self.stdout.write(f"  ... and {len(chunk_ids) - 10} more")

        # Preview data if requested
        if preview:
            self.stdout.write(
                self.style.HTTP_INFO(f"\n=== Preview of First {limit} Chunks ===\n")
            )

            for i, chunk_id in enumerate(chunk_ids[:limit], 1):
                self.stdout.write(f"\n--- Chunk {i}: {chunk_id} ---")

                try:
                    chunk_data = cache.get_chunk(chunk_id, delete_after_read=False)
                    if not chunk_data:
                        self.stdout.write(self.style.ERROR("  [FAIL] No data found"))
                        continue

                    metadata = chunk_data.get("metadata", {})
                    decisions = chunk_data.get("decisions", [])

                    self.stdout.write(f"  Decisions: {len(decisions)}")
                    self.stdout.write(f'  Chunk #: {metadata.get("chunk_index", "?")}')
                    self.stdout.write(f'  Job ID: {metadata.get("job_id", "?")}')
                    self.stdout.write(f'  Date: {metadata.get("target_date", "?")}')

                    if decisions:
                        sample_ids = [
                            d.get("ada") for d in decisions[:3] if d.get("ada")
                        ]
                        self.stdout.write(f'  Sample ADA IDs: {", ".join(sample_ids)}')

                except json.JSONDecodeError:
                    self.stdout.write(self.style.ERROR("  [FAIL] Invalid JSON data"))
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  [FAIL] Error reading chunk: {str(e)}")
                    )

        # Associated import jobs
        self.stdout.write(self.style.HTTP_INFO("\n=== Associated Import Jobs ===\n"))

        for job in jobs:
            self.stdout.write(f"\nJob #{job.id}:")
            self.stdout.write(f"  Status: {job.status}")
            self.stdout.write(f"  Total chunks: {job.total_chunks}")
            self.stdout.write(f"  Completed: {job.chunks_completed}")
            self.stdout.write(f"  Failed: {job.chunks_failed}")
            self.stdout.write(
                f"  Missing: {job.total_chunks - job.chunks_completed - job.chunks_failed}"
            )

            if job.total_chunks > 0:
                job_chunks = cache.list_job_chunk_ids(job.id)
                self.stdout.write(f"  Chunks in Redis: {len(job_chunks)}")

                missing = job.total_chunks - job.chunks_completed - job.chunks_failed
                if len(job_chunks) == missing:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "  [OK] Redis matches missing chunks - SAFE TO RETRY"
                        )
                    )
                elif job_chunks:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  [WARN]  Redis has {len(job_chunks)} chunks, expected {missing}"
                        )
                    )

        # Final recommendations
        self.stdout.write(self.style.SUCCESS("\n=== Recommendations ===\n"))

        if chunk_ids:
            self.stdout.write("[OK] Chunks are present in Redis")
            self.stdout.write("[OK] Safe to retry processing with:")
            self.stdout.write(
                self.style.SQL_FIELD(
                    f'\n  python manage.py retry_import_chunks {jobs[0].id} --all-missing\n'
                )
            )
        else:
            self.stdout.write(
                "[WARN]  No chunks in Redis - may need to re-fetch from API"
            )
