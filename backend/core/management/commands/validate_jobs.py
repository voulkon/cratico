"""
Management command to validate all AI jobs.

Usage:
    python manage.py validate_jobs
    python manage.py validate_jobs --job daily_summary
"""

from core.jobs.base import load_job_class
from core.models.ai_pricing import AIJobDefinition
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Validate AI job implementations against BaseAIJob protocol"

    def add_arguments(self, parser):
        parser.add_argument(
            "--job",
            type=str,
            help="Specific job name to validate (validates all if omitted)",
        )

    def handle(self, *args, **options):
        job_name = options.get("job")

        if job_name:
            # Validate single job
            try:
                job_def = AIJobDefinition.objects.get(job_name=job_name, is_active=True)
                self.validate_single_job(job_def)
            except AIJobDefinition.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f'Job "{job_name}" not found or not active')
                )
                return
        else:
            # Validate all active jobs
            job_defs = AIJobDefinition.objects.filter(is_active=True)

            if not job_defs.exists():
                self.stdout.write(self.style.WARNING("No active jobs found"))
                return

            self.stdout.write(
                self.style.SUCCESS(f"Found {job_defs.count()} active jobs\n")
            )

            failed = []
            for job_def in job_defs:
                try:
                    self.validate_single_job(job_def)
                except Exception as e:
                    failed.append((job_def.job_name, str(e)))

            # Summary
            self.stdout.write("\n" + "=" * 80)
            if failed:
                self.stdout.write(
                    self.style.ERROR(f"\n{len(failed)} job(s) failed validation:\n")
                )
                for job_name, error in failed:
                    self.stdout.write(self.style.ERROR(f"  [FAIL] {job_name}: {error}"))
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n[OK] All {job_defs.count()} jobs passed validation!"
                    )
                )

    def validate_single_job(self, job_def):
        """Validate a single job definition"""
        self.stdout.write(f"\nValidating: {job_def.job_name}")
        self.stdout.write(f"  Module: {job_def.algorithm_module}")
        self.stdout.write(f"  Class: {job_def.algorithm_class}")

        # Load the job class
        try:
            job_class = load_job_class(job_def)
            self.stdout.write(self.style.SUCCESS("  [OK] Class loaded successfully"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Failed to load class: {e}"))
            raise

        # Instantiate the job
        try:
            job = job_class(job_def)
            self.stdout.write(self.style.SUCCESS("  [OK] Job instantiated"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Failed to instantiate: {e}"))
            raise

        # Run validation
        try:
            job.validate_implementation()
            self.stdout.write(self.style.SUCCESS("  [OK] Protocol validation passed"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  [FAIL] Validation failed: {e}"))
            raise

        # Check metadata
        if hasattr(job, "JOB_NAME") and job.JOB_NAME == job_def.job_name:
            self.stdout.write(
                self.style.SUCCESS(f'  [OK] JOB_NAME matches: "{job.JOB_NAME}"')
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f'  [WARN] JOB_NAME mismatch: class="{getattr(job, "JOB_NAME", "NOT SET")}" vs db="{job_def.job_name}"'
                )
            )

        self.stdout.write(self.style.SUCCESS(f"  [OK] {job_def.job_name} is valid!\n"))
