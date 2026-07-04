"""
Management command to trigger analytics cache warming ad hoc.

Usage:
    # Warm cache for today (default reference date)
    python manage.py warm_analytics_cache

    # Warm cache for a specific reference date
    python manage.py warm_analytics_cache --date 2026-06-05

    # Dispatch as background Celery task (non-blocking)
    python manage.py warm_analytics_cache --async

    # Dispatch for a specific date, non-blocking
    python manage.py warm_analytics_cache --date 2026-06-05 --async
"""

from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = (
        "Trigger analytics cache warming (warm_analytics_cache Celery task). "
        "Pre-populates Redis cache for explore_orgs and da_top_pairs views "
        "across daily/weekly/monthly/yearly time windows."
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
        from core.tasks.tasks_post_import import warm_analytics_cache

        reference_date_str = options["date"]
        async_mode = options["async_mode"]

        if async_mode:
            # Dispatch as background Celery task
            task = warm_analytics_cache.delay(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Warmup dispatched as background task.\n"
                    f"  Task ID: {task.id}\n"
                    f"  Reference date: {reference_date_str or 'today'}"
                )
            )
            logger.info(
                f"[warm_analytics_cache cmd] Dispatched async task {task.id} "
                f"(date={reference_date_str or 'today'})"
            )
        else:
            # Run synchronously (blocking) — useful for debugging
            self.stdout.write(
                self.style.WARNING(
                    "Running warmup synchronously (blocking)...\n"
                    "Use --async to dispatch as a background task."
                )
            )
            result = warm_analytics_cache(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Warmup completed.\n"
                    f"  Status: {result.get('status')}\n"
                    f"  Reference date: {result.get('reference_date')}\n"
                    f"  Windows warmed: {result.get('windows_warmed')}\n"
                    f"  Keys warmed: {result.get('keys_warmed')}\n"
                    f"  Errors: {len(result.get('errors', []))}"
                )
            )
            if result.get("errors"):
                for err in result["errors"]:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [{err['window']}] {err['view']}: {err['error']}"
                        )
                    )
