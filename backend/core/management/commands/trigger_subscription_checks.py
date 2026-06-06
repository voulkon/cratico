"""
Management command to trigger subscription checks ad hoc.

Usage:
    # Check subscriptions against yesterday's data (default)
    python manage.py trigger_subscription_checks

    # Check subscriptions against a specific reference date
    python manage.py trigger_subscription_checks --date 2026-06-05

    # Dispatch as background Celery task (non-blocking)
    python manage.py trigger_subscription_checks --async

    # Dispatch for a specific date, non-blocking
    python manage.py trigger_subscription_checks --date 2026-06-05 --async
"""

from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = (
        "Trigger subscription notification checks "
        "(trigger_check_all_subscriptions Celery task). "
        "Fans out to check_all_active_subscriptions, which checks each "
        "active 'daily'/'weekly' subscription against yesterday's new decisions."
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
        from core.tasks.tasks_post_import import trigger_check_all_subscriptions

        reference_date_str = options["date"]
        async_mode = options["async_mode"]

        if async_mode:
            # Dispatch as background Celery task
            task = trigger_check_all_subscriptions.delay(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Subscription checks dispatched as background task.\n"
                    f"  Task ID: {task.id}\n"
                    f"  Reference date: {reference_date_str or 'today'}"
                )
            )
            logger.info(
                f"[trigger_subscription_checks cmd] Dispatched async task "
                f"{task.id} (date={reference_date_str or 'today'})"
            )
        else:
            # Run synchronously (blocking) — useful for debugging
            self.stdout.write(
                self.style.WARNING(
                    "Running subscription checks synchronously (blocking)...\n"
                    "Use --async to dispatch as a background task."
                )
            )
            result = trigger_check_all_subscriptions(
                reference_date_str=reference_date_str
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Subscription checks completed.\n"
                    f"  Status: {result.get('status')}\n"
                    f"  Reference date: {result.get('reference_date')}\n"
                    f"  Task ID: {result.get('task_id')}"
                )
            )
