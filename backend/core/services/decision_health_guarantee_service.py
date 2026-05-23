"""
Decision Health Guarantee Service

This service provides backward reconciliation for the decision processing pipeline.
While DecisionPipelineOrchestrator handles forward processing of new decisions,
this service ensures data consistency across ALL decisions in the database by:

1. Finding gaps in processing (missing entities, missing indexes, etc.)
2. Fixing those gaps using the same pipeline steps
3. Respecting feature flags (HAVE_AFM_FETCH_JOB, INDEX_THE_OPENSEARCH)
4. Providing dry-run mode for safe testing

Use cases:
- After enabling a feature flag that was previously disabled
- After fixing bugs in pipeline steps
- After infrastructure failures during batch imports
- Regular maintenance to ensure data quality

Example usage:
    service = DecisionHealthGuaranteeService()

    # Check what would be fixed (safe)
    results = service.ensure_all_decisions_health(dry_run=True)

    # Actually fix the gaps
    results = service.ensure_all_decisions_health(dry_run=False)
"""

import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from core.services.decision_health_service import DecisionHealthService, HealthStatus
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from loguru import logger


class DecisionHealthGuaranteeService:
    """
    Ensures data consistency across all decisions by detecting and fixing gaps
    in processing that may have occurred due to:
    - Feature flags being disabled during initial import
    - Code bugs in specific pipeline steps
    - Infrastructure failures during processing
    - Schema changes requiring backfills
    """

    def __init__(self):
        self.orchestrator = DecisionPipelineOrchestrator()
        self.health_service = DecisionHealthService()

    def _log_sample_adas(
        self, queryset, total_count: int, item_type: str = "decisions"
    ):
        """
        Helper to log a sample of ADAs (first 3 and last 3).

        Args:
            queryset: Django queryset containing decisions
            total_count: Total count of items
            item_type: What we're showing (decisions, entities, etc.)
        """
        if total_count == 0:
            return

        # Get first 3
        first_items = list(queryset[:3].values_list("ada", flat=True))

        # Get last 3 (if more than 3 total)
        if total_count > 3:
            last_items = list(
                queryset[max(0, total_count - 3) :].values_list("ada", flat=True)
            )
        else:
            last_items = []

        logger.info(f"  Sample {item_type}:")
        for ada in first_items:
            logger.info(f"    • {ada}")

        if total_count > 6:
            logger.info(f"    ... ({total_count - 6} more) ...")

        for ada in last_items:
            logger.info(f"    • {ada}")

    def _log_sample_afms(self, queryset, total_count: int):
        """
        Helper to log a sample of AFMs (first 3 and last 3).

        Args:
            queryset: Django queryset containing AFMEntity objects
            total_count: Total count of entities
        """
        if total_count == 0:
            return

        # Get first 3 with name
        first_items = list(queryset[:3].values("afm", "name"))

        # Get last 3 (if more than 3 total)
        if total_count > 3:
            last_items = list(queryset[max(0, total_count - 3) :].values("afm", "name"))
        else:
            last_items = []

        logger.info(f"  Sample entities:")
        for item in first_items:
            name = item["name"] or "Unknown"
            logger.info(f"    • AFM: {item['afm']} ({name})")

        if total_count > 6:
            logger.info(f"    ... ({total_count - 6} more) ...")

        for item in last_items:
            name = item["name"] or "Unknown"
            logger.info(f"    • AFM: {item['afm']} ({name})")

    def _log_sample_documents(self, queryset, total_count: int):
        """
        Helper to log a sample of document extractions (first 3 and last 3).

        Args:
            queryset: Django queryset containing DocumentExtraction objects
            total_count: Total count of documents
        """
        if total_count == 0:
            return

        # Get first 3
        first_items = list(queryset.select_related("decision")[:3])

        # Get last 3 (if more than 3 total)
        if total_count > 3:
            last_items = list(
                queryset.select_related("decision")[max(0, total_count - 3) :]
            )
        else:
            last_items = []

        logger.info(f"  Sample documents:")
        for extraction in first_items:
            text_len = len(extraction.raw_text or "")
            logger.info(
                f"    • {extraction.decision.ada} "
                f"({text_len:,} chars, {extraction.decision.issue_date})"
            )

        if total_count > 6:
            logger.info(f"    ... ({total_count - 6} more) ...")

        for extraction in last_items:
            text_len = len(extraction.raw_text or "")
            logger.info(
                f"    • {extraction.decision.ada} "
                f"({text_len:,} chars, {extraction.decision.issue_date})"
            )

    def ensure_organization_resolution(
        self,
        batch_size: int = 100,
        max_workers: int = 5,
        dry_run: bool = False,
        decision_adas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Find all decisions with unresolved organizations and resolve them.

        This checks for:
        - Signers without organization_id
        - Units without organization_id

        Args:
            batch_size: Number of decisions to process per batch
            max_workers: Number of parallel workers
            dry_run: If True, only report what would be done
            decision_adas: Optional list of specific ADAs to check

        Returns:
            Dictionary with processing results
        """
        logger.info("[SCAN] Checking for decisions with unresolved organizations...")

        # Find decisions where signers or units lack organization
        base_query = Decision.objects.filter(
            Q(signers__organization_id__isnull=True)
            | Q(units__organization_id__isnull=True)
        ).distinct()

        if decision_adas:
            base_query = base_query.filter(ada__in=decision_adas)

        decisions_needing_resolution = base_query.order_by("-issue_date")
        total_missing = decisions_needing_resolution.count()

        if total_missing == 0:
            logger.info("[OK] All decisions have resolved organizations")
            return {
                "status": "completed",
                "total_missing": 0,
                "resolved": 0,
                "errors": [],
            }

        logger.warning(
            f"[WARN]️ Found {total_missing} decisions with unresolved organizations"
        )
        self._log_sample_adas(decisions_needing_resolution, total_missing)  # Add this

        if dry_run:
            # Get detailed breakdown
            sample = list(
                decisions_needing_resolution.values(
                    "ada", "issue_date", "organization__label"
                )[:10]
            )

            signers_without_org = decisions_needing_resolution.filter(
                signers__organization_id__isnull=True
            ).count()
            units_without_org = decisions_needing_resolution.filter(
                units__organization_id__isnull=True
            ).count()

            return {
                "status": "dry_run",
                "total_missing": total_missing,
                "signers_without_org": signers_without_org,
                "units_without_org": units_without_org,
                "sample_decisions": sample,
                "message": f"Would resolve organizations for {total_missing} decisions",
            }

        results = {"total_missing": total_missing, "resolved": 0, "errors": []}

        # Process in batches
        for batch_start in range(0, total_missing, batch_size):
            batch = decisions_needing_resolution[batch_start : batch_start + batch_size]

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._resolve_organizations_safe, decision
                    ): decision.ada
                    for decision in batch
                }

                for future in as_completed(futures):
                    ada = futures[future]
                    try:
                        result = future.result()
                        if result["success"]:
                            results["resolved"] += 1
                        else:
                            results["errors"].append(
                                {"ada": ada, "error": result.get("error")}
                            )
                    except Exception as e:
                        logger.error(f"Exception processing {ada}: {e}")
                        results["errors"].append({"ada": ada, "error": str(e)})

            logger.info(
                f"Organization resolution progress: {batch_start + len(batch)}/{total_missing} "
                f"({results['resolved']} successful, {len(results['errors'])} errors)"
            )

        logger.info(
            f"[OK] Organization resolution guarantee completed: "
            f"{results['resolved']}/{total_missing} successful, "
            f"{len(results['errors'])} errors"
        )

        return results

    def _resolve_organizations_safe(self, decision: Decision) -> Dict[str, Any]:
        """Safely resolve organizations for a single decision."""
        try:
            health_check = self.orchestrator.get_or_create_health_check(decision)
            self.orchestrator._step_resolve_organizations(decision, health_check)
            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to resolve organizations for {decision.ada}: {e}")
            return {"success": False, "error": str(e)}

    def ensure_entity_extraction(
        self,
        batch_size: int = 100,
        max_workers: int = 5,
        dry_run: bool = False,
        decision_adas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Find all decisions without entity relationships and extract them.

        Note: This also handles amount extraction since amounts depend on entities.
        The DecisionAmountField.associated_relationship FK links amounts to entities,
        so both must be extracted together.

        Args:
            batch_size: Number of decisions to process per batch
            max_workers: Number of parallel workers
            dry_run: If True, only report what would be done
            decision_adas: Optional list of specific ADAs to check

        Returns:
            Dictionary with processing results
        """
        logger.info("[SCAN] Checking for decisions missing entity extraction...")

        # Find decisions without any entity relationships
        base_query = Decision.objects.annotate(
            has_entities=Exists(
                DecisionEntityRelationship.objects.filter(decision=OuterRef("pk"))
            ),
            has_amounts=Exists(
                DecisionAmountField.objects.filter(decision=OuterRef("pk"))
            ),
        ).filter(Q(has_entities=False) | Q(has_amounts=False))

        if decision_adas:
            base_query = base_query.filter(ada__in=decision_adas)

        decisions_without_entities = base_query.order_by("-issue_date")
        total_missing = decisions_without_entities.count()

        if total_missing == 0:
            logger.info("[OK] All decisions have entity and amount extraction")
            return {
                "status": "completed",
                "total_missing": 0,
                "processed": 0,
                "errors": [],
            }

        logger.warning(
            f"[WARN]️ Found {total_missing} decisions without entity/amount extraction"
        )
        self._log_sample_adas(decisions_without_entities, total_missing)  # Add this

        if dry_run:
            # Get detailed breakdown
            sample = list(
                decisions_without_entities.annotate(
                    entity_count=Count("entity_relationships"),
                    amount_count=Count("amount_fields"),
                ).values("ada", "issue_date", "entity_count", "amount_count")[:10]
            )

            return {
                "status": "dry_run",
                "total_missing": total_missing,
                "sample_decisions": sample,
                "message": f"Would process {total_missing} decisions for entity/amount extraction",
            }

        results = {"total_missing": total_missing, "processed": 0, "errors": []}

        # Process in batches with parallel execution
        for batch_start in range(0, total_missing, batch_size):
            batch = decisions_without_entities[batch_start : batch_start + batch_size]

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        self._extract_entities_and_amounts_safe, decision
                    ): decision.ada
                    for decision in batch
                }

                for future in as_completed(futures):
                    ada = futures[future]
                    try:
                        result = future.result()
                        if result["success"]:
                            results["processed"] += 1
                            logger.debug(
                                f"[OK] {ada}: {result.get('entities_found', 0)} entities, "
                                f"{result.get('amounts_found', 0)} amounts"
                            )
                        else:
                            results["errors"].append(
                                {"ada": ada, "error": result.get("error")}
                            )
                    except Exception as e:
                        logger.error(f"Exception processing {ada}: {e}")
                        results["errors"].append({"ada": ada, "error": str(e)})

            logger.info(
                f"Entity extraction progress: {batch_start + len(batch)}/{total_missing} "
                f"({results['processed']} successful, {len(results['errors'])} errors)"
            )

        logger.info(
            f"[OK] Entity extraction guarantee completed: "
            f"{results['processed']}/{total_missing} successful, "
            f"{len(results['errors'])} errors"
        )

        return results

    def _extract_entities_and_amounts_safe(self, decision: Decision) -> Dict[str, Any]:
        """Safely extract entities and amounts for a single decision."""
        try:
            health_check = self.orchestrator.get_or_create_health_check(decision)

            # Use the unified extraction method
            self.orchestrator._step_extract_entities_and_amounts(decision, health_check)

            # Count what we found
            entities_found = decision.entity_relationships.count()
            amounts_found = decision.amount_fields.count()

            return {
                "success": True,
                "entities_found": entities_found,
                "amounts_found": amounts_found,
            }
        except Exception as e:
            logger.error(f"Failed to extract entities/amounts for {decision.ada}: {e}")
            return {"success": False, "error": str(e)}

    def ensure_company_enrichment(
        self,
        batch_size: int = 100,
        dry_run: bool = False,
        afm_list: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Find all AFMEntity records without company data and queue them for enrichment.

        This respects the HAVE_AFM_FETCH_JOB feature flag and uses Redis locks
        to avoid duplicate API calls.

        Args:
            batch_size: Number of AFMs to queue per batch
            dry_run: If True, only report what would be done
            afm_list: Optional list of specific AFMs to enrich

        Returns:
            Dictionary with processing results
        """
        logger.info("[SCAN] Checking for entities missing company data...")

        # Find entities that haven't been attempted yet
        base_query = AFMEntity.objects.filter(gemi_lookup_attempted__isnull=True)

        if afm_list:
            base_query = base_query.filter(afm__in=afm_list)

        entities_needing_lookup = base_query.order_by("-first_seen")
        total_missing = entities_needing_lookup.count()

        # Check feature flag AFTER counting (so we can report what would be done)
        if not settings.HAVE_AFM_FETCH_JOB:
            logger.warning(
                f"[WARN]️ Found {total_missing} entities needing enrichment, "
                f"but HAVE_AFM_FETCH_JOB is disabled"
            )
            self._log_sample_afms(entities_needing_lookup, total_missing)  # Add this

            if dry_run:
                sample = list(
                    entities_needing_lookup.values("afm", "name", "first_seen")[:10]
                )
                return {
                    "status": "skipped",
                    "message": "Company enrichment disabled (HAVE_AFM_FETCH_JOB=False)",
                    "total_missing": total_missing,
                    "sample_entities": sample,
                    "would_process_if_enabled": total_missing,
                }

            return {
                "status": "skipped",
                "message": "Company enrichment disabled (HAVE_AFM_FETCH_JOB=False)",
                "total_missing": total_missing,
            }

        if total_missing == 0:
            logger.info("[OK] All entities have been attempted for company enrichment")
            return {"status": "completed", "total_missing": 0, "queued": 0}

        logger.warning(
            f"[WARN]️ Found {total_missing} entities needing company enrichment"
        )
        self._log_sample_afms(entities_needing_lookup, total_missing)  # Add this

        if dry_run:
            sample = list(
                entities_needing_lookup.values("afm", "name", "first_seen")[:10]
            )
            return {
                "status": "dry_run",
                "total_missing": total_missing,
                "sample_entities": sample,
                "message": f"Would queue {total_missing} AFMs for enrichment",
            }

        # Queue AFMs in batches to avoid overwhelming the task queue
        from api.redis_keys import AFM_FETCH_LOCK_PREFIX, AFM_FETCH_LOCK_TIMEOUT
        from core.tasks.tasks_entities import fetch_company_data_for_entities
        from django_redis import get_redis_connection

        redis_client = get_redis_connection("default")
        lock_owner = f"health_guarantee_{uuid.uuid4().hex[:8]}"

        queued = 0
        already_locked = 0

        for batch_start in range(0, total_missing, batch_size):
            batch = entities_needing_lookup[batch_start : batch_start + batch_size]
            afms = list(batch.values_list("afm", flat=True))

            # Try to acquire locks
            afms_to_queue = []
            for afm in afms:
                key = f"{AFM_FETCH_LOCK_PREFIX}{afm}"
                acquired = redis_client.set(
                    key, lock_owner, nx=True, ex=AFM_FETCH_LOCK_TIMEOUT
                )
                if acquired:
                    afms_to_queue.append(afm)
                else:
                    already_locked += 1

            if afms_to_queue:
                fetch_company_data_for_entities.delay(
                    afms_to_queue,
                    parent_task_id=f"health_guarantee_{batch_start}",
                    parent_ada="health_guarantee_batch",
                    lock_owner=lock_owner,
                )
                queued += len(afms_to_queue)

            logger.info(
                f"Company enrichment progress: {batch_start + len(batch)}/{total_missing} "
                f"(queued {queued}, skipped {already_locked} already processing)"
            )

        logger.info(
            f"[OK] Company enrichment guarantee completed: "
            f"queued {queued}/{total_missing} AFMs "
            f"(skipped {already_locked} already in progress)"
        )

        return {
            "status": "completed",
            "total_missing": total_missing,
            "queued": queued,
            "already_locked": already_locked,
        }

    def ensure_opensearch_indexing(
        self,
        batch_size: int = 50,
        max_workers: int = 3,
        dry_run: bool = False,
        decision_adas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Find all completed document extractions that aren't indexed in OpenSearch.

        This respects the INDEX_THE_OPENSEARCH feature flag and checks the actual
        OpenSearch index to determine what's missing.

        Args:
            batch_size: Number of documents to process per batch
            max_workers: Number of parallel workers for indexing
            dry_run: If True, only report what would be done
            decision_adas: Optional list of specific ADAs to check

        Returns:
            Dictionary with processing results
        """
        logger.info("[SCAN] Checking for documents missing OpenSearch indexing...")

        # Find completed extractions with actual text content
        base_query = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .select_related("decision")
        )

        if decision_adas:
            base_query = base_query.filter(decision__ada__in=decision_adas)

        completed_extractions = base_query.order_by("-created_at")
        total_extractions = completed_extractions.count()

        # Check feature flag AFTER counting (so we can report what would be done)
        if not settings.INDEX_THE_OPENSEARCH:
            logger.warning(
                f"[WARN]️ Found {total_extractions} completed document extractions, "
                f"but INDEX_THE_OPENSEARCH is disabled"
            )
            self._log_sample_documents(
                completed_extractions, total_extractions
            )  # Add this

            if dry_run:
                sample = [
                    {
                        "ada": e.decision.ada,
                        "issue_date": str(e.decision.issue_date),
                        "text_length": len(e.raw_text or ""),
                        "created_at": str(e.created_at),
                    }
                    for e in completed_extractions[:10]
                ]

                return {
                    "status": "skipped",
                    "message": "OpenSearch indexing disabled (INDEX_THE_OPENSEARCH=False)",
                    "total_extractions": total_extractions,
                    "sample_documents": sample,
                    "would_check_if_enabled": total_extractions,
                    "note": "Would check which of these are missing from OpenSearch index",
                }

            return {
                "status": "skipped",
                "message": "OpenSearch indexing disabled (INDEX_THE_OPENSEARCH=False)",
                "total_extractions": total_extractions,
            }

        # Feature flag is enabled, proceed with actual OpenSearch checks
        from core.services.opensearch_service import OpenSearchService

        search_service = OpenSearchService()

        logger.info(
            f"Checking index status for {total_extractions} completed extractions..."
        )

        missing_indexes = []
        check_errors = []

        for extraction in completed_extractions:
            try:
                if settings.INDEX_THE_OPENSEARCH:
                    is_indexed = search_service.document_exists(extraction.decision.id)
                    if not is_indexed:
                        missing_indexes.append(extraction)
                else:
                    logger.debug(
                        f"Skipping OpenSearch check due to INDEX_THE_OPENSEARCH feature flag set to {settings.INDEX_THE_OPENSEARCH}"
                    )
            except Exception as e:
                logger.warning(
                    f"Could not check index status for {extraction.decision.ada}: {e}"
                )
                check_errors.append({"ada": extraction.decision.ada, "error": str(e)})
                # Assume not indexed if we can't check
                missing_indexes.append(extraction)

        total_missing = len(missing_indexes)

        if total_missing == 0:
            logger.info("[OK] All documents are indexed in OpenSearch")
            return {
                "status": "completed",
                "total_missing": 0,
                "indexed": 0,
                "check_errors": check_errors,
            }

        logger.warning(
            f"[WARN]️ Found {total_missing} documents missing from OpenSearch"
        )
        # Log samples using a temporary queryset-like list
        if missing_indexes:
            logger.info(f"  Sample documents:")
            for extraction in missing_indexes[:3]:
                text_len = len(extraction.raw_text or "")
                logger.info(
                    f"    • {extraction.decision.ada} "
                    f"({text_len:,} chars, {extraction.decision.issue_date})"
                )

            if total_missing > 6:
                logger.info(f"    ... ({total_missing - 6} more) ...")

            for extraction in missing_indexes[-3:] if total_missing > 3 else []:
                text_len = len(extraction.raw_text or "")
                logger.info(
                    f"    • {extraction.decision.ada} "
                    f"({text_len:,} chars, {extraction.decision.issue_date})"
                )

        if dry_run:
            sample = [
                {
                    "ada": e.decision.ada,
                    "issue_date": str(e.decision.issue_date),
                    "text_length": len(e.raw_text or ""),
                    "created_at": str(e.created_at),
                }
                for e in missing_indexes[:10]
            ]

            return {
                "status": "dry_run",
                "total_missing": total_missing,
                "sample_documents": sample,
                "check_errors": check_errors,
                "message": f"Would index {total_missing} documents",
            }

        results = {
            "total_missing": total_missing,
            "indexed": 0,
            "errors": [],
            "check_errors": check_errors,
        }

        # Index in parallel (but with limited workers to avoid overwhelming OpenSearch)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    self._index_document_safe, extraction
                ): extraction.decision.ada
                for extraction in missing_indexes
            }

            for future in as_completed(futures):
                ada = futures[future]
                try:
                    result = future.result()
                    if result["success"]:
                        results["indexed"] += 1
                        if results["indexed"] % 10 == 0:
                            logger.info(
                                f"OpenSearch indexing progress: {results['indexed']}/{total_missing}"
                            )
                    else:
                        results["errors"].append(
                            {"ada": ada, "error": result.get("error")}
                        )
                except Exception as e:
                    logger.error(f"Exception indexing {ada}: {e}")
                    results["errors"].append({"ada": ada, "error": str(e)})

        logger.info(
            f"[OK] OpenSearch indexing guarantee completed: "
            f"{results['indexed']}/{total_missing} successful, "
            f"{len(results['errors'])} errors"
        )

        return results

    def _index_document_safe(self, extraction: DocumentExtraction) -> Dict[str, Any]:
        """Safely index a single document."""
        try:
            decision = extraction.decision
            health_check = self.orchestrator.get_or_create_health_check(decision)

            self.orchestrator._step_index_opensearch(decision, health_check)

            return {"success": True}
        except Exception as e:
            logger.error(f"Failed to index {extraction.decision.ada}: {e}")
            return {"success": False, "error": str(e)}

    def ensure_all_decisions_health(
        self,
        max_workers: int = 5,
        dry_run: bool = False,
        decision_adas: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Master method that runs all guarantee checks in sequence.

        This ensures complete data consistency across the entire database by running
        all health checks in the correct order:

        1. Organization Resolution (foundation for everything else)
        2. Entity & Amount Extraction (depends on organizations)
        3. Company Enrichment (enriches extracted entities)
        4. OpenSearch Indexing (final searchability layer)

        Args:
            max_workers: Number of parallel workers for each step
            dry_run: If True, only report what would be done without making changes
            decision_adas: Optional list of specific ADAs to check (for targeted fixes)

        Returns:
            Dictionary with results from all steps
        """
        logger.info("=" * 80)
        logger.info("[HEALTH] Starting comprehensive health guarantee check")
        logger.info("=" * 80)

        if dry_run:
            logger.info("[SCAN] DRY RUN MODE - No changes will be made")

        if decision_adas:
            logger.info(f"[TARGET] Targeting {len(decision_adas)} specific decisions")

        results = {
            "started_at": timezone.now().isoformat(),
            "dry_run": dry_run,
            "targeted_adas": decision_adas,
            "steps": {},
        }

        # Step 1: Organization Resolution (must come first)
        logger.info("\n" + "=" * 80)
        logger.info("[COPY] STEP 1/4: Organization Resolution")
        logger.info("=" * 80)
        results["steps"]["organization_resolution"] = (
            self.ensure_organization_resolution(
                max_workers=max_workers, dry_run=dry_run, decision_adas=decision_adas
            )
        )

        # Step 2: Entity & Amount Extraction (must come before company enrichment)
        logger.info("\n" + "=" * 80)
        logger.info("[CORP] STEP 2/4: Entity & Amount Extraction")
        logger.info("=" * 80)
        results["steps"]["entity_extraction"] = self.ensure_entity_extraction(
            max_workers=max_workers, dry_run=dry_run, decision_adas=decision_adas
        )

        # Step 3: Company Enrichment (enriches entities found in step 2)
        logger.info("\n" + "=" * 80)
        logger.info("[BIZ] STEP 3/4: Company Enrichment")
        logger.info("=" * 80)

        # If targeting specific decisions, extract their AFMs
        afm_list = None
        if decision_adas:
            afm_list = list(
                DecisionEntityRelationship.objects.filter(
                    decision__ada__in=decision_adas
                )
                .values_list("entity__afm", flat=True)
                .distinct()
            )
            logger.info(
                f"Targeting {len(afm_list)} unique AFMs from specified decisions"
            )

        results["steps"]["company_enrichment"] = self.ensure_company_enrichment(
            dry_run=dry_run, afm_list=afm_list
        )

        # Step 4: OpenSearch Indexing (final searchability layer)
        logger.info("\n" + "=" * 80)
        logger.info("[SCAN] STEP 4/4: OpenSearch Indexing")
        logger.info("=" * 80)
        results["steps"]["opensearch_indexing"] = self.ensure_opensearch_indexing(
            max_workers=max_workers, dry_run=dry_run, decision_adas=decision_adas
        )

        results["completed_at"] = timezone.now().isoformat()

        # Generate summary
        logger.info("\n" + "=" * 80)
        logger.info("[OK] Comprehensive health guarantee check completed")
        logger.info("=" * 80)

        self._log_summary(results)

        return results

    def _log_summary(self, results: Dict[str, Any]):
        """Log a nice summary of the health guarantee run."""
        steps = results["steps"]

        logger.info("\n[CHART] SUMMARY:")
        logger.info("-" * 80)

        # Organization Resolution
        org_step = steps.get("organization_resolution", {})
        if org_step.get("status") != "skipped":
            logger.info(
                f"  Organizations:  {org_step.get('resolved', 0)}/{org_step.get('total_missing', 0)} resolved"
            )

        # Entity Extraction
        entity_step = steps.get("entity_extraction", {})
        if entity_step.get("status") != "skipped":
            logger.info(
                f"  Entities:       {entity_step.get('processed', 0)}/{entity_step.get('total_missing', 0)} extracted"
            )

        # Company Enrichment
        company_step = steps.get("company_enrichment", {})
        if company_step.get("status") == "skipped":
            total = company_step.get("total_missing", 0)
            if total > 0:
                logger.warning(
                    f"  Companies:      Skipped (feature flag disabled) - "
                    f"{total} entities would be enriched if enabled"
                )
            else:
                logger.info(f"  Companies:      Skipped (feature flag disabled)")
        else:
            logger.info(
                f"  Companies:      {company_step.get('queued', 0)}/{company_step.get('total_missing', 0)} queued"
            )

        # OpenSearch
        search_step = steps.get("opensearch_indexing", {})
        if search_step.get("status") == "skipped":
            total_extractions = search_step.get("total_extractions", 0)
            if total_extractions > 0:
                logger.warning(
                    f"  OpenSearch:     Skipped (feature flag disabled) - "
                    f"{total_extractions} documents would be checked if enabled"
                )
            else:
                logger.info(f"  OpenSearch:     Skipped (feature flag disabled)")
        else:
            logger.info(
                f"  OpenSearch:     {search_step.get('indexed', 0)}/{search_step.get('total_missing', 0)} indexed"
            )

        logger.info("-" * 80)

        # Error summary
        total_errors = sum(len(step.get("errors", [])) for step in steps.values())
        if total_errors > 0:
            logger.warning(f"[WARN]️  Total errors encountered: {total_errors}")
        else:
            logger.info("[OK]  No errors encountered")

    def ensure_health_for_unhealthy_decisions(
        self,
        max_workers: int = 5,
        dry_run: bool = False,
        component_filter: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Find decisions with health issues and fix them.

        This uses DecisionHealthService to identify problems, then fixes them.
        More targeted than scanning all decisions - only fixes known issues.

        Args:
            max_workers: Number of parallel workers
            dry_run: If True, only report what would be done
            component_filter: Only fix specific component ('entities', 'opensearch', etc.)

        Returns:
            Dictionary with processing results
        """
        logger.info("[SCAN] Finding decisions with health issues...")

        # Get problematic decisions from health service
        if component_filter:
            problematic = self.health_service.get_problematic_decisions(
                limit=1000, component=component_filter, status_filter=HealthStatus.ERROR
            )
        else:
            problematic = self.health_service.get_problematic_decisions(limit=1000)

        if not problematic:
            logger.info("[OK] No problematic decisions found")
            return {"status": "completed", "total_found": 0, "fixed": 0}

        logger.warning(f"[WARN]️ Found {len(problematic)} decisions with issues")

        # Group by component that needs fixing
        needs_organization = []
        needs_entities = []
        needs_opensearch = []

        for health_check in problematic:
            if health_check.organization_status in [
                HealthStatus.ERROR,
                HealthStatus.WARNING,
            ]:
                needs_organization.append(health_check.decision.ada)
            if health_check.entities_status in [
                HealthStatus.ERROR,
                HealthStatus.WARNING,
            ]:
                needs_entities.append(health_check.decision.ada)
            if health_check.opensearch_status in [
                HealthStatus.ERROR,
                HealthStatus.WARNING,
            ]:
                needs_opensearch.append(health_check.decision.ada)

        if dry_run:
            return {
                "status": "dry_run",
                "total_found": len(problematic),
                "needs_organization": len(needs_organization),
                "needs_entities": len(needs_entities),
                "needs_opensearch": len(needs_opensearch),
                "sample_adas": [hc.decision.ada for hc in problematic[:10]],
                "message": f"Would fix {len(problematic)} decisions with health issues",
            }

        results = {"total_found": len(problematic), "steps": {}}

        # Fix organizations if needed
        if needs_organization and (
            not component_filter or component_filter == "organization"
        ):
            logger.info(
                f"\n[COPY] Fixing {len(needs_organization)} decisions with organization issues"
            )
            results["steps"]["organization"] = self.ensure_organization_resolution(
                max_workers=max_workers, decision_adas=needs_organization
            )

        # Fix entities if needed
        if needs_entities and (not component_filter or component_filter == "entities"):
            logger.info(
                f"\n[CORP] Fixing {len(needs_entities)} decisions with entity issues"
            )
            results["steps"]["entities"] = self.ensure_entity_extraction(
                max_workers=max_workers, decision_adas=needs_entities
            )

            # Queue company enrichment for newly extracted entities
            if results["steps"]["entities"].get("processed", 0) > 0:
                logger.info(
                    "\n[BIZ] Queueing company enrichment for newly extracted entities"
                )
                afm_list = list(
                    DecisionEntityRelationship.objects.filter(
                        decision__ada__in=needs_entities
                    )
                    .values_list("entity__afm", flat=True)
                    .distinct()
                )
                results["steps"]["company_enrichment"] = self.ensure_company_enrichment(
                    afm_list=afm_list
                )

        # Fix OpenSearch if needed
        if needs_opensearch and (
            not component_filter or component_filter == "opensearch"
        ):
            logger.info(
                f"\n[SCAN] Fixing {len(needs_opensearch)} decisions with OpenSearch issues"
            )
            results["steps"]["opensearch"] = self.ensure_opensearch_indexing(
                max_workers=max_workers, decision_adas=needs_opensearch
            )

        # Re-check health to verify fixes
        logger.info("\n[HEALTH] Re-checking health to verify fixes...")
        fixed_count = 0
        still_broken = []

        for health_check in problematic:
            updated_health = self.health_service.check_decision_health(
                health_check.decision, force_refresh=True
            )

            if updated_health.overall_status == HealthStatus.HEALTHY:
                fixed_count += 1
            elif updated_health.overall_status in [
                HealthStatus.ERROR,
                HealthStatus.WARNING,
            ]:
                still_broken.append(
                    {
                        "ada": updated_health.decision.ada,
                        "status": updated_health.overall_status,
                        "issues": updated_health.get_issue_summary(),
                    }
                )

        results["fixed"] = fixed_count
        results["still_broken"] = still_broken

        logger.info(
            f"\n[OK] Health-based guarantee completed: "
            f"{fixed_count}/{len(problematic)} decisions now healthy, "
            f"{len(still_broken)} still have issues"
        )

        return results
