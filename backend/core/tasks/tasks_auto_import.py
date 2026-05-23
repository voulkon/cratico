"""
Auto Import Tasks - Dual Mode System

1. AUTO DAILY IMPORT (Fresh Data)
   - Runs at configurable time (default 00:30)
   - Imports decisions for yesterday
   - Will eventually include summaries and email notifications

2. AUTO BACKFILL (Continuous Autofarming)
   - Runs continuously after each import job completes
   - Finds the next oldest day with data
   - Queues it for import
   - Repeats until no more gaps found
   - Uses actual Decision records (not DateCoverage)
"""

from datetime import date, timedelta

from celery import shared_task
from core.models.decisions import Decision
from core.services.feature_flag_service import feature_flags
from core.services.import_job_queue import ImportJobQueue
from django.db.models import Max
from loguru import logger


@shared_task
def auto_daily_import_task():
    """
    Daily fresh data import task.

    Runs at the time specified in AUTO_DAILY_IMPORT_TIME feature flag.
    Imports decisions for yesterday.

    Future enhancements:
    - Generate daily summaries
    - Send email notifications
    - Analytics updates

    Only runs if AUTO_DAILY_IMPORT_ENABLED is true.
    """
    if not feature_flags.is_enabled("AUTO_DAILY_IMPORT_ENABLED"):
        logger.info("AUTO_DAILY_IMPORT_ENABLED is disabled, skipping daily import")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    logger.info("Starting auto daily import for fresh data")

    queue = ImportJobQueue()
    yesterday = date.today() - timedelta(days=1)

    try:
        job = queue.enqueue_job(
            target_date=yesterday,
            search_params={"force": False},
            created_by=None,  # System-initiated
            auto_dispatch=True,
            skip_duplicates=True,
        )

        logger.info(f"Daily import queued: Job #{job.id} for {yesterday}")

        # TODO: Add summary generation here
        # TODO: Add email notifications here

        return {
            "status": "success",
            "date": str(yesterday),
            "job_id": job.id,
            "job_status": job.status,
        }

    except Exception as e:
        logger.error(f"Failed to queue daily import: {e}")
        return {"status": "error", "date": str(yesterday), "error": str(e)}


@shared_task
def trigger_next_backfill():
    """
    Continuous backfill trigger (autofarming).

    Called automatically after each import job completes.
    Finds the next oldest day with data and queues it for import.

    This creates a continuous loop:
    1. Job completes
    2. This task finds next oldest day
    3. Queues it
    4. When that job completes, repeat

    Only runs if AUTO_BACKFILL_ENABLED is true.
    """
    if not feature_flags.is_enabled("AUTO_BACKFILL_ENABLED"):
        logger.debug("AUTO_BACKFILL_ENABLED is disabled, skipping backfill")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    logger.info("Checking for next backfill opportunity")

    queue = ImportJobQueue()

    # Check if we can start a new job (respect concurrency limits)
    if not queue.can_start_new_job():
        logger.info("Cannot start new job (concurrency limit reached)")
        return {"status": "skipped", "reason": "concurrency_limit"}

    # Find the next oldest day to import
    next_date = find_next_oldest_missing_day()

    if not next_date:
        logger.info("No more days to backfill - coverage is complete!")
        return {"status": "completed", "message": "No more gaps found"}

    logger.info(f"Found next oldest day to backfill: {next_date}")

    try:
        job = queue.enqueue_job(
            target_date=next_date,
            search_params={"force": False},
            created_by=None,
            auto_dispatch=True,
            skip_duplicates=True,
        )

        logger.info(f"Backfill queued: Job #{job.id} for {next_date}")

        return {
            "status": "success",
            "date": str(next_date),
            "job_id": job.id,
            "job_status": job.status,
        }

    except Exception as e:
        logger.error(f"Failed to queue backfill: {e}")
        return {"status": "error", "date": str(next_date), "error": str(e)}


def find_next_oldest_missing_day(entity_type="all", entity_id=None) -> date | None:
    """
    Find the next missing day going backwards from the most recent data.

    Uses actual Decision records with indexed issue_date_day field.
    Does NOT rely on DateCoverage (which may not be accurate).

    Algorithm (like Ctrl+Left in Excel):
    1. Find the most recent date with decisions (e.g., May 20, 2026)
    2. Go backwards day by day
    3. Skip days WITH decisions (continuous coverage)
    4. Return the FIRST day WITHOUT decisions (most recent gap)

    Example timeline (going backwards):
    - May-March: all present (skip)
    - February: MISSING ← return Feb 28 (first missing day found)
    - January: all present (won't check yet)
    - December: missing (will find later)
    - November: all present

    Args:
        entity_type: 'all', 'organization', 'unit', or 'signer'
        entity_id: ID of the specific entity (if not 'all')

    Returns:
        The next date to import (most recent gap), or None if no gaps found
    """
    # Build filter for Decision records based on entity type
    decision_filter = {}

    if entity_type == "organization" and entity_id:
        decision_filter["organization__uid"] = entity_id
    elif entity_type == "unit" and entity_id:
        decision_filter["units__uid"] = entity_id
    elif entity_type == "signer" and entity_id:
        decision_filter["signers__uid"] = entity_id
    # For 'all', no filter needed

    # Find the MOST RECENT date with actual decisions in our database
    # Use issue_date_day which is indexed for efficiency
    latest_in_db = Decision.objects.filter(**decision_filter).aggregate(
        Max("issue_date_day")
    )["issue_date_day__max"]

    if not latest_in_db:
        logger.warning("No decisions found in database - this might be a fresh install")
        # Start from yesterday as a reasonable starting point
        return date.today() - timedelta(days=1)

    logger.debug(f"Most recent date in DB: {latest_in_db}")

    # Go backwards from the most recent date to find the first gap
    # Start from the day before the most recent data
    current_date = latest_in_db - timedelta(days=1)

    # We'll go back until we find a gap, or until we reach a reasonable limit
    # (e.g., API launch date or 10 years ago)
    # TODO: Make this part of feature flag configuration too
    api_launch_date = date(2010, 10, 1)  # Diavgeia API approximate launch

    while current_date >= api_launch_date:
        # Check if this date has any decisions in our DB using indexed field
        has_data = Decision.objects.filter(
            **decision_filter, issue_date_day=current_date
        ).exists()

        if not has_data:
            # Found a day without data - this is our target
            logger.info(f"Found next missing day: {current_date}")
            return current_date

        # This day has data, keep going backwards
        current_date -= timedelta(days=1)

    logger.info(f"No gaps found going back to {api_launch_date}")
    return None
