from datetime import date, datetime
from typing import Any, Dict, Optional

from celery import shared_task
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.import_jobs import DateCoverage, ImportJob, ImportJobStatus
from core.services.decision_ingestion_service import DecisionIngestionService
from django.utils import timezone
from loguru import logger


@shared_task(bind=True, max_retries=3, retry_backoff=True)
def fetch_decisions_for_increment(
    self,
    start_date_str: str,
    end_date_str: str,
    search_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Celery task to fetch decisions for a single date increment and save them to DB.

    Args:
        start_date_str: Start date in ISO format (YYYY-MM-DD)
        end_date_str: End date in ISO format (YYYY-MM-DD)
        search_params: Additional search parameters

    Returns:
        Dictionary with stats about the fetched and saved decisions
    """
    # Create a span for this task operation
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("fetch_decisions_increment") as span:
        # Add attributes to the span for context
        span.set_attribute("start_date", start_date_str)
        span.set_attribute("end_date", end_date_str)

        logger.info(f"Processing increment {start_date_str} to {end_date_str}")

        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)

        fetcher = DiavgeiaFetcher()
        importer = DecisionImporter()
        service = DecisionIngestionService(fetcher, decision_importer=importer)

        try:
            logger.info(f"Task {self.request.id}: Starting")

            # Use the internal method directly to fetch just this increment
            decisions = service._fetch_for_single_increment(
                start_date, end_date, search_params or {}
            )

            # Save decisions directly to the database
            created = 0
            if decisions:
                created = importer.import_many(decisions)
                logger.info(
                    f"Saved {created} new decisions to database (from {len(decisions)} total)"
                )

            # Record success in span
            span.set_attribute("status", "success")
            span.set_attribute("decisions_count", len(decisions))
            span.set_attribute("created_count", created)

            # Return stats about the operation
            return {
                "increment": f"{start_date_str} to {end_date_str}",
                "total_fetched": len(decisions),
                "new_saved": created,
                "status": "success",
            }
        except Exception as exc:
            # Record error in span
            span.set_status(trace.StatusCode.ERROR)
            span.record_exception(exc)
            logger.error(f"Error in fetch_decisions_for_increment: {str(exc)}")
            self.retry(exc=exc)


@shared_task
def process_fetch_period(
    start_date_str: str,
    end_date_str: str,
    date_increment_days: int = 30,
    search_params: Optional[Dict[str, Any]] = None,
    job_id: Optional[int] = None,
):
    """
    Orchestrator task that uses the enhanced DecisionIngestionService
    with built-in job tracking.
    """
    try:
        start_date = date.fromisoformat(start_date_str)
        end_date = date.fromisoformat(end_date_str)

        # Use the enhanced service with job tracking
        fetcher = DiavgeiaFetcher()
        importer = DecisionImporter()
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher, decision_importer=importer
        )

        # The service now handles job tracking and coverage updates
        service.fetch_decisions_for_period(
            start_date=start_date,
            end_date=end_date,
            date_increment_days=date_increment_days,
            search_params=search_params,
            distributed=True,
            save_to_db=True,
            job_id=job_id,  # Pass the job_id directly to the service
        )

        return "Decision fetch tasks dispatched"

    except Exception as e:
        logger.error(f"Error in process_fetch_period task: {str(e)}")
        raise


@shared_task
def collect_results(results=None) -> Dict[str, Any]:
    """
    Collect statistics from a group of tasks.
    """
    if not results:
        return {"status": "error", "message": "No results provided"}

    total_fetched = sum(r.get("total_fetched", 0) for r in results if r)
    total_saved = sum(r.get("new_saved", 0) for r in results if r)

    logger.success(
        f"All increments completed. Total fetched: {total_fetched}, "
        f"New decisions saved: {total_saved}"
    )

    return {
        "status": "complete",
        "total_fetched": total_fetched,
        "total_saved": total_saved,
        "increment_count": len(results),
    }


@shared_task
def update_coverage_stats(
    start_date, end_date, organization_id=None, unit_id=None, signer_id=None
):
    """Update the DateCoverage model with current stats"""
    from datetime import datetime, timedelta

    from core.models.decisions import Decision

    # Parse dates
    start = datetime.fromisoformat(start_date).date()
    end = datetime.fromisoformat(end_date).date()

    # Generate all dates in range
    current_date = start
    while current_date <= end:
        # Build filter for decisions on this date
        date_filter = {"issue_date__date": current_date}

        if organization_id:
            date_filter["organization__uid"] = organization_id
        elif unit_id:
            date_filter["units__uid"] = unit_id  # Note: plural 'units'
        if signer_id:
            date_filter["signers__uid"] = signer_id

        # Count decisions
        decision_count = Decision.objects.filter(**date_filter).count()

        # Update or create coverage record with proper duplicate handling
        try:
            coverage, created = DateCoverage.objects.get_or_create(
                date=current_date,
                organization_id=organization_id if organization_id else None,
                unit_id=unit_id if unit_id else None,
                signer_id=signer_id if signer_id else None,
                defaults={"decision_count": decision_count},
            )
            if not created:
                # Update the existing record
                coverage.decision_count = decision_count
                coverage.save()
        except DateCoverage.MultipleObjectsReturned:
            # Handle race condition - multiple processes created duplicates
            logger.warning(
                f"Found duplicate DateCoverage for date {current_date}, cleaning up"
            )
            # Delete all duplicates and create a fresh record
            DateCoverage.objects.filter(
                date=current_date,
                organization_id=organization_id if organization_id else None,
                unit_id=unit_id if unit_id else None,
                signer_id=signer_id if signer_id else None,
            ).delete()
            DateCoverage.objects.create(
                date=current_date,
                organization_id=organization_id if organization_id else None,
                unit_id=unit_id if unit_id else None,
                signer_id=signer_id if signer_id else None,
                decision_count=decision_count,
            )

        current_date += timedelta(days=1)


@shared_task
def daily_decisions_sync_task(target_date_str=None, incremental=True):
    """
    Daily task to sync decisions with optional reconciliation
    """
    from datetime import date, datetime, timedelta

    from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
    from core.importers.decisions import DecisionImporter
    from core.services.decision_ingestion_service import DecisionIngestionService

    try:
        # Parse target date
        if target_date_str:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        else:
            target_date = date.today() - timedelta(days=1)  # Yesterday

        logger.info(f"Starting daily sync task for {target_date}")

        # Create service components
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter()
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        if incremental:
            # Use incremental sync
            result = service.fetch_decisions_since_timestamp(save_to_db=True)
            logger.info(
                f"Incremental sync completed. Processed {result['processed_count']} decisions."
            )
        else:
            # Fetch specific day
            result = service.fetch_daily_decisions(
                target_date=target_date, save_to_db=True
            )
            logger.info(
                f"Daily sync completed for {target_date}. Processed {result['processed_count']} decisions."
            )

        # Schedule reconciliation task
        reconcile_daily_counts.delay(target_date.isoformat(), result["processed_count"])

        return {
            "status": "completed",
            "date": target_date.isoformat(),
            "processed_count": result["processed_count"],
        }

    except Exception as e:
        logger.error(f"Daily sync task failed: {str(e)}")
        raise


@shared_task
def reconcile_daily_counts(target_date_str, our_count):
    """
    Task to reconcile our decision counts with official API
    """
    from datetime import datetime

    import requests

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()

        # Get official counts
        response = requests.get(
            "https://diavgeia.gov.gr/static/api/search/countPerDayLastMonth", timeout=30
        )
        response.raise_for_status()

        official_data = response.json()

        # Find count for our target date
        target_timestamp = target_date.strftime("%Y-%m-%dT00:00:00Z")
        official_count = None

        for item in official_data.get("facetsResults", []):
            if item["label"] == target_timestamp:
                official_count = item["counter"]
                break

        if official_count is not None:
            difference = our_count - official_count
            percentage_diff = (
                (difference / official_count * 100) if official_count > 0 else 0
            )

            logger.info(f"Reconciliation for {target_date}:")
            logger.info(f"  Official count: {official_count}")
            logger.info(f"  Our count: {our_count}")
            logger.info(f"  Difference: {difference} ({percentage_diff:.2f}%)")

            # Store reconciliation results (you might want to create a model for this)
            # For now, just log significant discrepancies
            if abs(percentage_diff) > 10:  # More than 10% difference
                logger.warning(
                    f"Large discrepancy detected for {target_date}! Investigate needed."
                )

            return {
                "date": target_date_str,
                "official_count": official_count,
                "our_count": our_count,
                "difference": difference,
                "percentage_diff": percentage_diff,
            }
        else:
            logger.warning(f"No official count found for {target_date}")
            return {
                "date": target_date_str,
                "official_count": None,
                "our_count": our_count,
                "status": "no_official_data",
            }

    except Exception as e:
        logger.error(f"Reconciliation failed for {target_date_str}: {str(e)}")
        raise


@shared_task
def import_ministry_decisions_task(
    org_type=None, from_date=None, organization_uid=None, user_id=None
):
    from django.core.management import call_command

    args = []
    if org_type:
        args.extend(["--org-type", org_type])
    if from_date:
        args.extend(["--from-date", from_date])
    if organization_uid:
        args.extend(["--organization", organization_uid])

    # Log which user initiated this task (for auditing)
    if user_id:
        logger.info(f"Import ministry decisions task initiated by user ID: {user_id}")

    try:
        call_command("import_ministry_decisions", *args)
        return {"status": "completed"}
    except Exception as e:
        logger.error(f"Error importing decisions: {str(e)}")
        return {"status": "error", "message": str(e)}


@shared_task
def import_decisions_task(
    start_date,
    end_date,
    organization_id=None,
    unit_id=None,
    signer_id=None,
    job_id=None,
):
    """
    Celery task to import decisions from Diavgeia API

    Args:
        start_date: ISO format date string
        end_date: ISO format date string
        organization_id: Optional organization UID to filter
        unit_id: Optional unit UID to filter
        signer_id: Optional signer UID to filter
        job_id: ID of the ImportJob record
    """
    # Update job status
    job = None
    if job_id:
        job = ImportJob.objects.get(id=job_id)
        job.status = ImportJobStatus.RUNNING
        job.save()

    try:
        # Parse dates from strings
        start = datetime.fromisoformat(start_date).date()
        end = datetime.fromisoformat(end_date).date()

        # Create components
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter(import_job=job)
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        # Build search params
        search_params = {}
        if organization_id:
            search_params["org"] = organization_id
        elif unit_id:
            search_params["org"] = unit_id  # API uses 'org' parameter for both
        if signer_id:
            search_params["signer"] = signer_id

        # Run import
        result = service.fetch_decisions_for_period(
            start_date=start,
            end_date=end,
            date_increment_days=30,
            search_params=search_params,
            distributed=True,
            save_to_db=True,
            job_id=job_id,
        )

        # Update job with results
        if job_id:
            job.status = ImportJobStatus.COMPLETED
            job.completed_at = timezone.now()
            job.total_decisions = len(result)
            # You might want to add more stats about new vs updated decisions
            job.save()

        # Update coverage data
        update_coverage_stats.delay(start_date, end_date, organization_id, signer_id)

        return f"Imported {len(result)} decisions"

    except Exception as e:
        # Handle errors
        if job_id:
            job.status = ImportJobStatus.FAILED
            job.error_details = str(e)
            job.save()
        raise
