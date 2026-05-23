"""
Management command to monitor and control the Import Job Queue

Usage:
    # View queue status
    python manage.py import_queue status

    # Clear stale jobs (stuck for >24 hours)
    python manage.py import_queue clear-stale

    # Remove duplicate pending jobs
    python manage.py import_queue clear-duplicates

    # Manually dispatch next pending job
    python manage.py import_queue dispatch-next

    # Set max concurrent jobs (runtime override)
    python manage.py import_queue set-limit 2
"""

from datetime import timedelta

from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Monitor and control the Import Job Queue"

    def add_arguments(self, parser):
        parser.add_argument(
            "action",
            type=str,
            choices=[
                "status",
                "clear-stale",
                "clear-duplicates",
                "dispatch-next",
                "set-limit",
            ],
            help="Action to perform",
        )
        parser.add_argument(
            "--max-age-hours",
            type=int,
            default=24,
            help="Max age in hours for stale jobs (default: 24)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="New max concurrent jobs limit (for set-limit action)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting (for clear-duplicates)",
        )

    def handle(self, *args, **options):
        action = options["action"]
        queue = ImportJobQueue()

        if action == "status":
            self.show_status(queue)

        elif action == "clear-stale":
            self.clear_stale(queue, options["max_age_hours"])

        elif action == "clear-duplicates":
            self.clear_duplicates(options.get("dry_run", False))

        elif action == "dispatch-next":
            self.dispatch_next(queue)

        elif action == "set-limit":
            if not options["limit"]:
                self.stdout.write(
                    self.style.ERROR("Error: --limit is required for set-limit action")
                )
                return
            self.set_limit(options["limit"])

    def show_status(self, queue: ImportJobQueue):
        """Display current queue status"""
        status = queue.get_queue_status()

        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("Import Job Queue Status")
        self.stdout.write("=" * 60)

        self.stdout.write(f"\nMax Concurrent Jobs: {status['max_concurrent']}")
        self.stdout.write(f"Active Jobs: {status['active_count']}")
        self.stdout.write(f"Pending Jobs: {status['pending_count']}")
        self.stdout.write(f"Can Start New: {status['can_start_new']}")

        # Check for stale jobs (stuck for >6 hours)
        stale_cutoff = timezone.now() - timedelta(hours=6)
        stale_jobs = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ],
            created_at__lt=stale_cutoff,
        )

        stale_count = stale_jobs.count()
        if stale_count > 0:
            self.stdout.write("\n" + "!" * 60)
            self.stdout.write(
                self.style.WARNING(
                    f"[WARN]️  WARNING: {stale_count} jobs stuck for >6 hours detected!"
                )
            )
            self.stdout.write(
                self.style.WARNING(f"These jobs are blocking the queue. Run:")
            )
            self.stdout.write(
                self.style.WARNING(
                    f"  python manage.py import_queue clear-stale --max-age-hours 1"
                )
            )
            self.stdout.write("!" * 60)

        if status["active_jobs"]:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("Active Jobs:")
            self.stdout.write("-" * 60)
            for job in status["active_jobs"]:
                # Calculate age
                age = timezone.now() - job["created_at"]
                age_hours = age.total_seconds() / 3600

                # Mark stale jobs
                stale_marker = " [WARN]️ STALE!" if age_hours > 6 else ""

                self.stdout.write(
                    f"  #{job['id']} | {job['start_date']} | {job['status']} | "
                    f"Created: {job['created_at']} ({age_hours:.1f}h ago){stale_marker}"
                )

        if status["pending_jobs"]:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("Pending Jobs (Queue):")
            self.stdout.write("-" * 60)
            for job in status["pending_jobs"]:
                self.stdout.write(
                    f"  #{job['id']} | {job['start_date']} | "
                    f"Created: {job['created_at']}"
                )

        # Show recent completed jobs
        recent_completed = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.COMPLETED,
                ImportJobStatus.PARTIALLY_COMPLETED,
                ImportJobStatus.FAILED,
            ]
        ).order_by("-completed_at")[:5]

        if recent_completed:
            self.stdout.write("\n" + "-" * 60)
            self.stdout.write("Recent Completed Jobs:")
            self.stdout.write("-" * 60)
            for job in recent_completed:
                self.stdout.write(
                    f"  #{job.id} | {job.start_date} | {job.status} | "
                    f"Decisions: {job.total_decisions} | "
                    f"Completed: {job.completed_at}"
                )

        self.stdout.write("\n" + "=" * 60 + "\n")

    def clear_stale(self, queue: ImportJobQueue, max_age_hours: int):
        """Clear stale jobs that are stuck"""
        self.stdout.write(f"\nClearing jobs stuck for >{max_age_hours} hours...")

        count = queue.clear_stale_jobs(max_age_hours)

        if count > 0:
            self.stdout.write(
                self.style.SUCCESS(f"\n[OK] Marked {count} stale jobs as failed")
            )
        else:
            self.stdout.write("\n[OK] No stale jobs found")

        # Try to dispatch next job after clearing
        dispatched = queue.dispatch_next_job()
        if dispatched:
            self.stdout.write(
                self.style.SUCCESS(f"\n[OK] Auto-dispatched next job #{dispatched.id}")
            )

    def clear_duplicates(self, dry_run: bool = False):
        """Remove duplicate pending jobs, keeping only the oldest"""
        self.stdout.write("\n[SCAN] Searching for duplicate jobs...")

        # Find duplicates: same date + filters, pending or active status
        duplicates_found = []
        deleted_count = 0

        # Group jobs by (start_date, end_date, org, unit, signer)

        pending_and_active = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.PENDING,
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ]
        ).order_by("start_date", "organization", "unit", "signer", "created_at")

        # Track unique combinations and their first job
        seen = {}

        for job in pending_and_active:
            # Create a unique key for this job's parameters
            key = (
                job.start_date,
                job.end_date,
                job.organization_id,
                job.unit_id,
                job.signer_id,
            )

            if key not in seen:
                # First time seeing this combination - keep it
                seen[key] = job
            else:
                # Duplicate! Mark for deletion (keep the older job)
                original_job = seen[key]
                duplicates_found.append(
                    {
                        "duplicate_id": job.id,
                        "original_id": original_job.id,
                        "date": job.start_date,
                        "org": job.organization_id,
                        "status": job.status,
                    }
                )

                if not dry_run:
                    job.delete()
                    deleted_count += 1

        # Show results
        if duplicates_found:
            self.stdout.write(
                f"\n[CHART] Found {len(duplicates_found)} duplicate job(s):\n"
            )

            for dup in duplicates_found[:10]:  # Show first 10
                self.stdout.write(
                    f"   Duplicate #{dup['duplicate_id']} (date: {dup['date']}, "
                    f"status: {dup['status']}) → Keeping original #{dup['original_id']}"
                )

            if len(duplicates_found) > 10:
                self.stdout.write(f"   ... and {len(duplicates_found) - 10} more")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[WARN]️  DRY RUN: Would delete {len(duplicates_found)} duplicate jobs"
                    )
                )
                self.stdout.write(
                    self.style.WARNING("Run without --dry-run to actually delete them")
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(f"\n[OK] Deleted {deleted_count} duplicate jobs")
                )
        else:
            self.stdout.write("\n[OK] No duplicate jobs found")

        self.stdout.write("")

    def dispatch_next(self, queue: ImportJobQueue):
        """Manually dispatch next pending job"""
        self.stdout.write("\nDispatching next pending job...")

        job = queue.dispatch_next_job()

        if job:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[OK] Dispatched Job #{job.id} for {job.start_date}\n"
                    f"  Task ID: {job.celery_task_id}"
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "\n[WARN] No job dispatched (at capacity or no pending jobs)"
                )
            )

    def set_limit(self, limit: int):
        """Set max concurrent jobs (runtime override)"""
        from django.conf import settings

        old_limit = settings.IMPORT_MAX_CONCURRENT_JOBS
        settings.IMPORT_MAX_CONCURRENT_JOBS = limit

        self.stdout.write(
            self.style.SUCCESS(
                f"\n[OK] Updated max concurrent jobs: {old_limit} → {limit}\n"
                f"  Note: This is a runtime override. Set IMPORT_MAX_CONCURRENT_JOBS "
                f"environment variable for persistent change."
            )
        )
