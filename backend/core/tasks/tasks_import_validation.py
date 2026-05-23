"""
Import Validation and Backfill Tasks

Validates historical decision imports and triggers re-imports for days with
insufficient data based on statistical thresholds.

Architecture:
    1. validate_and_backfill_imports: Main orchestrator task that scans history
    2. validate_single_day: Checks one day and triggers re-import if needed
    3. Uses statistical thresholds based on day-of-week patterns
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional

from celery import shared_task
from core.models.decisions import Decision
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.models.import_thresholds import ImportThreshold
from core.utils.public_holiday_calculation import is_greek_holiday
from django.utils import timezone
from loguru import logger

# Default thresholds (used as fallback if DB config not available)
# These are MINIMUM thresholds - actual complete days typically have more
DEFAULT_THRESHOLDS = {
    "weekday": 5000,  # Monday-Friday minimum
    "saturday": 100,  # Saturday minimum
    "sunday": 70,  # Sunday minimum
}


def get_threshold_for_date(target_date: date) -> int:
    """
    Get minimum expected decision count for a date.

    Uses database-configured thresholds from ImportThreshold model,
    falls back to DEFAULT_THRESHOLDS if not available.

    Args:
        target_date: Date to check

    Returns:
        Minimum expected decision count
    """
    # Check if it's a Greek public holiday
    is_holiday, holiday_name = is_greek_holiday(target_date)
    if is_holiday:
        logger.debug(f"{target_date} is a holiday: {holiday_name}")
        # Use Sunday threshold for holidays
        try:
            return ImportThreshold.get_instance().sunday_threshold
        except Exception as e:
            logger.warning(f"Could not load threshold from DB: {e}, using default")
            return DEFAULT_THRESHOLDS["sunday"]

    # Get threshold based on day of week
    day_of_week = target_date.weekday()
    try:
        return ImportThreshold.get_threshold_for_weekday(day_of_week)
    except Exception as e:
        logger.warning(f"Could not load threshold from DB: {e}, using default")
        # Fallback to defaults
        if day_of_week == 5:  # Saturday
            return DEFAULT_THRESHOLDS["saturday"]
        elif day_of_week == 6:  # Sunday
            return DEFAULT_THRESHOLDS["sunday"]
        else:  # Monday-Friday
            return DEFAULT_THRESHOLDS["weekday"]


def is_day_complete(target_date: date) -> tuple[bool, int, int]:
    """
    Check if a day has sufficient decisions to be considered complete.

    Args:
        target_date: Date to check

    Returns:
        Tuple of (is_complete, actual_count, expected_threshold)
    """
    # Make timezone-aware datetime range for the full day
    day_start = timezone.make_aware(datetime.combine(target_date, datetime.min.time()))
    day_end = timezone.make_aware(datetime.combine(target_date, datetime.max.time()))

    actual_count = Decision.objects.filter(
        issue_date__gte=day_start, issue_date__lte=day_end
    ).count()
    expected_threshold = get_threshold_for_date(target_date)

    is_complete = actual_count >= expected_threshold

    return is_complete, actual_count, expected_threshold


@shared_task(bind=True)
def validate_and_backfill_imports(
    self,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    days_back: int = 60,
    dry_run: bool = False,
    force_reimport: bool = False,
    chunk_size: int = 10,
    skip_enabled_check: bool = False,
    max_reimports: Optional[int] = None,
):
    """
    Orchestrator: Scan historical imports and trigger re-imports for incomplete days.

    This task walks backward from today (or end_date) and checks each day's
    decision count against expected thresholds. If a day is under-imported,
    it dispatches fetch_daily_decisions_distributed to re-import that day.

    Args:
        start_date_str: Start date in ISO format (e.g., "2025-12-01")
        end_date_str: End date in ISO format (defaults to today)
        days_back: Number of days to check backward if dates not provided (default: 60)
        dry_run: If True, only report issues without triggering imports
        force_reimport: Force re-import even if previous ImportJob exists
        chunk_size: Chunk size for distributed imports (default: 10)
        skip_enabled_check: Skip the enabled check (for manual command runs)
        max_reimports: Maximum number of re-imports to dispatch (None = unlimited)

    Returns:
        Dict with validation summary and dispatched jobs
    """
    try:
        # Check if validation system is enabled (unless explicitly skipped)
        if not skip_enabled_check:
            try:
                config = ImportThreshold.get_instance()
                if not config.enabled:
                    logger.info(
                        "Import validation system is DISABLED. Skipping validation."
                    )
                    return {
                        "status": "disabled",
                        "message": "Import validation system is disabled in admin configuration.",
                    }
            except Exception as e:
                logger.warning(
                    f"Could not check if validation is enabled: {e}. Proceeding anyway."
                )

        # Determine date range
        if end_date_str:
            end_date = datetime.fromisoformat(end_date_str).date()
        else:
            end_date = date.today()

        if start_date_str:
            start_date = datetime.fromisoformat(start_date_str).date()
        else:
            start_date = end_date - timedelta(days=days_back)

        # Get task ID (handle sync calls from management commands)
        task_id = getattr(self.request, "id", "sync-command")

        logger.info(
            f"Validation task {task_id}: Checking {start_date} to {end_date} "
            f"(dry_run={dry_run}, force={force_reimport})"
        )

        # Collect validation results
        results = {
            "total_days_checked": 0,
            "complete_days": 0,
            "incomplete_days": 0,
            "reimport_dispatched": 0,
            "reimport_skipped": 0,
            "details": [],
        }

        # Walk through each day
        current_date = end_date
        while current_date >= start_date:
            results["total_days_checked"] += 1

            # Check if day is complete
            is_complete, actual_count, threshold = is_day_complete(current_date)
            day_name = current_date.strftime("%A")
            is_holiday, holiday_name = is_greek_holiday(current_date)

            day_result = {
                "date": current_date.isoformat(),
                "day_name": day_name,
                "holiday_name": holiday_name if is_holiday else None,
                "is_holiday": is_holiday,
                "actual_count": actual_count,
                "threshold": threshold,
                "is_complete": is_complete,
                "action_taken": None,
            }

            if is_complete:
                results["complete_days"] += 1
                logger.info(
                    f"[OK] {current_date} ({day_name}): {actual_count:,} decisions "
                    f"(threshold: {threshold:,}) - Complete"
                )
            else:
                results["incomplete_days"] += 1
                shortage = threshold - actual_count

                logger.warning(
                    f"[WARN]️  {current_date} ({day_name}): {actual_count:,} decisions "
                    f"(threshold: {threshold:,}) - SHORT BY {shortage:,}"
                )

                if dry_run:
                    day_result["action_taken"] = "dry_run_skip"
                    results["reimport_skipped"] += 1
                    logger.info(
                        f"   [DRY RUN] Would dispatch re-import for {current_date}"
                    )
                elif (
                    max_reimports is not None
                    and results["reimport_dispatched"] >= max_reimports
                ):
                    # Stop dispatching if we've reached the limit
                    day_result["action_taken"] = "max_limit_reached"
                    results["reimport_skipped"] += 1
                    logger.info(
                        f"   ⏸️  Max re-import limit ({max_reimports}) reached, skipping {current_date}"
                    )
                else:
                    # Check if there's already an in-progress job
                    existing_job = None
                    if not force_reimport:
                        existing_job = ImportJob.objects.filter(
                            start_date=current_date,
                            end_date=current_date,
                            status__in=[
                                ImportJobStatus.PENDING,
                                ImportJobStatus.FETCHING,
                                ImportJobStatus.SPLITTING,
                                ImportJobStatus.PROCESSING,
                            ],
                        ).first()

                    if existing_job:
                        logger.info(
                            f"   ⏩ Import already in progress for {current_date} "
                            f"(job ID {existing_job.id}), skipping"
                        )
                        day_result["action_taken"] = "existing_job_found"
                        day_result["existing_job_id"] = existing_job.id
                        results["reimport_skipped"] += 1
                    else:
                        # Use ImportJobQueue to respect concurrency limits
                        from core.services.import_job_queue import ImportJobQueue

                        queue = ImportJobQueue()
                        search_params = {"force": force_reimport}

                        job = queue.enqueue_job(
                            target_date=current_date,
                            search_params=search_params,
                            created_by=None,  # System-triggered validation
                            auto_dispatch=True,  # Auto-dispatch if capacity available
                        )

                        logger.success(
                            f"   [RETRY] Queued re-import job #{job.id} for {current_date} "
                            f"(status: {job.status})"
                        )

                        day_result["action_taken"] = "reimport_dispatched"
                        day_result["job_id"] = job.id
                        day_result["job_status"] = job.status
                        results["reimport_dispatched"] += 1

            results["details"].append(day_result)

            # Move to previous day
            current_date -= timedelta(days=1)

        # Log summary
        logger.success(
            f"Validation complete: {results['total_days_checked']} days checked, "
            f"{results['complete_days']} complete, {results['incomplete_days']} incomplete, "
            f"{results['reimport_dispatched']} re-imports dispatched"
        )

        return results

    except Exception as e:
        task_id = getattr(self.request, "id", "sync-command")
        logger.error(f"Validation task {task_id}: Failed: {str(e)}")
        raise


@shared_task(bind=True)
def validate_single_day(
    self, target_date_str: str, force_reimport: bool = False, chunk_size: int = 10
) -> Dict[str, Any]:
    """
    Validate a single day and trigger re-import if needed.

    This is a convenience task for checking individual days.

    Args:
        target_date_str: Date to validate in ISO format (e.g., "2025-12-15")
        force_reimport: Force re-import even if threshold is met
        chunk_size: Chunk size for distributed import

    Returns:
        Dict with validation result and action taken
    """
    try:
        target_date = datetime.fromisoformat(target_date_str).date()

        logger.info(f"Validating single day: {target_date}")

        # Check completeness
        is_complete, actual_count, threshold = is_day_complete(target_date)
        day_name = target_date.strftime("%A")
        is_holiday, holiday_name = is_greek_holiday(target_date)

        result = {
            "date": target_date.isoformat(),
            "holiday_name": holiday_name if is_holiday else None,
            "day_name": day_name,
            "is_holiday": is_holiday,
            "actual_count": actual_count,
            "threshold": threshold,
            "is_complete": is_complete,
            "action_taken": None,
        }

        if is_complete and not force_reimport:
            logger.info(
                f"[OK] {target_date} ({day_name}): {actual_count:,} decisions - Complete"
            )
            result["action_taken"] = "no_action_needed"
            return result

        # Trigger re-import using ImportJobQueue to respect concurrency limits
        from core.services.import_job_queue import ImportJobQueue

        queue = ImportJobQueue()
        search_params = {"force": force_reimport}

        job = queue.enqueue_job(
            target_date=target_date,
            search_params=search_params,
            created_by=None,  # System-triggered validation
            auto_dispatch=True,  # Auto-dispatch if capacity available
        )

        logger.success(
            f"[RETRY] Queued re-import job #{job.id} for {target_date} (status: {job.status})"
        )

        result["action_taken"] = "reimport_dispatched"
        result["job_id"] = job.id
        result["job_status"] = job.status

        return result

    except Exception as e:
        logger.error(f"Single day validation failed: {str(e)}")
        raise


@shared_task(bind=True)
def update_thresholds_from_analysis(
    self, weekday_threshold: int, saturday_threshold: int, sunday_threshold: int
):
    """
    Update the global thresholds based on analyze_decision_counts results.

    This is a convenience task to update thresholds without code changes.
    Note: Changes are not persisted across worker restarts unless code is updated.

    Args:
        weekday_threshold: New threshold for Monday-Friday
        saturday_threshold: New threshold for Saturday
        sunday_threshold: New threshold for Sunday

    Returns:
        Dict with old and new threshold values
    """
    global DECISION_COUNT_THRESHOLDS

    old_thresholds = DECISION_COUNT_THRESHOLDS.copy()

    DECISION_COUNT_THRESHOLDS["weekday"] = weekday_threshold
    DECISION_COUNT_THRESHOLDS["saturday"] = saturday_threshold
    DECISION_COUNT_THRESHOLDS["sunday"] = sunday_threshold

    logger.info(
        f"Updated thresholds: weekday={weekday_threshold}, "
        f"saturday={saturday_threshold}, sunday={sunday_threshold}"
    )

    return {
        "old_thresholds": old_thresholds,
        "new_thresholds": DECISION_COUNT_THRESHOLDS.copy(),
    }
