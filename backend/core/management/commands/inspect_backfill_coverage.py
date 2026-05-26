"""
Inspect how the backfill algorithm classifies days in a date range.

For each day the command prints whether it would be considered done
(and why) or under-imported (and why), using the same two-tier logic
that find_next_oldest_missing_day uses:

  1. PRIMARY  — a completed ImportJob exists for the exact date
  2. FALLBACK — no ImportJob, but decision count meets the day-type threshold
  3. UNDER-IMPORTED — fails both checks → would be scheduled for backfill

Usage:
    # Single day
    python manage.py inspect_backfill_coverage --date 2026-05-01

    # Date range
    python manage.py inspect_backfill_coverage --start-date 2026-04-01 --end-date 2026-05-01

    # Narrow to a specific entity
    python manage.py inspect_backfill_coverage --start-date 2026-01-01 --end-date 2026-01-31 \\
        --entity-type organization --entity-id AAA

    # Show only under-imported days (hide "done" noise)
    python manage.py inspect_backfill_coverage --start-date 2025-06-01 --end-date 2025-06-26 \\
        --only-gaps
"""

from datetime import date, datetime, timedelta

from core.services.coverage_service import BackfillCoverageService
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Show how the backfill algorithm classifies each day in a date range"

    # ------------------------------------------------------------------ #
    #  Argument parsing                                                    #
    # ------------------------------------------------------------------ #

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="Inspect a single day (YYYY-MM-DD)",
        )
        group.add_argument(
            "--start-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            dest="start_date",
            help="Start of range (YYYY-MM-DD)",
        )

        parser.add_argument(
            "--end-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            dest="end_date",
            default=None,
            help="End of range (YYYY-MM-DD, inclusive). Defaults to today.",
        )
        parser.add_argument(
            "--entity-type",
            choices=["all", "organization", "unit", "signer"],
            default="all",
            dest="entity_type",
            help="Restrict to a specific entity type (default: all)",
        )
        parser.add_argument(
            "--entity-id",
            default=None,
            dest="entity_id",
            help="UID of the entity (required when --entity-type is not 'all')",
        )
        parser.add_argument(
            "--only-gaps",
            action="store_true",
            dest="only_gaps",
            help="Only print under-imported days (suppress done rows)",
        )

    # ------------------------------------------------------------------ #
    #  Entry point                                                         #
    # ------------------------------------------------------------------ #

    def handle(self, *args, **options):
        entity_type = options["entity_type"]
        entity_id = options["entity_id"]

        if entity_type != "all" and not entity_id:
            raise CommandError(
                f"--entity-id is required when --entity-type is '{entity_type}'"
            )

        # Resolve date range
        if options.get("date"):
            start_date = end_date = options["date"]
        else:
            start_date = options["start_date"]
            end_date = options["end_date"] or date.today()

        if end_date < start_date:
            raise CommandError("--end-date must be >= --start-date")

        only_gaps = options["only_gaps"]

        # Build ORM filters
        decision_filter, job_filter = BackfillCoverageService.build_entity_filters(
            entity_type, entity_id
        )

        total_days = (end_date - start_date).days + 1

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n{'='*72}\n"
            f"  Backfill Coverage Inspection\n"
            f"  Range : {start_date}  →  {end_date}  ({total_days} days)\n"
            f"  Entity: {entity_type}" + (f" / {entity_id}" if entity_id else "") + "\n"
            f"{'='*72}\n"
        ))

        # Column header
        self.stdout.write(
            f"  {'DATE':<12} {'TYPE':<14} {'STATUS':<14} {'JOB':>6} {'COUNT':>8}  {'MIN':>7}  REASON"
        )
        self.stdout.write(f"  {'-'*70}")

        # Counters for summary
        done_by_job = 0
        done_by_threshold = 0
        under_imported = 0

        current = start_date
        while current <= end_date:
            verdict, details = BackfillCoverageService.classify_day(
                current, decision_filter, job_filter
            )

            if verdict == "done_job":
                done_by_job += 1
                if not only_gaps:
                    self.stdout.write(
                        self.style.SUCCESS(self._format_row(current, verdict, details))
                    )
            elif verdict == "done_threshold":
                done_by_threshold += 1
                if not only_gaps:
                    self.stdout.write(self._format_row(current, verdict, details))
            else:  # under_imported
                under_imported += 1
                self.stdout.write(
                    self.style.WARNING(self._format_row(current, verdict, details))
                )

            current += timedelta(days=1)

        # Summary
        self.stdout.write(f"\n  {'-'*70}")
        self.stdout.write(self.style.MIGRATE_HEADING("  SUMMARY"))
        self.stdout.write(f"  Total days       : {total_days}")
        self.stdout.write(
            self.style.SUCCESS(f"  Done (ImportJob) : {done_by_job}")
        )
        self.stdout.write(f"  Done (threshold) : {done_by_threshold}")
        self.stdout.write(
            self.style.WARNING(f"  Under-imported   : {under_imported}")
        )
        self.stdout.write("")

        if under_imported == 0:
            self.stdout.write(self.style.SUCCESS("  All days in range are fully covered.\n"))
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  {under_imported} day(s) would be scheduled for backfill.\n"
                )
            )

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _format_row(day: date, verdict: str, details: dict) -> str:
        day_type = details.get("day_type", "")

        if verdict == "done_job":
            job_id = details["job_id"]
            total = details["total_decisions"]
            chunks = f"{details['chunks_completed']}/{details['total_chunks']}"
            return (
                f"  {day!s:<12} {day_type:<14} {'DONE (job)':<14} "
                f"#{job_id:>5} {total:>8,}           job #{job_id} completed "
                f"({total:,} decisions, {chunks} chunks)"
            )

        count = details.get("decision_count", 0)
        min_exp = details.get("min_expected", 0)
        pct = f"{100 * count / min_exp:.0f}%" if min_exp else "n/a"
        skip = details.get("job_skip_reason")
        skip_suffix = f"  ⚠ {skip}" if skip else ""

        if verdict == "done_threshold":
            return (
                f"  {day!s:<12} {day_type:<14} {'DONE (thresh)':<14} "
                f"{'':>6} {count:>8,}  {min_exp:>7,}  {pct} of threshold{skip_suffix}"
            )

        # under_imported
        missing = min_exp - count
        return (
            f"  {day!s:<12} {day_type:<14} {'UNDER-IMPORTED':<14} "
            f"{'':>6} {count:>8,}  {min_exp:>7,}  {pct} of threshold — missing {missing:,}{skip_suffix}"
        )
