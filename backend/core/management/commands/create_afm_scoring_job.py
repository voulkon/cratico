"""
Management command to create and launch AFM scoring jobs.

This provides a simple CLI interface for creating scoring jobs
without needing to use the admin interface.
"""

import uuid

from core.models.afm_scoring import AFMScoringConfig
from core.models.afm_scoring_job import AFMScoringJob
from core.tasks.afm_scoring_tasks import start_afm_scoring_job
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

User = get_user_model()


class Command(BaseCommand):
    help = """
    Create and launch an AFM scoring batch job.

    This command creates an AFMScoringJob record and queues it for processing.
    You can monitor progress in the admin interface.

    Examples:

    # 1. Score all entities with active config
    python manage.py create_afm_scoring_job

    # 2. Score with specific config
    python manage.py create_afm_scoring_job --config-id 1

    # 3. Exclude already fetched entities
    python manage.py create_afm_scoring_job --exclude-fetched

    # 4. Create job but don't start it (for testing)
    python manage.py create_afm_scoring_job --no-start
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--config-id",
            type=int,
            help="Scoring config ID to use (default: active config)",
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for processing (default: 1000)",
        )

        parser.add_argument(
            "--exclude-fetched",
            action="store_true",
            help="Exclude entities with successful GEMI data",
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

        # Get config
        if options["config_id"]:
            try:
                config = AFMScoringConfig.objects.get(id=options["config_id"])
            except AFMScoringConfig.DoesNotExist:
                raise CommandError(f"Config ID {options['config_id']} not found")
        else:
            config = AFMScoringConfig.get_active()
            if not config:
                raise CommandError(
                    "No active scoring configuration found. "
                    "Create one in admin or specify --config-id"
                )

        # Create job
        job = AFMScoringJob.objects.create(
            job_id=str(uuid.uuid4()),
            created_by=user,
            config=config,
            batch_size=options["batch_size"],
            exclude_already_fetched=options["exclude_fetched"],
        )

        self.stdout.write(self.style.SUCCESS(f"Created AFM scoring job: {job.job_id}"))
        self.stdout.write(f"Configuration: {config.name}")
        self.stdout.write(f"Batch size: {job.batch_size}")

        # Start job unless --no-start
        if not options["no_start"]:
            task = start_afm_scoring_job.delay(job_id=job.job_id)
            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])

            self.stdout.write(self.style.SUCCESS(f"Job queued with task ID: {task.id}"))
            self.stdout.write(f"\nMonitor progress in the admin interface.")
        else:
            self.stdout.write(
                self.style.WARNING("Job created but not started (--no-start)")
            )
            self.stdout.write(
                f"Start manually with: python manage.py shell\n"
                f">>> from core.models.afm_scoring_job import AFMScoringJob\n"
                f">>> from core.tasks.afm_scoring_tasks import start_afm_scoring_job\n"
                f">>> job = AFMScoringJob.objects.get(job_id='{job.job_id}')\n"
                f">>> start_afm_scoring_job.delay(job_id=job.job_id)"
            )
