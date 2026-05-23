"""
Management command to create and launch classification jobs.

This provides a simple CLI interface for creating classification jobs
without needing to use the admin interface.
"""

import uuid

from core.models.classification_job import ClassificationJob
from core.tasks.classification_tasks import start_batch_classification_job
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = """
    Create and launch a classification batch job.

    This command creates a ClassificationJob record and queues it for processing.
    You can monitor progress in the admin interface at:
    /api/admin/classification/dashboard/

    Examples:

    # 1. Classify all unclassified decisions
    python manage.py create_classification_job --mode unclassified

    # 2. Classify decisions from a specific date range
    python manage.py create_classification_job --mode date_range --start-date 2025-01-01 --end-date 2025-01-31

    # 3. Re-classify with updated algorithm
    python manage.py create_classification_job --mode outdated --batch-size 500

    # 4. Create job but don't start it (for testing)
    python manage.py create_classification_job --mode unclassified --no-start
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            choices=["unclassified", "date_range", "reclassify", "outdated", "all"],
            default="unclassified",
            help="Processing mode (default: unclassified)",
        )

        parser.add_argument(
            "--start-date", type=str, help="Start date for date_range mode (YYYY-MM-DD)"
        )

        parser.add_argument(
            "--end-date", type=str, help="End date for date_range mode (YYYY-MM-DD)"
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for processing (default: 1000)",
        )

        parser.add_argument(
            "--reclassify",
            action="store_true",
            help="Re-classify even if already classified",
        )

        parser.add_argument(
            "--no-start", action="store_true", help="Create job but do not start it"
        )

        parser.add_argument(
            "--user",
            type=str,
            help="Username to associate with the job (default: first superuser)",
        )

    def handle(self, *args, **options):
        # Get user
        if options["user"]:
            try:
                user = User.objects.get(username=options["user"])
            except User.DoesNotExist:
                raise CommandError(f"User '{options['user']}' not found")
        else:
            # Get first superuser
            user = User.objects.filter(is_superuser=True).first()
            if not user:
                raise CommandError("No superuser found. Create a superuser first.")

        # Validate date range
        if options["mode"] == "date_range":
            if not options["start_date"] and not options["end_date"]:
                raise CommandError(
                    "date_range mode requires --start-date and/or --end-date"
                )

        # Create job
        job = ClassificationJob.objects.create(
            job_id=str(uuid.uuid4()),
            created_by=user,
            processing_mode=options["mode"],
            batch_size=options["batch_size"],
            reclassify=options["reclassify"],
        )

        # Set dates if provided
        if options["start_date"]:
            from django.utils.dateparse import parse_date

            job.start_date = parse_date(options["start_date"])

        if options["end_date"]:
            from django.utils.dateparse import parse_date

            job.end_date = parse_date(options["end_date"])

        job.save()

        self.stdout.write(
            self.style.SUCCESS(f"[OK] Created classification job: {job.job_id}")
        )

        # Start job unless --no-start
        if not options["no_start"]:
            task = start_batch_classification_job.delay(job_id=job.job_id)
            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])

            self.stdout.write(
                self.style.SUCCESS(f"[OK] Job queued with task ID: {task.id}")
            )
            self.stdout.write(
                f"\nMonitor progress at: /api/admin/classification/dashboard/"
            )
        else:
            self.stdout.write(
                self.style.WARNING("Job created but not started (--no-start)")
            )
            self.stdout.write(
                f"Start manually in admin or with: python manage.py shell\n"
                f">>> from core.models.classification_job import ClassificationJob\n"
                f">>> from core.tasks.classification_tasks import start_batch_classification_job\n"
                f">>> job = ClassificationJob.objects.get(job_id='{job.job_id}')\n"
                f">>> start_batch_classification_job.delay(job_id=job.job_id)"
            )
