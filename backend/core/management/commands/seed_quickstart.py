"""
Fill a fresh development database with a small slice of real Diavgeia data.

The command picks a recent low-volume day, queues a global DAILY import for it
through ImportJobQueue, and enables the post-import flags so cache warming and
amount verification run against the imported decisions.

The import uses the normal distributed pipeline: Celery fetch, Redis chunks,
DecisionImporter, DecisionPipelineOrchestrator, then post-import.  It does not
use the shallow ``seed_data --decisions`` path, which skips the pipeline.
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from loguru import logger

from core.models.import_jobs import ImportJobStatus, ImportJobType
from core.services.decision_fetch_reconcile_service import (
    DecisionFetchReconcileService,
)
from core.services.import_job_queue import ImportJobQueue
from core.services.public_holiday_detection_service import (
    PublicHolidayDetectionService,
)

POST_IMPORT_FLAGS = (
    "POST_IMPORT_ORCHESTRATOR_ENABLED",
    "ANALYTICS_WARMUP_ENABLED",
    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED",
)


def enable_post_import_flags() -> list[str]:
    """Enable the post-import flags and return the keys that changed."""
    from core.models.feature_flags import FeatureFlag
    from core.services.feature_flag_service import feature_flags

    feature_flags.initialize_flags_in_db()

    changed: list[str] = []
    for key in POST_IMPORT_FLAGS:
        flag = FeatureFlag.objects.filter(key=key).first()
        if flag is None or flag.enabled:
            continue
        flag.enabled = True
        flag.save(update_fields=["enabled"])
        changed.append(key)

    feature_flags.clear_cache()
    return changed


def _pick_recent_low_volume_date(
    service: DecisionFetchReconcileService,
    min_count: int,
    max_count: int,
    today: date,
) -> tuple[date | None, int | None, str]:
    """
    Return the most recent completed day whose official count is in range.

    ``get_all_official_daily_counts`` returns rows sorted newest first, so the
    first in-range day is the most recent one.  Today is skipped because its
    count is still growing.  Weekdays normally carry tens of thousands of
    decisions, so the default range selects a weekend or a holiday.
    """
    rows = service.get_all_official_daily_counts()
    if not rows:
        return None, None, "no_counts"

    completed = [row for row in rows if row["date"] < today]
    in_range = [row for row in completed if min_count <= row["count"] <= max_count]
    if in_range:
        row = in_range[0]
        return row["date"], row["count"], "in_range"

    above = [row for row in completed if row["count"] >= min_count]
    if above:
        row = min(above, key=lambda r: (r["count"], -r["date"].toordinal()))
        return row["date"], row["count"], "above_range"

    return None, None, "below_min"


class Command(BaseCommand):
    help = (
        "Import a recent low-volume day through the real pipeline so a fresh "
        "development database has decisions, organizations, and warm caches."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=lambda s: date.fromisoformat(s),
            help="Import this day instead of discovering a recent low-volume one "
            "(YYYY-MM-DD)",
        )
        parser.add_argument(
            "--min-count",
            type=int,
            default=100,
            help="Minimum official decision count for auto-discovery (default: 100)",
        )
        parser.add_argument(
            "--max-count",
            type=int,
            default=1000,
            help="Maximum official decision count for auto-discovery (default: 1000)",
        )
        parser.add_argument(
            "--no-post-import",
            action="store_true",
            help="Do not enable POST_IMPORT_ORCHESTRATOR_ENABLED and its sub-flags",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Resolve the date and show the flags without queueing a job",
        )

    def handle(self, *args, **options):
        min_count = options["min_count"]
        max_count = options["max_count"]
        dry_run = options["dry_run"]
        enable_post_import = not options["no_post_import"]

        if min_count < 0 or max_count < min_count:
            raise CommandError("Require 0 <= --min-count <= --max-count")

        today = timezone.localdate()

        if options["date"]:
            target_date = options["date"]
            official_count = None
            if target_date > today:
                raise CommandError("--date cannot be in the future")
        else:
            target_date, official_count = self._resolve_date(
                min_count, max_count, today
            )

        day_type = PublicHolidayDetectionService.get_day_type(target_date)
        day_label = day_type.replace("_", " ")
        count_label = (
            f", {official_count} official decisions"
            if official_count is not None
            else ""
        )
        self.stdout.write(f"Target date: {target_date} ({day_label}{count_label})")
        logger.info(
            f"seed_quickstart: target date {target_date}, "
            f"official_count={official_count}, dry_run={dry_run}"
        )

        if enable_post_import:
            if dry_run:
                self.stdout.write("Would enable: " + ", ".join(POST_IMPORT_FLAGS))
            else:
                changed = enable_post_import_flags()
                if changed:
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Enabled post-import flags: " + ", ".join(changed)
                        )
                    )
                else:
                    self.stdout.write(
                        "Post-import flags already enabled: "
                        + ", ".join(POST_IMPORT_FLAGS)
                    )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run: no ImportJob was queued."))
            return

        queue = ImportJobQueue()
        job = queue.enqueue_job(
            target_date=target_date,
            search_params={"force": False},
            created_by=None,
            auto_dispatch=True,
            skip_duplicates=True,
            import_type=ImportJobType.DAILY,
        )
        # dispatch_next_job updates a different instance, so read the status
        # that was actually persisted before reporting it.
        job.refresh_from_db()

        self.stdout.write(
            self.style.SUCCESS(f"Queued ImportJob #{job.id} for {target_date}")
        )
        self.stdout.write(f"  Status: {job.status}")

        if job.status == ImportJobStatus.PENDING:
            self.stdout.write(
                self.style.WARNING(
                    "  The import queue is at capacity. The job starts when a "
                    "slot frees, or run: python manage.py import_queue dispatch-next"
                )
            )

        self.stdout.write("")
        self.stdout.write("The worker fetches the day, imports decisions and")
        self.stdout.write("organizations, then runs cache warming and amount")
        self.stdout.write("verification. Expect several minutes for ~1,000 decisions.")
        self.stdout.write("")
        self.stdout.write("Monitor:")
        self.stdout.write("  http://localhost/admin/core/importjob/")
        self.stdout.write("  http://localhost:5555 (Flower)")

    def _resolve_date(
        self, min_count: int, max_count: int, today: date
    ) -> tuple[date, int | None]:
        service = DecisionFetchReconcileService()

        target_date, official_count, reason = _pick_recent_low_volume_date(
            service, min_count, max_count, today
        )
        if target_date:
            if reason == "above_range":
                message = (
                    f"No completed day inside {min_count}-{max_count}; using "
                    f"{target_date} with {official_count} decisions."
                )
                logger.warning(message)
                self.stdout.write(self.style.WARNING(message))
            return target_date, official_count

        fallback = today - timedelta(days=1)
        if reason == "no_counts":
            message = (
                "Official daily counts are unavailable. Falling back to "
                "yesterday, which may be larger than --max-count."
            )
        else:
            message = (
                f"No completed day has at least {min_count} decisions. "
                f"Falling back to yesterday, which may be larger than "
                f"--max-count."
            )
        logger.warning(message)
        self.stdout.write(self.style.WARNING(message))
        return fallback, None
