"""
Organization-specific decision fetching tasks.

These tasks complement the default daily fetch by requesting decisions
specifically per organization, allowing comparison of what the default
search finds vs. organization-targeted searches.
"""

import os
import pickle
import time
from datetime import datetime
from typing import Any, Dict, Optional

from celery import shared_task
from core.constants.decision_import_constants import PICKLE_DIR
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.organizations import Organization
from core.utils.discovery_tracking import (
    DiscoverySource,
    add_discovery_source_to_decision,
)
from loguru import logger


@shared_task(bind=True, max_retries=3)
def fetch_org_decisions_to_pickle(
    self,
    org_uid: str,
    from_date: str,
    to_date: str,
    search_params: Optional[Dict[str, Any]] = None,
):
    """
    Fetch decisions for a specific organization and save to pickle.

    This allows you to compare:
    - Which decisions appear in default search
    - Which decisions only appear when querying by organization

    Args:
        org_uid: Organization UID (e.g., "6115")
        from_date: Start date in ISO format
        to_date: End date in ISO format
        search_params: Additional search parameters

    Returns:
        Dict with pickle file path and metadata

    Example:
        >>> # Fetch decisions for a specific organization
        >>> from core.tasks.tasks_org_decisions import fetch_org_decisions_to_pickle
        >>> result = fetch_org_decisions_to_pickle.delay(
        ...     org_uid="6115",
        ...     from_date="2023-01-01",
        ...     to_date="2023-12-31"
        ... )
    """
    try:
        logger.info(
            f"Task {self.request.id}: Fetching decisions for org {org_uid} "
            f"from {from_date} to {to_date}"
        )

        # Get organization details
        try:
            org = Organization.objects.get(uid=org_uid)
            org_identifier = f"{org_uid};{org.latin_name.lower().replace(' ', '')}"
            logger.info(f"Task {self.request.id}: Found org: {org.label}")
        except Organization.DoesNotExist:
            org_identifier = org_uid
            logger.warning(
                f"Task {self.request.id}: Organization {org_uid} not in DB, "
                f"using UID only"
            )

        # Create fetcher
        fetcher = DiavgeiaFetcher()

        # Build search parameters
        if search_params is None:
            search_params = {}

        search_params.update(
            {
                "org": org_identifier,
                "from_issue_date": from_date,  # Use issue_date not modification date!
                "to_issue_date": to_date,  # Use issue_date not modification date!
                "page": 0,
                "size": 500,
            }
        )

        # Fetch all pages
        all_decisions = []
        page = 0
        total_pages = 1

        while page < total_pages:
            search_params["page"] = page

            response = fetcher.fetch_decisions(**search_params)

            if response and response.info:
                if page == 0 and response.info.total > 0:
                    page_size = search_params.get("size", 500)
                    total_pages = (response.info.total + page_size - 1) // page_size
                    logger.info(
                        f"Task {self.request.id}: Found {response.info.total} total "
                        f"decisions, {total_pages} pages for org {org_uid}"
                    )

                all_decisions.extend(response.decisions)
                page += 1
                logger.info(
                    f"Task {self.request.id}: Fetched page {page}/{total_pages}"
                )

                if response.info.actualSize < search_params.get("size", 500):
                    logger.info(
                        f"Task {self.request.id}: Reached last page "
                        f"(actualSize {response.info.actualSize})"
                    )
                    break
            else:
                logger.warning(f"Task {self.request.id}: No response for page {page}")
                break

        # Create pickle directory
        pickle_dir = PICKLE_DIR
        os.makedirs(pickle_dir, exist_ok=True)

        # Generate pickle file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        pickle_file = (
            f"{pickle_dir}/org_{org_uid}_{from_date}_{to_date}_{timestamp}.pkl"
        )

        # Save to pickle with metadata
        pickle_data = {
            "decisions": all_decisions,
            "source_type": DiscoverySource.ORG_SPECIFIC,
            "search_params": search_params,
            "org_uid": org_uid,
            "fetched_at": datetime.utcnow().isoformat(),
            "total_count": len(all_decisions),
        }

        with open(pickle_file, "wb") as f:
            pickle.dump(pickle_data, f)

        logger.info(
            f"Task {self.request.id}: Saved {len(all_decisions)} org decisions to {pickle_file}"
        )

        # Dispatch storage task
        from core.tasks.tasks_org_decisions import store_org_decisions_from_pickle

        storage_task = store_org_decisions_from_pickle.delay(
            pickle_file=pickle_file, skip_opensearch=False
        )

        return {
            "status": "success",
            "pickle_file": pickle_file,
            "decision_count": len(all_decisions),
            "org_uid": org_uid,
            "storage_task_id": storage_task.id,
            "from_date": from_date,
            "to_date": to_date,
        }

    except Exception as e:
        logger.error(
            f"Task {self.request.id}: Error fetching org decisions for {org_uid}: {e}"
        )
        raise self.retry(countdown=60 * (self.request.retries + 1))


@shared_task(bind=True, max_retries=5)
def store_org_decisions_from_pickle(
    self, pickle_file: str, skip_opensearch: bool = False, delay_seconds: int = 0
):
    """
    Load org-specific decisions from pickle and process with source tracking.

    This is similar to store_decisions_from_pickle but tags decisions with
    DiscoverySource.ORG_SPECIFIC to track they came from org-targeted search.

    Args:
        pickle_file: Path to pickle file
        skip_opensearch: Skip OpenSearch indexing
        delay_seconds: Sleep before processing
    """
    if delay_seconds > 0:
        logger.info(
            f"Task {self.request.id}: Sleeping {delay_seconds}s to prevent race conditions"
        )
        time.sleep(delay_seconds)

    try:
        logger.info(f"Task {self.request.id}: Loading org decisions from {pickle_file}")

        # Load pickle
        if not os.path.exists(pickle_file):
            raise FileNotFoundError(f"Pickle file not found: {pickle_file}")

        with open(pickle_file, "rb") as f:
            pickle_data = pickle.load(
                f
            )  # nosec: B301 - Internal pickle files for org decisions import

        decisions = pickle_data["decisions"]
        source_type = pickle_data.get("source_type", DiscoverySource.ORG_SPECIFIC)
        search_params = pickle_data.get("search_params", {})
        org_uid = pickle_data.get("org_uid", "unknown")

        logger.info(
            f"Task {self.request.id}: Loaded {len(decisions)} decisions for org {org_uid}"
        )

        # Import decisions through orchestrator
        from core.models.decisions import Decision
        from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
        from core.tasks.tasks_documents import run_decision_pipeline_task

        orchestrator = DecisionPipelineOrchestrator()
        dispatched_tasks = []
        failed_imports = []
        newly_discovered = []

        for i, decision_dto in enumerate(decisions, 1):
            try:
                # Check if decision already exists
                existing = Decision.objects.filter(ada=decision_dto.ada).first()
                is_new = existing is None

                # Import decision
                decision = orchestrator._step_import_decision(decision_dto)

                if decision:
                    # Tag with discovery source
                    add_discovery_source_to_decision(
                        decision,
                        source_type=source_type,
                        search_params={
                            "org": org_uid,
                            "from_date": search_params.get("from_date"),
                            "to_date": search_params.get("to_date"),
                        },
                        notes=f"Found in org-specific search for {org_uid}",
                        save=True,
                    )

                    # Check if decision needs processing
                    needs_processing = is_new

                    if not is_new:
                        # Check if existing decision has errors or incomplete processing
                        from core.models.decision_health import (
                            DecisionHealthCheck,
                            HealthStatus,
                        )

                        health_check = DecisionHealthCheck.objects.filter(
                            decision=decision
                        ).first()

                        if health_check:
                            needs_processing = health_check.overall_status in [
                                HealthStatus.ERROR,
                                HealthStatus.WARNING,
                                HealthStatus.UNKNOWN,
                            ]
                        else:
                            # No health check exists - needs processing
                            needs_processing = True

                    if needs_processing:
                        if is_new:
                            newly_discovered.append(decision.ada)
                            logger.info(
                                f"Task {self.request.id}: NEW decision {decision.ada} "
                                f"discovered via org search (not in default!)"
                            )

                        # Dispatch pipeline task only if needed
                        pipeline_task = run_decision_pipeline_task.delay(
                            ada=decision.ada,
                            force_reprocess=False,
                            skip_opensearch=skip_opensearch,
                        )

                        dispatched_tasks.append(
                            {
                                "ada": decision.ada,
                                "task_id": pipeline_task.id,
                                "is_new": is_new,
                            }
                        )
                    else:
                        logger.debug(
                            f"Task {self.request.id}: Skipping {decision.ada} - "
                            f"already processed with healthy status"
                        )

                    if i % 10 == 0:
                        logger.info(
                            f"Task {self.request.id}: Processed {i}/{len(decisions)} "
                            f"org decisions ({len(newly_discovered)} new)"
                        )
                else:
                    failed_imports.append(
                        {"ada": decision_dto.ada, "error": "Import failed"}
                    )

            except Exception as e:
                logger.error(
                    f"Task {self.request.id}: Error processing decision "
                    f"{decision_dto.ada}: {e}"
                )
                failed_imports.append({"ada": decision_dto.ada, "error": str(e)})

        # Cleanup pickle
        try:
            os.remove(pickle_file)
            logger.info(f"Task {self.request.id}: Cleaned up pickle file {pickle_file}")
        except Exception as e:
            logger.warning(
                f"Task {self.request.id}: Failed to cleanup pickle {pickle_file}: {e}"
            )

        result = {
            "status": "success",
            "total_processed": len(decisions),
            "dispatched_tasks": len(dispatched_tasks),
            "failed_imports": len(failed_imports),
            "newly_discovered": len(newly_discovered),
            "new_adas": newly_discovered[:100],  # First 100 for logging
            "org_uid": org_uid,
            "source_type": source_type,
        }

        logger.info(
            f"Task {self.request.id}: Org decision storage completed. "
            f"Processed: {result['total_processed']}, "
            f"New discoveries: {result['newly_discovered']}, "
            f"Failed: {result['failed_imports']}"
        )

        return result

    except Exception as e:
        logger.error(f"Task {self.request.id}: Error in org decision storage: {e}")
        raise self.retry(countdown=60 * (self.request.retries + 1))


@shared_task
def fetch_all_orgs_decisions(from_date: str, to_date: str, limit: Optional[int] = None):
    """
    Dispatch fetch tasks for all organizations in the database.

    This creates a comprehensive org-specific fetch to compare against
    default searches and identify coverage gaps.

    Args:
        from_date: Start date in ISO format
        to_date: End date in ISO format
        limit: Optional limit on number of organizations to process

    Returns:
        Dict with dispatched task information

    Example:
        >>> # Fetch decisions for all orgs in 2023
        >>> from core.tasks.tasks_org_decisions import fetch_all_orgs_decisions
        >>> result = fetch_all_orgs_decisions.delay(
        ...     from_date="2023-01-01",
        ...     to_date="2023-12-31",
        ...     limit=10  # Start with 10 orgs for testing
        ... )
    """
    logger.info(
        f"Dispatching org-specific fetches for all orgs from {from_date} to {to_date}"
    )

    # Get all active organizations
    orgs = Organization.objects.filter(status="active")

    if limit:
        orgs = orgs[:limit]
        logger.info(f"Limited to {limit} organizations")

    total_orgs = orgs.count()
    logger.info(f"Found {total_orgs} organizations to process")

    dispatched = []

    for i, org in enumerate(orgs, 1):
        try:
            task = fetch_org_decisions_to_pickle.delay(
                org_uid=org.uid, from_date=from_date, to_date=to_date
            )

            dispatched.append(
                {"org_uid": org.uid, "org_label": org.label, "task_id": task.id}
            )

            if i % 10 == 0:
                logger.info(f"Dispatched {i}/{total_orgs} org fetch tasks")

            # Small delay to avoid overwhelming the API
            time.sleep(0.5)

        except Exception as e:
            logger.error(f"Error dispatching task for org {org.uid}: {e}")

    logger.info(
        f"Dispatched {len(dispatched)} org-specific fetch tasks out of {total_orgs} orgs"
    )

    return {
        "status": "success",
        "total_orgs": total_orgs,
        "dispatched": len(dispatched),
        "from_date": from_date,
        "to_date": to_date,
        "tasks": dispatched,
    }
