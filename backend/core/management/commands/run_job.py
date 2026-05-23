"""
Management command to execute AI jobs.

Usage:
    # Run daily_summary for today (dry run first)
    python manage.py run_job daily_summary --provider AWS_BEDROCK --model anthropic.claude-3-haiku-20240307-v1:0 --dry-run

    # Actually execute
    python manage.py run_job daily_summary --provider AWS_BEDROCK --model anthropic.claude-3-haiku-20240307-v1:0

    # Run with filters
    python manage.py run_job high_value_analysis --min-amount 100000 --start-date 2025-01-01 --limit 50

    # Run in background (via Celery)
    python manage.py run_job daily_summary --async
"""

from datetime import datetime

from core.jobs.base import load_job_class
from core.models.ai_pricing import AIJobDefinition
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Execute AI jobs"

    def add_arguments(self, parser):
        parser.add_argument("job_name", type=str, help="Job name to execute")

        parser.add_argument(
            "--provider", type=str, help="AI provider (defaults to job default)"
        )
        parser.add_argument(
            "--model", type=str, help="Model name (defaults to job default)"
        )

        # Execution mode
        parser.add_argument(
            "--dry-run", action="store_true", help="Estimate only, do not call AI"
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="async_mode",
            help="Run via Celery (background)",
        )

        # Common filters
        parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
        parser.add_argument(
            "--limit", type=int, help="Limit number of items to process"
        )

        # Job-specific kwargs
        parser.add_argument(
            "--target-date", type=str, help="Target date for daily_summary (YYYY-MM-DD)"
        )
        parser.add_argument(
            "--min-amount", type=float, help="Minimum amount for high_value_analysis"
        )
        parser.add_argument(
            "--decision-types", type=str, help="Comma-separated decision type UIDs"
        )
        parser.add_argument(
            "--organization-ids", type=str, help="Comma-separated organization UIDs"
        )

        # Output
        parser.add_argument(
            "--verbose", action="store_true", help="Show per-item progress"
        )

    def handle(self, *args, **options):
        job_name = options["job_name"]
        dry_run = options.get("dry_run", False)
        async_mode = options.get("async_mode", False)
        options.get("verbose", False)

        # Load job definition
        try:
            job_def = AIJobDefinition.objects.get(job_name=job_name, is_active=True)
        except AIJobDefinition.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Job "{job_name}" not found or not active')
            )
            return

        # Get provider and model
        provider = options.get("provider") or job_def.default_provider
        model = options.get("model") or job_def.default_model

        if not provider or not model:
            self.stdout.write(self.style.ERROR("Provider and model must be specified"))
            return

        # Build kwargs for job
        job_kwargs = {}

        # Parse dates
        if options.get("start_date"):
            job_kwargs["start_date"] = datetime.strptime(
                options["start_date"], "%Y-%m-%d"
            ).date()
        if options.get("end_date"):
            job_kwargs["end_date"] = datetime.strptime(
                options["end_date"], "%Y-%m-%d"
            ).date()
        if options.get("target_date"):
            job_kwargs["target_date"] = datetime.strptime(
                options["target_date"], "%Y-%m-%d"
            ).date()

        # Other filters
        if options.get("min_amount"):
            job_kwargs["min_amount"] = options["min_amount"]
        if options.get("decision_types"):
            job_kwargs["decision_types"] = [
                t.strip() for t in options["decision_types"].split(",")
            ]
        if options.get("organization_ids"):
            job_kwargs["organization_ids"] = [
                o.strip() for o in options["organization_ids"].split(",")
            ]
        if options.get("limit"):
            job_kwargs["limit"] = options["limit"]

        # Header
        self.stdout.write(f'\n{"="*80}')
        mode_str = "DRY RUN" if dry_run else "EXECUTION"
        async_str = " (ASYNC)" if async_mode else ""
        self.stdout.write(
            self.style.SUCCESS(f"{mode_str}: {job_def.display_name}{async_str}")
        )
        self.stdout.write(f'{"="*80}\n')

        self.stdout.write(f"Provider: {provider}")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Analysis Type: {job_def.analysis_type}")

        if job_kwargs:
            self.stdout.write("\nFilters:")
            for key, value in job_kwargs.items():
                self.stdout.write(f"  {key}: {value}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n[WARN] DRY RUN MODE - No actual AI calls will be made"
                )
            )

        # If async mode, use Celery
        if async_mode:
            try:
                from core.jobs.tasks import execute_job_by_name

                self.stdout.write(f'\n{"-"*80}')
                self.stdout.write("Queuing job for background execution...\n")

                task = execute_job_by_name.delay(
                    job_name=job_name,
                    provider=provider,
                    model=model,
                    dry_run=dry_run,
                    **job_kwargs,
                )

                self.stdout.write(self.style.SUCCESS("[OK] Job queued!"))
                self.stdout.write(f"Task ID: {task.id}")
                self.stdout.write("\nCheck status with:")
                self.stdout.write("  python manage.py shell")
                self.stdout.write("  >>> from celery.result import AsyncResult")
                self.stdout.write(f'  >>> result = AsyncResult("{task.id}")')
                self.stdout.write("  >>> result.status")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Failed to queue job: {e}"))
                import traceback

                traceback.print_exc()

            return

        # Synchronous execution
        try:
            job_class = load_job_class(job_def)
            job = job_class(job_def)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nFailed to load job: {e}"))
            return

        self.stdout.write(f'\n{"-"*80}')
        self.stdout.write("Starting execution...\n")

        try:
            # Execute the job
            execution = job.execute(
                provider=provider, model=model, dry_run=dry_run, **job_kwargs
            )

            # Show results
            self.stdout.write(f'\n{"="*80}')
            self.stdout.write(self.style.SUCCESS("EXECUTION COMPLETE"))
            self.stdout.write(f'{"="*80}\n')

            self.stdout.write(f"Execution ID: {execution.execution_id}")
            self.stdout.write(f"Status: {execution.status}")
            self.stdout.write(f"Items processed: {execution.items_processed}")
            self.stdout.write(f"Items succeeded: {execution.items_succeeded}")
            self.stdout.write(f"Items failed: {execution.items_failed}")

            if dry_run:
                self.stdout.write(
                    f"\nEstimated cost: ${float(execution.estimated_cost_usd):.4f}"
                )
            else:
                self.stdout.write(
                    f"\nEstimated cost: ${float(execution.estimated_cost_usd):.4f}"
                )
                self.stdout.write(
                    f"Actual cost: ${float(execution.actual_cost_usd or 0):.4f}"
                )

                if execution.actual_cost_usd and execution.estimated_cost_usd:
                    variance = execution.cost_variance_percentage
                    if variance is not None:
                        variance_str = f"{variance:+.1f}%"
                        if abs(variance) < 10:
                            style = self.style.SUCCESS
                        elif abs(variance) < 25:
                            style = self.style.WARNING
                        else:
                            style = self.style.ERROR
                        self.stdout.write(f"Cost variance: {style(variance_str)}")

            # Show errors if any
            if execution.items_failed > 0:
                self.stdout.write(f'\n{"-"*80}')
                self.stdout.write(self.style.ERROR("Failed items:\n"))

                failed_items = execution.items.filter(status="FAILED")[:10]
                for item in failed_items:
                    self.stdout.write(
                        f"  • {item.item_identifier}: {item.error_message}"
                    )

                if execution.items_failed > 10:
                    self.stdout.write(f"\n  ... and {execution.items_failed - 10} more")

            # View in admin
            self.stdout.write(f'\n{"-"*80}')
            self.stdout.write("View details in admin:")
            self.stdout.write(
                f"  /api/admin/core/aijobexecution/{execution.id}/change/"
            )
            self.stdout.write(f'\n{"="*80}\n')

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nExecution failed: {e}"))
            import traceback

            traceback.print_exc()
