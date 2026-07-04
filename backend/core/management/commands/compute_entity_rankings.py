"""
Management command to trigger entity rankings computation ad hoc.

Usage:
    # Compute entity rankings for today (default reference date)
    python manage.py compute_entity_rankings

    # Compute entity rankings for a specific reference date
    python manage.py compute_entity_rankings --date 2026-06-05

    # Dispatch as background Celery task (non-blocking)
    python manage.py compute_entity_rankings --async

    # Dispatch for a specific date, non-blocking
    python manage.py compute_entity_rankings --date 2026-06-05 --async
"""

from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = (
        "Trigger entity rankings computation "
        "(compute_entity_rankings Celery task). "
        "Computes per-entity statistics (total_amount, decision_count, "
        "rank_by_amount, rank_by_frequency, etc.) across "
        "daily/weekly/monthly/yearly windows and stores results in "
        "AnalyticsSnapshotRun + EntityAnalyticsSnapshot models."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Reference date in ISO format (YYYY-MM-DD). Defaults to today.",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="async_mode",
            help="Dispatch as a background Celery task instead of running synchronously.",
        )

    def handle(self, *args, **options):
        from core.tasks.tasks_post_import import compute_entity_rankings

        reference_date_str = options["date"]
        async_mode = options["async_mode"]

        if async_mode:
            task = compute_entity_rankings.delay(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Entity rankings dispatched as background task.\n"
                    f"  Task ID: {task.id}\n"
                    f"  Reference date: {reference_date_str or 'today'}"
                )
            )
            logger.info(
                f"[compute_entity_rankings cmd] Dispatched async task "
                f"{task.id} (date={reference_date_str or 'today'})"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Running entity rankings synchronously (blocking)...\n"
                    "Use --async to dispatch as a background task."
                )
            )
            result = compute_entity_rankings(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Entity rankings completed.\n"
                    f"  Status: {result.get('status')}\n"
                    f"  Reference date: {result.get('reference_date')}\n"
                    f"  Windows processed: {result.get('windows_processed')}"
                )
            )
