import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.models.types import ActType
from core.services.seed_service import SeedService
from diavgeia_api.models.decisions import Decision
from diavgeia_api.models.search import SearchResponse
from django.utils import timezone
from loguru import logger


class DecisionIngestionService:
    """
    Service responsible for fetching decisions from Diavgeia API,
    handling date range iteration and pagination, and tracking import jobs.
    """

    DEFAULT_PAGE_SIZE = 500  # Max allowed by Diavgeia API
    DEFAULT_DELAY_SECONDS = 1.1

    def __init__(
        self,
        diavgeia_fetcher: DiavgeiaFetcher,
        delay_seconds: float = DEFAULT_DELAY_SECONDS,
        decision_importer: Optional[DecisionImporter] = None,
    ) -> None:
        """
        Initializes the service.

        Args:
            diavgeia_fetcher: An instance of the DiavgeiaFetcher.
            delay_seconds: Minimum time delay between consecutive API calls.
            decision_importer: Optional importer to persist decisions to database.
        """
        self.diavgeia_fetcher = diavgeia_fetcher
        self.delay_seconds = delay_seconds
        self.decision_importer = decision_importer
        logger.info(
            f"Initialized DecisionIngestionService with delay: {self.delay_seconds}s"
        )

    def ensure_types_before_import(self, force: bool = False) -> dict:
        """
        Ensures act types are available in the database before attempting
        to import decisions. Types are critical for proper importing.

        Args:
            force: If True, update existing types

        Returns:
            Dictionary with status information
        """
        if not ActType.objects.exists() or force:
            # Types don't exist or force flag is set - need to seed them
            logger.info(
                "Act types don't exist or force flag set. Seeding types before importing decisions..."
            )

            # Create a temporary seed service
            seed_service = SeedService()

            # Seed the types
            return seed_service.seed_types(force=force)
        else:
            logger.info("Act types already exist. Proceeding with decision import...")
            return {
                "status": "skipped",
                "seeded": False,
                "message": "Types already exist",
            }

    def fetch_decisions_for_period(
        self,
        start_date: date,
        end_date: date,
        date_increment_days: int = 30,
        search_params: Optional[Dict[str, Any]] = None,
        distributed: bool = False,
        save_to_db: bool = False,
        ensure_types: bool = True,
        force_types: bool = False,
        job_id: Optional[int] = None,
    ) -> Union[List[Decision], Tuple[List[Decision], Dict[str, Any]]]:
        """
        Fetches all decisions within a given date period using the 'issueDate'.

        Handles date increments, pagination, and job tracking.

        Args:
            start_date: The beginning of the date range (inclusive).
            end_date: The end of the date range (inclusive).
            date_increment_days: How many days to fetch in each sub-query.
            search_params: Additional search parameters.
            distributed: If True, creates Celery tasks instead of processing locally.
            save_to_db: Whether to save fetched decisions to the database.
            ensure_types: Whether to check and seed types before importing.
            force_types: Whether to force update existing types.
            job_id: Optional ImportJob ID to track progress.

        Returns:
            Either a list of Decision objects or a tuple with (decisions, job_stats).
        """
        # Update job status if we have a job_id
        job = None
        if job_id:
            try:
                job = ImportJob.objects.get(id=job_id)
                job.status = ImportJobStatus.RUNNING
                job.save()
                logger.info(f"Updated job {job_id} status to RUNNING")
            except ImportJob.DoesNotExist:
                logger.warning(f"Job with ID {job_id} not found")

        try:
            # Original validation and preparation
            if date_increment_days < 1:
                raise ValueError("date_increment_days must be at least 1")

            # Check if we need to ensure types are available
            if save_to_db and ensure_types:
                type_result = self.ensure_types_before_import(force=force_types)
                if type_result.get("status") == "error":
                    logger.error(
                        f"Failed to seed required types: {type_result.get('message')}"
                    )

            # Extract entity IDs for coverage updates
            organization_id = None
            unit_id = None
            signer_id = None
            if search_params:
                # Handle organization parameter
                org_param = search_params.get("org")
                if org_param:
                    # Check if this is a unit or organization
                    from core.models.organizations import Organization, Unit

                    try:
                        Organization.objects.get(uid=org_param)
                        organization_id = org_param
                    except Organization.DoesNotExist:
                        try:
                            Unit.objects.get(uid=org_param)
                            unit_id = org_param
                        except Unit.DoesNotExist:
                            logger.warning(
                                f"Entity with UID {org_param} not found in organizations or units"
                            )

                # Handle explicit unit parameter
                unit_param = search_params.get("unit")
                if unit_param:
                    from core.models.organizations import Unit

                    try:
                        Unit.objects.get(uid=unit_param)
                        unit_id = unit_param
                    except Unit.DoesNotExist:
                        logger.warning(f"Unit with UID {unit_param} not found")

                signer_id = search_params.get("signer")

            # Check feature flag for decision type filtering
            from core.services.feature_flag_service import feature_flags

            filtered_types = feature_flags.get_value("FILTER_DECISION_TYPES")
            if (
                filtered_types
                and isinstance(filtered_types, list)
                and len(filtered_types) > 0
            ):
                # Initialize search_params if None
                if search_params is None:
                    search_params = {}
                # Join types with semicolon (API supports this for multiple types)
                search_params["type"] = ";".join(filtered_types)
                logger.info(
                    f"Feature flag FILTER_DECISION_TYPES active: filtering by types {filtered_types} "
                    f"(joined as: {search_params['type']})"
                )
            elif filtered_types is not None:
                logger.info(
                    "Feature flag FILTER_DECISION_TYPES is empty - importing all decision types"
                )

            decisions = []
            if distributed:
                decisions = self._fetch_decisions_distributed(
                    start_date, end_date, date_increment_days, search_params
                )
                # For distributed mode, decisions will be empty as tasks are processed async
            else:
                decisions = self._fetch_decisions_locally(
                    start_date, end_date, date_increment_days, search_params, save_to_db
                )

            # Update coverage stats if needed
            if save_to_db and (organization_id or unit_id or signer_id):
                self._update_coverage_stats(
                    start_date, end_date, organization_id, unit_id, signer_id
                )

            # Update job status on success
            if job:
                job.status = ImportJobStatus.COMPLETED
                job.completed_at = timezone.now()
                job.total_decisions = len(decisions)
                job.save()
                logger.info(f"Updated job {job_id} status to COMPLETED")

                # Return both decisions and job stats
                return decisions, {
                    "job_id": job_id,
                    "status": "completed",
                    "total_decisions": len(decisions),
                }

            # Return just decisions if no job tracking
            return decisions

        except Exception as e:
            # Handle errors and update job status
            logger.error(f"Error in fetch_decisions_for_period: {str(e)}")
            if job:
                job.status = ImportJobStatus.FAILED
                job.error_details = str(e)
                job.save()
                logger.info(f"Updated job {job_id} status to FAILED: {str(e)}")
            raise

    def _fetch_decisions_distributed(
        self,
        start_date: date,
        end_date: date,
        date_increment_days: int = 1,  # Much smaller chunks for distributed
        search_params: Optional[Dict[str, Any]] = None,
    ) -> List[Decision]:
        """Implementation that dispatches tasks to Celery workers with smaller chunks"""
        from celery import group
        from core.tasks import fetch_decisions_for_increment

        increments = []
        current_start = start_date

        # For distributed mode, use much smaller increments (hours instead of days)
        # This ensures better load distribution across workers
        while current_start <= end_date:
            current_end = min(
                current_start + timedelta(days=date_increment_days - 1), end_date
            )

            # Further split each day into smaller chunks by organization types or time ranges
            # This creates more granular tasks for better distribution
            increments.append((current_start.isoformat(), current_end.isoformat()))
            current_start += timedelta(days=date_increment_days)

        # Create a group of tasks for parallel processing
        logger.info(
            f"Dispatching {len(increments)} tasks to workers (1 day per task for better distribution)"
        )

        # Create and execute tasks group (one task per date increment)
        job = group(
            fetch_decisions_for_increment.s(start, end, search_params)
            for start, end in increments
        )

        # Execute the group
        result = job.apply_async()

        # Store the group_id for reference
        group_id = result.id
        logger.info(f"Tasks dispatched with group ID: {group_id}")

        return []  # Return empty list as results will be collected asynchronously

    def _fetch_decisions_locally(
        self,
        start_date: date,
        end_date: date,
        date_increment_days: int,
        search_params: Optional[Dict[str, Any]],
        save_to_db: bool,
    ) -> List[Decision]:
        """Process decisions locally (non-distributed mode)"""
        all_decisions: Dict[str, Decision] = {}
        current_start = start_date
        total_fetched_count = 0

        if search_params is None:
            search_params = {}
        else:
            # Remove pagination/date params if accidentally passed
            search_params.pop("page", None)
            search_params.pop("size", None)
            search_params.pop("from_issue_date", None)
            search_params.pop("to_issue_date", None)

        logger.info(
            f"Starting decision fetch from {start_date.isoformat()} to {end_date.isoformat()} "
            f"with increment {date_increment_days} days. Params: {search_params}"
        )

        while current_start <= end_date:
            # Calculate end date for the current increment
            current_end = min(
                current_start + timedelta(days=date_increment_days - 1), end_date
            )
            logger.info(
                f"Processing date range: {current_start.isoformat()} to {current_end.isoformat()}"
            )

            # --- Fetch decisions for the current date increment ---
            decisions_in_increment = self._fetch_for_single_increment(
                current_start, current_end, search_params
            )

            # Add unique decisions to the main dictionary
            for decision in decisions_in_increment:
                key = decision.ada or decision.versionId  # Prefer ADA for uniqueness
                if key not in all_decisions:
                    all_decisions[key] = decision

            total_fetched_count += len(decisions_in_increment)
            logger.info(
                f"Fetched {len(decisions_in_increment)} decisions for {current_start.isoformat()}-{current_end.isoformat()}. "
                f"Total unique so far: {len(all_decisions)}"
            )

            # Move to the next date increment
            current_start += timedelta(days=date_increment_days)

        logger.success(
            f"Finished fetching all decisions for the period. "
            f"Total unique decisions found: {len(all_decisions)} (fetched {total_fetched_count} total)."
        )

        decisions_list = list(all_decisions.values())

        if save_to_db and self.decision_importer:
            created = self.decision_importer.import_decisions(decisions_list)
            logger.info(
                f"Saved {created} new decisions to database (from {len(decisions_list)} total)"
            )

        return decisions_list

    def _update_coverage_stats(
        self,
        start_date: date,
        end_date: date,
        organization_id: Optional[str] = None,
        unit_id: Optional[str] = None,
        signer_id: Optional[str] = None,
    ) -> None:
        """Update the DateCoverage model with current stats"""
        from core.models.decisions import Decision
        from core.models.import_jobs import DateCoverage

        # Generate all dates in range
        current_date = start_date
        while current_date <= end_date:
            # Build filter for decisions on this date
            date_filter = {"issue_date_day": current_date}

            # Handle organization coverage
            if organization_id:
                date_filter["organization__uid"] = organization_id
                decision_count = Decision.objects.filter(**date_filter).count()

                # Use get_or_create with proper exception handling for race conditions
                try:
                    coverage, created = DateCoverage.objects.get_or_create(
                        date=current_date,
                        organization_id=organization_id,
                        unit=None,
                        signer=None,
                        defaults={"decision_count": decision_count},
                    )
                    if not created:
                        # Update the existing record
                        coverage.decision_count = decision_count
                        coverage.save()
                except DateCoverage.MultipleObjectsReturned:
                    # Handle race condition - multiple processes created duplicates
                    logger.warning(
                        f"Found duplicate DateCoverage for org {organization_id} on {current_date}, cleaning up"
                    )
                    # Delete all duplicates and create a fresh record
                    DateCoverage.objects.filter(
                        date=current_date,
                        organization_id=organization_id,
                        unit=None,
                        signer=None,
                    ).delete()
                    DateCoverage.objects.create(
                        date=current_date,
                        organization_id=organization_id,
                        unit=None,
                        signer=None,
                        decision_count=decision_count,
                    )

                logger.debug(
                    f"Updated organization coverage for {organization_id} on {current_date}: {decision_count}"
                )

            # Handle unit coverage - note the plural 'units' field
            if unit_id:
                date_filter["units__uid"] = unit_id
                decision_count = Decision.objects.filter(**date_filter).count()

                try:
                    coverage, created = DateCoverage.objects.get_or_create(
                        date=current_date,
                        organization=None,
                        unit_id=unit_id,
                        signer=None,
                        defaults={"decision_count": decision_count},
                    )
                    if not created:
                        coverage.decision_count = decision_count
                        coverage.save()
                except DateCoverage.MultipleObjectsReturned:
                    logger.warning(
                        f"Found duplicate DateCoverage for unit {unit_id} on {current_date}, cleaning up"
                    )
                    DateCoverage.objects.filter(
                        date=current_date,
                        organization=None,
                        unit_id=unit_id,
                        signer=None,
                    ).delete()
                    DateCoverage.objects.create(
                        date=current_date,
                        organization=None,
                        unit_id=unit_id,
                        signer=None,
                        decision_count=decision_count,
                    )

                logger.debug(
                    f"Updated unit coverage for {unit_id} on {current_date}: {decision_count}"
                )

            # Handle signer coverage
            if signer_id:
                # Reset filter and add signer condition
                date_filter = {"issue_date_day": current_date}
                date_filter["signers__uid"] = signer_id
                decision_count = Decision.objects.filter(**date_filter).count()

                try:
                    coverage, created = DateCoverage.objects.get_or_create(
                        date=current_date,
                        organization=None,
                        unit=None,
                        signer_id=signer_id,
                        defaults={"decision_count": decision_count},
                    )
                    if not created:
                        coverage.decision_count = decision_count
                        coverage.save()
                except DateCoverage.MultipleObjectsReturned:
                    logger.warning(
                        f"Found duplicate DateCoverage for signer {signer_id} on {current_date}, cleaning up"
                    )
                    DateCoverage.objects.filter(
                        date=current_date,
                        organization=None,
                        unit=None,
                        signer_id=signer_id,
                    ).delete()
                    DateCoverage.objects.create(
                        date=current_date,
                        organization=None,
                        unit=None,
                        signer_id=signer_id,
                        decision_count=decision_count,
                    )

                logger.debug(
                    f"Updated signer coverage for {signer_id} on {current_date}: {decision_count}"
                )

            current_date += timedelta(days=1)

        logger.info(f"Updated DateCoverage records from {start_date} to {end_date}")

    # Add the missing method back to the class
    def _fetch_for_single_increment(
        self, start_date: date, end_date: date, base_search_params: Dict[str, Any]
    ) -> List[Decision]:
        """Helper method to fetch all pages for a single date increment."""
        increment_decisions: List[Decision] = []
        page = 0
        total_pages = 1  # Assume at least one page initially

        while page < total_pages:
            current_search_params = base_search_params.copy()
            current_search_params["from_issue_date"] = start_date.isoformat()
            current_search_params["to_issue_date"] = end_date.isoformat()
            current_search_params["page"] = page
            current_search_params["size"] = self.DEFAULT_PAGE_SIZE

            logger.debug(
                f"Fetching page {page + 1}/{total_pages if total_pages > 1 else '?'}..."
            )

            # --- Rate Limiting ---
            time.sleep(self.delay_seconds)  # Simple delay before each request

            response: Optional[SearchResponse] = self.diavgeia_fetcher.fetch_decisions(
                **current_search_params
            )

            if response and response.info:
                # Update total pages based on the first valid response for this increment
                if page == 0 and response.info.total > 0:
                    total_pages = (
                        response.info.total + self.DEFAULT_PAGE_SIZE - 1
                    ) // self.DEFAULT_PAGE_SIZE
                    logger.debug(
                        f"Total decisions for increment: {response.info.total}, Total pages: {total_pages}"
                    )

                if response.decisions:
                    increment_decisions.extend(response.decisions)
                    logger.debug(
                        f"Got {len(response.decisions)} decisions on page {page + 1}."
                    )
                else:
                    # No decisions on this page, likely finished pagination for this increment
                    logger.debug(
                        f"No decisions found on page {page + 1}. Ending pagination for this increment."
                    )
                    break

                # Check if actualSize indicates the last page
                if response.info.actualSize < self.DEFAULT_PAGE_SIZE:
                    logger.debug(
                        f"Reached last page for increment (actualSize {response.info.actualSize} < size {self.DEFAULT_PAGE_SIZE})."
                    )
                    break  # Exit pagination loop

                page += 1
            else:
                # Handle fetcher failure or invalid response
                logger.error(
                    f"Failed to fetch or received invalid response for page {page + 1}. "
                    f"Stopping pagination for {start_date.isoformat()}-{end_date.isoformat()}."
                )
                # Potentially add retry logic here later
                break  # Exit pagination loop

        return increment_decisions

    def fetch_decisions_since_timestamp(
        self,
        since_timestamp=None,
        # TODO: add type annottation with respective import
        # since_timestamp: Optional[datetime] = None,
        search_params: Optional[Dict[str, Any]] = None,
        save_to_db: bool = True,
        max_days_per_batch: int = 7,
    ) -> Dict[str, Any]:
        """
        Fetch all decisions since a given timestamp using publishTimestamp.

        Args:
            since_timestamp: Timestamp to start from. If None, gets from SyncStatus
            search_params: Additional search parameters
            save_to_db: Whether to save to database
            max_days_per_batch: Maximum days to process in each batch

        Returns:
            Dictionary with sync results and stats
        """
        from core.models.sync_status import SyncStatus
        from django.utils import timezone

        # Get the starting timestamp
        if since_timestamp is None:
            since_timestamp = SyncStatus.get_last_decisions_sync()

        # Current timestamp for this sync
        current_timestamp = timezone.now()

        logger.info(
            f"Starting incremental sync from {since_timestamp} to {current_timestamp}"
        )

        # Convert timestamps to dates for the existing logic
        start_date = since_timestamp.date()
        end_date = current_timestamp.date()

        # Ensure we don't go too far back in a single run
        max_start_date = current_timestamp.date() - timedelta(days=30)
        if start_date < max_start_date:
            start_date = max_start_date
            logger.warning(
                f"Limited start date to {start_date} to avoid processing too much data"
            )

        try:
            # Update search params to use publishTimestamp instead of issueDate
            if search_params is None:
                search_params = {}

            # Use publishTimestamp for more recent data
            search_params["from_publish_timestamp"] = since_timestamp.isoformat()
            search_params["to_publish_timestamp"] = current_timestamp.isoformat()

            # Fetch decisions using existing infrastructure
            decisions = self.fetch_decisions_for_period(
                start_date=start_date,
                end_date=end_date,
                date_increment_days=max_days_per_batch,
                search_params=search_params,
                distributed=False,  # Run locally for incremental sync
                save_to_db=save_to_db,
                ensure_types=True,
            )

            # Update sync status
            processed_count = len(decisions) if isinstance(decisions, list) else 0
            SyncStatus.update_decisions_sync(
                timestamp=current_timestamp,
                processed_count=processed_count,
                status="completed",
            )

            logger.success(
                f"Incremental sync completed. Processed {processed_count} decisions."
            )

            return {
                "status": "completed",
                "processed_count": processed_count,
                "start_timestamp": since_timestamp,
                "end_timestamp": current_timestamp,
                "duration_hours": (current_timestamp - since_timestamp).total_seconds()
                / 3600,
            }

        except Exception as e:
            # Update sync status with error
            SyncStatus.update_decisions_sync(
                timestamp=since_timestamp,  # Don't advance timestamp on error
                processed_count=0,
                status="failed",
                error=str(e),
            )
            logger.error(f"Incremental sync failed: {str(e)}")
            raise

    def fetch_daily_decisions(
        self,
        target_date: Optional[date] = None,
        save_to_db: bool = True,
        want_it_distributed: bool = False,
    ) -> Dict[str, Any]:
        """
        Fetch all decisions for a specific day.

        Args:
            target_date: Date to fetch decisions for. Defaults to yesterday.
            save_to_db: Whether to save to database

        Returns:
            Dictionary with results and stats
        """
        if target_date is None:
            target_date = date.today() - timedelta(days=1)  # Yesterday

        logger.info(f"Fetching all decisions for {target_date}")

        # Fetch decisions for the full day
        decisions = self.fetch_decisions_for_period(
            start_date=target_date,
            end_date=target_date,
            date_increment_days=1,
            search_params={},  # No filters - fetch everything
            distributed=want_it_distributed,
            save_to_db=save_to_db,
            ensure_types=True,
        )

        processed_count = len(decisions) if isinstance(decisions, list) else 0

        logger.info(f"Fetched {processed_count} decisions for {target_date}")

        return {
            "status": "completed",
            "date": target_date,
            "processed_count": processed_count,
            "decisions": decisions,
        }
