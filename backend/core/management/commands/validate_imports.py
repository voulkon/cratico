"""
Management command to validate and backfill historical decision imports.

This command checks historical imports for completeness and triggers re-imports
for days that don't meet minimum decision count thresholds.

Usage:
    # Analyze and backfill last 90 days (dry run first)
    python manage.py validate_imports --days 90 --dry-run

    # Actually perform the backfill
    python manage.py validate_imports --days 90

    # Check specific date range
    python manage.py validate_imports --start-date 2025-12-01 --end-date 2026-01-25

    # Force re-import even for complete days
    python manage.py validate_imports --days 30 --force
"""

from datetime import date, datetime

from core.models.import_thresholds import ImportThreshold
from core.tasks.tasks_import_validation import validate_and_backfill_imports
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "Validate historical imports and trigger backfills for incomplete days"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="Start date for validation (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="End date for validation (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=60,
            help="Number of days to check backward from end-date (default: 60)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only report issues without triggering imports",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-import even for days that meet thresholds",
        )
        parser.add_argument(
            "--chunk-size",
            type=int,
            default=10,
            help="Chunk size for distributed imports (default: 10)",
        )
        parser.add_argument(
            "--max-reimports",
            type=int,
            help="Maximum number of re-imports to dispatch (default: unlimited)",
        )
        parser.add_argument(
            "--async",
            dest="use_async",
            action="store_true",
            help="Run validation as async Celery task (default: synchronous)",
        )

    def handle(self, *args, **options):
        start_date = options.get("start_date")
        end_date = options.get("end_date") or date.today()
        days_back = options.get("days")
        dry_run = options.get("dry_run")
        force = options.get("force")
        chunk_size = options.get("chunk_size")
        max_reimports = options.get("max_reimports")
        use_async = options.get("use_async")

        # Display current thresholds
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("[SCAN] Import Validation & Backfill")
        self.stdout.write(f"{'='*80}\n")

        # Show configuration status
        try:
            config = ImportThreshold.get_instance()
            status_color = self.style.SUCCESS if config.enabled else self.style.ERROR
            status_text = "ENABLED [OK]" if config.enabled else "DISABLED [STOP]"

            self.stdout.write(f"Validation System: {status_color(status_text)}")
            self.stdout.write("\nCurrent Decision Count Thresholds:")
            self.stdout.write(
                f"  Weekdays (Mon-Fri): {config.weekday_threshold:,} decisions"
            )
            self.stdout.write(
                f"  Saturday:           {config.saturday_threshold:,} decisions"
            )
            self.stdout.write(
                f"  Sunday:             {config.sunday_threshold:,} decisions"
            )

            if not config.enabled:
                self.stdout.write(
                    self.style.WARNING(
                        "\n[WARN]️  Note: System is disabled, but manual command will still run."
                    )
                )
        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Could not load configuration: {e}"))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\n[WARN]️  DRY RUN MODE - No imports will be triggered"
                )
            )

        if force:
            self.stdout.write(
                self.style.WARNING(
                    "[WARN]️  FORCE MODE - Will re-import even complete days"
                )
            )

        if max_reimports:
            self.stdout.write(
                self.style.WARNING(
                    f"[WARN]️  LIMIT MODE - Maximum {max_reimports} re-imports will be dispatched"
                )
            )

        self.stdout.write("")

        # Build parameters
        params = {
            "start_date_str": start_date.isoformat() if start_date else None,
            "end_date_str": end_date.isoformat(),
            "days_back": days_back,
            "dry_run": dry_run,
            "force_reimport": force,
            "chunk_size": chunk_size,
            "max_reimports": max_reimports,
            "skip_enabled_check": True,  # Manual commands always run regardless of enabled flag
        }

        if use_async:
            # Dispatch as Celery task
            self.stdout.write(
                "[LAUNCH] Dispatching validation as async Celery task...\n"
            )

            task = validate_and_backfill_imports.delay(**params)

            self.stdout.write(self.style.SUCCESS(f"[OK] Task dispatched: {task.id}"))
            self.stdout.write(f"\nMonitor task with:")
            self.stdout.write(f"  celery -A diavgeia_project inspect active")
            self.stdout.write(f"  celery -A diavgeia_project result {task.id}")

        else:
            # Run synchronously
            self.stdout.write("[RETRY] Running validation synchronously...\n")

            # Import the function directly to run sync
            from core.tasks.tasks_import_validation import (
                validate_and_backfill_imports as validate_func,
            )

            try:
                # Call the bound task directly - Celery handles 'self' automatically
                result = validate_func(**params)

                # Display results
                self.stdout.write(f"\n{'='*80}")
                self.stdout.write("[CHART] Validation Results")
                self.stdout.write(f"{'='*80}\n")

                self.stdout.write(
                    f"Total days checked:      {result['total_days_checked']}"
                )
                self.stdout.write(f"Complete days:           {result['complete_days']}")
                self.stdout.write(
                    f"Incomplete days:         {result['incomplete_days']}"
                )

                if dry_run:
                    self.stdout.write(
                        f"\nRe-imports that would be dispatched: {result['incomplete_days']}"
                    )
                else:
                    self.stdout.write(
                        f"\nRe-imports dispatched:   {result['reimport_dispatched']}"
                    )
                    self.stdout.write(
                        f"Re-imports skipped:      {result['reimport_skipped']}"
                    )

                # Show incomplete days detail
                if result["incomplete_days"] > 0:
                    self.stdout.write(f"\n{'='*80}")
                    self.stdout.write("[WARN]️  Incomplete Days")
                    self.stdout.write(f"{'='*80}\n")

                    for day_result in result["details"]:
                        if not day_result["is_complete"]:
                            shortage = (
                                day_result["threshold"] - day_result["actual_count"]
                            )
                            action = day_result.get("action_taken", "unknown")

                            self.stdout.write(
                                f"{day_result['date']} ({day_result['day_name']:9s}): "
                                f"{day_result['actual_count']:6,} / {day_result['threshold']:6,} "
                                f"(short by {shortage:,}) - {action}"
                            )

                            if "reimport_task_id" in day_result:
                                self.stdout.write(
                                    f"  └─ Task: {day_result['reimport_task_id']}"
                                )

                self.stdout.write(f"\n{'='*80}")

                if dry_run and result["incomplete_days"] > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"\n[INFO] Run without --dry-run to dispatch {result['incomplete_days']} re-import tasks"
                        )
                    )
                elif result["reimport_dispatched"] > 0:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"\n[OK] Dispatched {result['reimport_dispatched']} re-import tasks"
                        )
                    )
                    self.stdout.write("\nMonitor progress in Django admin: ImportJobs")
                else:
                    self.stdout.write(
                        self.style.SUCCESS("\n[OK] All days are complete!")
                    )

                self.stdout.write("")

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"\n[ERROR] Validation failed: {str(e)}")
                )
                logger.exception("Validation command failed")
                raise
