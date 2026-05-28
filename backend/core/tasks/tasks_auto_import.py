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
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.coverage_service import BackfillCoverageService
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

    # Guard against concurrent trigger_next_backfill executions.
    #
    # Two workers can both pass can_start_new_job() before either enqueues a job,
    # creating two interleaved backfill chains.  If a PENDING import job already
    # exists, another trigger instance has already found the next date and queued it;
    # let that chain continue via on_job_completed → dispatch_next_job().
    pending_count = queue.get_pending_jobs_count()
    if pending_count > 0:
        logger.info(
            f"Already have {pending_count} pending import job(s) — "
            f"skipping duplicate backfill trigger"
        )
        return {"status": "skipped", "reason": "pending_jobs_exist", "pending": pending_count}

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
    Find the next under-imported day going backwards from the most recent data.

    Uses actual Decision records with indexed issue_date_day field.
    Does NOT rely on DateCoverage (which may not be accurate).

    Day completion is evaluated in priority order:

    1. PRIMARY — A completed ImportJob exists for the exact date → day is done.
       This is the authoritative signal: we ran a full import and it finished.

    2. FALLBACK — No ImportJob found, but decision count meets the minimum
       threshold for the day type (via PublicHolidayDetectionService):
       - Workdays:    ≥ 10,000 decisions
       - Weekends:    ≥ 300 decisions
       - Holidays:    ≥ 200 decisions

    Algorithm (like Ctrl+Left in Excel):
    1. Find the most recent date with decisions (e.g., May 20, 2026)
    2. Go backwards day by day
    3. Skip days that pass either the ImportJob or threshold check
    4. Return the FIRST day that fails both checks

    Args:
        entity_type: 'all', 'organization', 'unit', or 'signer'
        entity_id: ID of the specific entity (if not 'all')

    Returns:
        The next date to import (most recent under-imported day), or None if
        all days are considered done going back to the API launch date.
    """
    # Build filters for Decision records and ImportJobs based on entity type
    decision_filter, job_filter = BackfillCoverageService.build_entity_filters(
        entity_type, entity_id
    )

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
        verdict, details = BackfillCoverageService.classify_day(
            current_date, decision_filter, job_filter
        )
        day_type = details["day_type"]
        decision_count = details["decision_count"]
        min_expected = details["min_expected"]

        if verdict == "done_job":
            logger.debug(
                f"[{current_date}] Done — ImportJob #{details['job_id']} completed "
                f"({details['total_decisions']:,} decisions, "
                f"{details['chunks_completed']}/{details['total_chunks']} chunks)"
            )
            current_date -= timedelta(days=1)
            continue

        if details.get("job_skip_reason"):
            logger.debug(
                f"[{current_date}] Completed ImportJob ignored — {details['job_skip_reason']}"
            )

        if verdict == "done_threshold":
            logger.debug(
                f"[{current_date}] Done — no valid ImportJob, but threshold met "
                f"(type={day_type}, count={decision_count:,}/{min_expected:,})"
            )
            current_date -= timedelta(days=1)
            continue

        # under_imported — neither check passed
        # Before scheduling, check if there's already an active job for this date.
        # An active job means data is still being imported; returning this date
        # would either be a no-op (skip_duplicates catches it) or, in a brief
        # status-transition window, spawn a duplicate import.  Skip it and keep
        # looking for a date that has no active coverage attempt.
        active_job = ImportJob.objects.filter(
            **job_filter,
            start_date=current_date,
            end_date=current_date,
            status__in=[
                ImportJobStatus.PENDING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.RUNNING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ],
        ).first()

        if active_job:
            logger.debug(
                f"[{current_date}] Skipping — active ImportJob #{active_job.id} "
                f"already in progress (status={active_job.status})"
            )
            current_date -= timedelta(days=1)
            continue

        # Guard against infinite re-import of dates where the API has
        # consistently returned nothing.
        #
        # We only stop retrying when ALL completed jobs for this date fetched
        # 0 decisions (total_decisions=0 → total_chunks=0) on 2+ independent
        # attempts.  A single 0-decision run may just be an API failure and
        # deserves one retry.
        #
        # We deliberately do NOT short-circuit based on decision_count alone:
        # a date that has, say, 6,560 decisions in the DB (below the 10,000
        # workday threshold) should still be retried — a successful new import
        # job will pass is_job_substantive and classify_day will return
        # "done_job", regardless of whether the count exceeds the threshold.
        # Accepting it prematurely would leave it permanently under-imported.
        #
        # NOTE: The Easter Sunday case (32 real decisions, all chunks done)
        # never reaches this guard — classify_day returns "done_job" for it.
        zero_decision_attempts = ImportJob.objects.filter(
            **job_filter,
            start_date=current_date,
            end_date=current_date,
            status__in=[
                ImportJobStatus.COMPLETED,
                ImportJobStatus.PARTIALLY_COMPLETED,
            ],
            total_decisions=0,
        ).count()

        if zero_decision_attempts >= 2:
            logger.warning(
                f"[{current_date}] Skipping — {zero_decision_attempts} completed jobs "
                f"returned 0 decisions (DB has {decision_count:,} for this date). "
                f"Accepting as-is to avoid infinite loop."
            )
            current_date -= timedelta(days=1)
            continue

        logger.info(
            f"[{current_date}] Under-imported — no valid ImportJob and below threshold "
            f"(type={day_type}, count={decision_count:,}, min_expected={min_expected:,}) "
            f"→ scheduling backfill"
        )
        return current_date

    logger.info(f"No gaps found going back to {api_launch_date}")
    return None


@shared_task
def trigger_next_company_gemi_batch(batch_size: int = 3, _previous_result=None):
    """
    Continuous virtuous-cycle GEMI company fetcher (autofarming).

    Called automatically after each batch of AFM fetches completes.
    Grabs the next `batch_size` top-ranked eligible companies that have not
    yet been fetched, adds them to the AFMFetchQueueService priority queue,
    dispatches process_afm_fetch_queue for exactly that batch, and chains
    itself as the completion callback so the cycle continues.

    Cycle stops naturally when:
    - AUTO_COMPANY_GEMI_IMPORT_ENABLED is turned off  (checked every iteration)
    - No more unfetched eligible entities remain

    Args:
        batch_size: How many companies to grab per iteration (default: 3)
        _previous_result: Ignored — present so Celery can pass it when used
                          as a success link from process_afm_fetch_queue.
    """
    if not feature_flags.is_enabled("AUTO_COMPANY_GEMI_IMPORT_ENABLED"):
        logger.debug(
            "AUTO_COMPANY_GEMI_IMPORT_ENABLED is disabled, stopping company GEMI cycle"
        )
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from core.services.afm_fetch_queue_service import AFMFetchQueueService
    from core.tasks.tasks_entities import process_afm_fetch_queue

    queue_service = AFMFetchQueueService()

    # Guard: if there are already pending items another cycle iteration is in
    # flight (e.g. beat triggered while cycle was running).  Let it finish.
    pending = queue_service.get_pending_count()
    if pending > 0:
        logger.info(
            f"Company GEMI cycle already in flight ({pending} pending), skipping duplicate trigger"
        )
        return {"status": "skipped", "reason": "already_running", "pending": pending}

    # Grab the next batch from the ranked eligible list
    stats = queue_service.populate_queue_from_scores(
        target_count=batch_size,
        force_refresh=False,
        auto_trigger=False,
    )

    added = stats.get("added", 0)

    if added == 0:
        logger.info(
            "Company GEMI cycle complete — no more eligible entities to fetch"
        )
        return {
            "status": "completed",
            "message": "All eligible entities have been processed",
        }

    logger.info(
        f"Company GEMI cycle: queued {added} companies, dispatching fetch + next trigger"
    )

    # Dispatch fetch for exactly this batch; on success, chain the next trigger.
    # .si() makes the signature immutable so Celery does not inject the
    # preceding task's result as a positional argument.
    process_afm_fetch_queue.apply_async(
        kwargs={"max_items": added},
        link=trigger_next_company_gemi_batch.si(batch_size=batch_size),
    )

    return {
        "status": "queued",
        "added": added,
        "batch_size": batch_size,
    }
