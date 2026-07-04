"""
Management command to recompute issue_date_day, issue_date_month, and
issue_date_year for all existing Decision records using the Europe/Athens
timezone.

Background
----------
Diavgeia encodes issue dates as Unix timestamps representing midnight in
Athens local time (EET = UTC+2 in winter, EEST = UTC+3 in summer).  For
example, "March 20, 2023" is stored as 2023-03-19T22:00:00Z (22:00 UTC =
00:00 Athens).

The old save() method called ``self.issue_date.date()`` which returns the
*UTC* date, so that record would get issue_date_day = 2023-03-19 instead of
the correct 2023-03-20.  This command corrects all affected rows.

Modes
-----

Sync (default)
    Runs the UPDATE in‑process, batch by batch.  Suitable for small
    datasets or when you have a stable terminal session.

Async (--async)
    Dispatches the work to a Celery task that self‑chains through
    batches.  This is the recommended mode for the 20M+ row
    production table.

After running this command you should also run::

    python manage.py backfill_date_coverage --reset

to rebuild the DateCoverage table from the corrected data.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Recompute issue_date_day / issue_date_month / issue_date_year for all "
        "Decision rows using the configured TIME_ZONE."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show how many rows would be updated without making changes.",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50_000,
            help="Number of rows to update per transaction (default: 50 000).",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="async_mode",
            help=(
                "Dispatch to Celery instead of running synchronously. "
                "The task self‑chains through batches."
            ),
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        async_mode = options["async_mode"]

        if async_mode:
            self._dispatch_async(dry_run, batch_size)
        else:
            self._run_sync(dry_run, batch_size)

    def _dispatch_async(self, dry_run: bool, batch_size: int):
        from core.tasks.tasks_data_migration import (
            recompute_issue_date_fields_task,
        )

        result = recompute_issue_date_fields_task.apply_async(
            kwargs={"dry_run": dry_run, "batch_size": batch_size},
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Task dispatched.\n"
                f"  Task ID: {result.id}\n"
                f"  dry_run: {dry_run}\n"
                f"  batch_size: {batch_size:,}\n\n"
                f"Monitor progress via Flower or:\n"
                f"  celery -A diavgeia_project inspect active"
            )
        )

    # ------------------------------------------------------------------
    # synchronous path (original behaviour)
    # ------------------------------------------------------------------

    def _run_sync(self, dry_run: bool, batch_size: int):

        with connection.cursor() as cursor:
            # Count how many rows will be affected (UTC date ≠ Athens date).
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM core_decision
                WHERE issue_date IS NOT NULL
                  AND issue_date_day IS DISTINCT FROM
                      (issue_date AT TIME ZONE %(tz)s)::date
                """,
                {"tz": settings.TIME_ZONE},
            )
            affected = cursor.fetchone()[0]

        self.stdout.write(
            f"Rows where issue_date_day differs from {settings.TIME_ZONE} date: {affected:,}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry-run — no changes written."))
            return

        if affected == 0:
            self.stdout.write(self.style.SUCCESS("Nothing to update."))
            return

        self.stdout.write(f"Updating in batches of {batch_size:,} …")

        total_updated = 0
        batch_num = 0

        while True:
            batch_num += 1
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE core_decision
                    SET
                        issue_date_day   = (issue_date AT TIME ZONE %(tz)s)::date,
                        issue_date_month = DATE_TRUNC('month',
                                               issue_date AT TIME ZONE %(tz)s
                                           )::date,
                        issue_date_year  = EXTRACT(
                                               YEAR FROM
                                               (issue_date AT TIME ZONE %(tz)s)
                                           )::integer
                    WHERE id IN (
                        SELECT id
                        FROM core_decision
                        WHERE issue_date IS NOT NULL
                          AND issue_date_day IS DISTINCT FROM
                              (issue_date AT TIME ZONE %(tz)s)::date
                        LIMIT %(batch_size)s
                    )
                    """,
                    {"tz": settings.TIME_ZONE, "batch_size": batch_size},
                )
                rows_in_batch = cursor.rowcount

            if rows_in_batch == 0:
                break

            total_updated += rows_in_batch
            self.stdout.write(
                f"  Batch {batch_num}: +{rows_in_batch:,} rows  "
                f"(total so far: {total_updated:,} / {affected:,})"
            )

        self.stdout.write(
            self.style.SUCCESS(f"Done. Updated {total_updated:,} Decision rows.")
        )
        self.stdout.write(
            "Next step: python manage.py backfill_date_coverage --reset"
        )
