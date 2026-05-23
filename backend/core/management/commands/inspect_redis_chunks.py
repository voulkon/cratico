"""
Management command to inspect Redis chunks for a specific date

Usage:
    # Check chunks for May 13, 2026
    python manage.py inspect_redis_chunks 2026-05-13

    # Check with sample data preview
    python manage.py inspect_redis_chunks 2026-05-13 --preview
"""

import json

from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django.core.management.base import BaseCommand
from django_redis import get_redis_connection


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

        redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)
        pattern = f"decision_chunk:{date_str}_*"

        self.stdout.write(
            self.style.SUCCESS(f"\n=== Redis Chunk Inspection for {date_str} ===\n")
        )
        self.stdout.write(f"Scanning pattern: {pattern}")
        self.stdout.write(f"Redis DB: {IMPORT_CHUNKS_REDIS_DB_NAME}\n")

        # Collect all matching keys
        chunk_keys = []
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            chunk_keys.append(key_str)

        self.stdout.write(
            self.style.SUCCESS(f"[OK] Found {len(chunk_keys)} chunks in Redis\n")
        )

        if len(chunk_keys) == 0:
            self.stdout.write(
                self.style.WARNING(
                    "No chunks found. They may have been processed or never created."
                )
            )
            return

        # Show statistics
        total_size = 0
        for key in chunk_keys:
            memory_usage = redis_client.memory_usage(key)
            if memory_usage:
                total_size += memory_usage

        self.stdout.write(f"Total memory usage: {total_size / 1024 / 1024:.2f} MB")
        self.stdout.write(
            f"Average per chunk: {total_size / len(chunk_keys) / 1024:.2f} KB\n"
        )

        # Show sample keys
        self.stdout.write(self.style.HTTP_INFO("Sample chunk keys:"))
        for i, key in enumerate(chunk_keys[:10], 1):
            ttl = redis_client.ttl(key)
            ttl_str = "No expiration" if ttl == -1 else f"Expires in {ttl}s"
            self.stdout.write(f"  {i}. {key} ({ttl_str})")

        if len(chunk_keys) > 10:
            self.stdout.write(f"  ... and {len(chunk_keys) - 10} more")

        # Preview data if requested
        if preview:
            self.stdout.write(
                self.style.HTTP_INFO(f"\n=== Preview of First {limit} Chunks ===\n")
            )

            for i, key in enumerate(chunk_keys[:limit], 1):
                self.stdout.write(f"\n--- Chunk {i}: {key} ---")

                try:
                    # Get the chunk data
                    data = redis_client.get(key)
                    if not data:
                        self.stdout.write(self.style.ERROR("  [FAIL] No data found"))
                        continue

                    # Deserialize
                    chunk_data = json.loads(data)

                    # Show metadata
                    metadata = chunk_data.get("metadata", {})
                    decisions = chunk_data.get("decisions", [])

                    self.stdout.write(f"  Decisions: {len(decisions)}")
                    self.stdout.write(f'  Chunk #: {metadata.get("chunk_index", "?")}')
                    self.stdout.write(f'  Job ID: {metadata.get("import_job_id", "?")}')
                    self.stdout.write(f'  Date: {metadata.get("target_date", "?")}')

                    # Show sample decision IDs
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

        # Check for associated import job
        self.stdout.write(self.style.HTTP_INFO("\n=== Associated Import Jobs ===\n"))

        from datetime import datetime

        from core.models.import_jobs import ImportJob

        target_date = datetime.fromisoformat(date_str).date()
        jobs = ImportJob.objects.filter(start_date=target_date).order_by("-created_at")

        if jobs:
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
                    chunks_in_redis = len(chunk_keys)
                    self.stdout.write(f"  Chunks in Redis: {chunks_in_redis}")

                    if (
                        chunks_in_redis
                        == job.total_chunks - job.chunks_completed - job.chunks_failed
                    ):
                        self.stdout.write(
                            self.style.SUCCESS(
                                "  [OK] Redis matches missing chunks - SAFE TO RETRY"
                            )
                        )
                    elif chunks_in_redis > 0:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  [WARN]️  Redis has {chunks_in_redis} chunks, expected {job.total_chunks - job.chunks_completed - job.chunks_failed}"
                            )
                        )
        else:
            self.stdout.write(
                self.style.WARNING(f"No import jobs found for {target_date}")
            )

        # Final recommendations
        self.stdout.write(self.style.SUCCESS("\n=== Recommendations ===\n"))

        if len(chunk_keys) > 0:
            self.stdout.write("[OK] Chunks are present in Redis")
            self.stdout.write("[OK] Safe to retry processing with:")
            self.stdout.write(
                self.style.SQL_FIELD(
                    f'\n  python manage.py retry_import_chunks {jobs.first().id if jobs else "JOB_ID"} --all-missing\n'
                )
            )
        else:
            self.stdout.write(
                "[WARN]️  No chunks in Redis - may need to re-fetch from API"
            )
