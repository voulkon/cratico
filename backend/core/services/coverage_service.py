"""
Single source of truth for deciding whether a given date is fully covered
by the import pipeline.

Used by:
  - find_next_oldest_missing_day  (core/tasks/tasks_auto_import.py)
  - inspect_backfill_coverage     (management command)
"""

from datetime import date
from typing import Literal

from core.models.decisions import Decision
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.public_holiday_detection_service import PublicHolidayDetectionService
from core.constants.decision_import_constants import COVERAGE_DATE_FIELD

DayVerdict = Literal["done_job", "done_threshold", "under_imported"]


class BackfillCoverageService:
    """
    Decides whether a single calendar day is fully covered, and why.

    Day completion is evaluated in priority order:

    1. PRIMARY  — A completed ImportJob exists for the exact date.
                  This is the authoritative signal: a full import ran and finished.

    2. FALLBACK — No ImportJob found, but decision count meets the minimum
                  threshold for the day type:
                    Workdays  ≥ 10,000
                    Weekends  ≥     300
                    Holidays  ≥     200
    """

    THRESHOLD_WORKDAY = 10_000
    THRESHOLD_WEEKEND = 300
    THRESHOLD_HOLIDAY = 200

    # ------------------------------------------------------------------ #
    #  Filter helpers                                                      #
    # ------------------------------------------------------------------ #

    @staticmethod
    def build_entity_filters(
        entity_type: str = "all", entity_id=None
    ) -> tuple[dict, dict]:
        """
        Return ``(decision_filter, job_filter)`` ORM keyword-argument dicts
        scoped to the requested entity.
        """
        decision_filter: dict = {}
        job_filter: dict = {}

        if entity_type == "organization" and entity_id:
            decision_filter["organization__uid"] = entity_id
            job_filter["organization__uid"] = entity_id
        elif entity_type == "unit" and entity_id:
            decision_filter["units__uid"] = entity_id
            job_filter["unit__uid"] = entity_id
        elif entity_type == "signer" and entity_id:
            decision_filter["signers__uid"] = entity_id
            job_filter["signer__uid"] = entity_id

        return decision_filter, job_filter

    # ------------------------------------------------------------------ #
    #  Threshold helper                                                    #
    # ------------------------------------------------------------------ #

    @classmethod
    def min_expected_for_day_type(cls, day_type: str) -> int:
        """Return the minimum decision count threshold for the given day type."""
        if day_type in ("saturday", "sunday"):
            return cls.THRESHOLD_WEEKEND
        if day_type == "observed_holiday":
            return cls.THRESHOLD_HOLIDAY
        return cls.THRESHOLD_WORKDAY

    # ------------------------------------------------------------------ #
    #  Job sanity check                                                    #
    # ------------------------------------------------------------------ #

    @classmethod
    def is_job_substantive(cls, job: "ImportJob") -> tuple[bool, str]:
        """
        Return ``(is_valid, reason)`` for a completed ImportJob.

        A job is considered authoritative if all chunks ran to completion:

            ``total_chunks > 0`` and ``chunks_completed == total_chunks``

        The old ``total_decisions >= MIN_DECISIONS_FOR_VALID_JOB`` floor has been
        removed.  It was redundant: if 0 decisions were fetched then total_chunks
        is also 0 (chunks are created from fetched decision ADAs), so the chunk
        check already rejects empty jobs.  The floor only caused problems for
        dates with genuinely low decision counts (e.g. Easter Sunday with 32
        decisions), making them unresolvable and creating an infinite backfill loop.

        NOTE: We intentionally do NOT compare decisions_assigned_to_pipeline with
        decisions_restored_from_redis.  Since the introduction of the health-check
        skip (healthy decisions bypass run_decision_pipeline_task), "assigned" is
        always ≤ "restored" — they are only equal when every single decision in
        the job is unhealthy.  The mismatch is expected and correct; checking for
        equality would cause every valid job to be rejected.
        """
        if job.total_chunks == 0 or job.chunks_completed != job.total_chunks:
            return False, (
                f"chunks_completed={job.chunks_completed} "
                f"!= total_chunks={job.total_chunks}"
            )

        return True, "ok"

    # ------------------------------------------------------------------ #
    #  Core classification                                                 #
    # ------------------------------------------------------------------ #

    @classmethod
    def classify_day(
        cls,
        day: date,
        decision_filter: dict,
        job_filter: dict,
    ) -> tuple[DayVerdict, dict]:
        """
        Decide whether a single day is fully covered.

        Returns ``(verdict, details)`` where *verdict* is one of:

        ``'done_job'``
            A completed, substantive ImportJob exists for the exact date.

        ``'done_threshold'``
            No valid ImportJob, but decision count meets the day-type threshold.

        ``'under_imported'``
            Fails both checks; should be scheduled for import.

        *details* always contains:
            day_type, job_id (or None), decision_count, min_expected,
            total_decisions, chunks_completed, total_chunks,
            job_skip_reason (populated when a completed job was found but rejected)
        """
        day_type = PublicHolidayDetectionService.get_day_type(day)
        min_expected = cls.min_expected_for_day_type(day_type)

        # ── PRIMARY: completed (or partially completed) ImportJob? ──────
        completed_job = (
            ImportJob.objects.filter(
                **job_filter,
                start_date=day,
                end_date=day,
                status__in=[
                    ImportJobStatus.COMPLETED,
                    ImportJobStatus.PARTIALLY_COMPLETED,
                ],
            )
            .order_by("-completed_at")
            .first()
        )

        if completed_job:
            is_valid, skip_reason = cls.is_job_substantive(completed_job)
            if is_valid:
                return "done_job", {
                    "day_type": day_type,
                    "job_id": completed_job.id,
                    "total_decisions": completed_job.total_decisions,
                    "chunks_completed": completed_job.chunks_completed,
                    "total_chunks": completed_job.total_chunks,
                    "decision_count": completed_job.total_decisions,
                    "min_expected": min_expected,
                    "job_skip_reason": None,
                }
            # Job exists but failed sanity checks — fall through to threshold
            job_skip_reason = f"job #{completed_job.id} rejected: {skip_reason}"
        else:
            job_skip_reason = None

        # ── FALLBACK: count-based threshold ──────────────────────────────
        decision_count = Decision.objects.filter(
            **decision_filter, **{COVERAGE_DATE_FIELD: day}
        ).count()

        details = {
            "day_type": day_type,
            "job_id": completed_job.id if completed_job else None,
            "job_skip_reason": job_skip_reason,
            "decision_count": decision_count,
            "min_expected": min_expected,
            "total_decisions": decision_count,
            "chunks_completed": None,
            "total_chunks": None,
        }

        if decision_count >= min_expected:
            return "done_threshold", details

        return "under_imported", details
