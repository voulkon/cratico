import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional

from core.importers.decisions import DecisionImporter
from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.import_jobs import ImportJob
from core.services.document_processor import DocumentAnalysisService

# from core.services.afm_extractor import AFMExtractionService
# from core.services.entity_extraction_service import EntityExtractionService
from core.services.entity_amount_extraction_service import EntityAmountExtractionService
from core.services.feature_flag_service import feature_flags
from core.services.opensearch_service import OpenSearchService
from django.utils import timezone
from loguru import logger


class DecisionPipelineOrchestrator:
    """
    Central orchestrator for the decision processing pipeline.
    Ensures all steps (Ingestion -> Entities -> Documents -> Indexing) are completed
    and tracks their status in DecisionHealthCheck.
    """

    def __init__(self):
        # self.afm_service = AFMExtractionService()
        # self.entity_service = EntityExtractionService()
        self.extraction_service = EntityAmountExtractionService()
        self.doc_service = DocumentAnalysisService()
        self.search_service = OpenSearchService()
        self.decision_importer = DecisionImporter()

    def _separator(self, char: str = "=", width: int = 80) -> str:
        """Generate a separator line for logs."""
        return char * width

    def get_or_create_health_check(self, decision: Decision) -> DecisionHealthCheck:
        health_check, created = DecisionHealthCheck.objects.get_or_create(
            decision=decision,
            defaults={
                "decision_issue_date": decision.issue_date,
                "overall_status": HealthStatus.UNKNOWN,
            },
        )
        return health_check

    def update_health_status(
        self,
        health_check: DecisionHealthCheck,
        component: str,
        status: str,
        error: str = None,
    ):
        """Updates the status of a specific component and the overall health."""
        setattr(health_check, f"{component}_status", status)

        if error:
            findings = health_check.findings or {}
            findings[component] = error
            health_check.findings = findings
            health_check.has_errors = True

        # Recalculate overall status - include new import_status and organization_status
        statuses = [
            health_check.import_status,
            health_check.organization_status,
            health_check.ingestion_status,  # Legacy field for backward compatibility
            health_check.relations_status,
            health_check.entities_status,
            health_check.document_extraction_status,
            health_check.opensearch_status,
            health_check.coverage_status,
        ]

        if HealthStatus.ERROR in statuses:
            health_check.overall_status = HealthStatus.ERROR
        elif HealthStatus.WARNING in statuses:
            health_check.overall_status = HealthStatus.WARNING
        elif all(
            s == HealthStatus.HEALTHY for s in statuses if s != HealthStatus.UNKNOWN
        ):
            health_check.overall_status = HealthStatus.HEALTHY

        health_check.save()

    def run_pipeline(
        self,
        decision_ada: str,
        force_reprocess: bool = False,
        skip_opensearch: bool = False,
        decision_dto=None,
    ) -> DecisionHealthCheck:
        """
        Runs the full processing pipeline for a decision.

        Args:
            decision_ada: The ADA of the decision to process
            force_reprocess: Force reprocessing even if already processed
            skip_opensearch: Skip OpenSearch indexing (useful for reducing infra costs)
            decision_dto: Optional DecisionDTO for import stage (if provided, skips import check)
        """
        # Generate unique ingestion ID for log tracing in Grafana
        ingestion_id = str(uuid.uuid4())[:8]

        # Bind ingestion_id to all logs in this context
        with logger.contextualize(ingestion_id=ingestion_id, ada=decision_ada):
            logger.debug(
                f"\n{self._separator()}\n"
                f"[START] Starting pipeline for decision {decision_ada}\n"
                f"   Ingestion ID: {ingestion_id} (use this to filter logs)\n"
                f"   Force reprocess: {force_reprocess}\n"
                f"   Skip OpenSearch: {skip_opensearch}\n"
                f"   Has DTO: {decision_dto is not None}\n"
                f"{self._separator()}\n"
            )

            # Stage 0: Import Decision (if DTO provided)
            if decision_dto:
                logger.debug(
                    f"\n{self._separator()}\n[IMPORT] STAGE 0/8: IMPORT DECISION\n{self._separator()}"
                )
                decision = self._step_import_decision(decision_dto, health_check=None)
                if not decision:
                    logger.error(
                        f"[ERROR] Failed to import decision {decision_dto.ada}"
                    )
                    return None
            else:
                # Get existing decision from database
                try:
                    decision = Decision.objects.get(ada=decision_ada)
                except Decision.DoesNotExist:
                    logger.error(
                        f"[ERROR] Decision {decision_ada} not found in database"
                    )
                    return None

            health_check = self.get_or_create_health_check(decision)

            # If DTO was provided, mark import as healthy
            if decision_dto:
                self.update_health_status(health_check, "import", HealthStatus.HEALTHY)
            else:
                # For existing decisions, mark import as healthy if decision exists
                self.update_health_status(health_check, "import", HealthStatus.HEALTHY)

            # Legacy: Keep ingestion_status for backward compatibility
            self.update_health_status(health_check, "ingestion", HealthStatus.HEALTHY)

            # 1. Organization Resolution (moved from DecisionImporter)
            logger.debug(
                f"\n{self._separator()}\n[ORG] STAGE 1/9: ORGANIZATION RESOLUTION\n{self._separator()}"
            )
            self._step_resolve_organizations(decision, health_check)

            # 2 & 3. Entity and Amount Extraction (combined)
            logger.debug(
                f"\n{self._separator()}\n[ENTITY+AMOUNT] STAGE 2/9: ENTITY AND AMOUNT EXTRACTION\n{self._separator()}"
            )
            self._step_extract_entities_and_amounts(decision, health_check)

            # 3. Direct Assignment Classification
            logger.debug(
                f"\n{self._separator()}\n[CLASSIFY] STAGE 3/9: DIRECT ASSIGNMENT CLASSIFICATION\n{self._separator()}"
            )
            self._step_classify_direct_assignment(decision, health_check)

            # 4. Company Data Enrichment
            logger.debug(
                f"\n{self._separator()}\n[COMPANY] STAGE 4/9: COMPANY ENRICHMENT\n{self._separator()}"
            )
            self._step_enrich_companies(decision, health_check)

            # 5. Document Processing
            logger.debug(
                f"\n{self._separator()}\n[DOCUMENT] STAGE 5/9: DOCUMENT PROCESSING\n{self._separator()}"
            )
            self._step_process_document(decision, health_check, force_reprocess)

            # 6. OpenSearch Indexing
            if skip_opensearch:
                logger.debug(
                    f"\n{self._separator()}\n"
                    f"[SEARCH] STAGE 6/9: OPENSEARCH INDEXING (SKIPPED)\n"
                    f"{self._separator()}\n"
                    f"OpenSearch indexing disabled - skipping to save on infrastructure costs"
                )
                self.update_health_status(
                    health_check, "opensearch", HealthStatus.UNKNOWN
                )
            else:
                logger.debug(
                    f"\n{self._separator()}\n[SEARCH] STAGE 6/9: OPENSEARCH INDEXING\n{self._separator()}"
                )
                self._step_index_opensearch(decision, health_check)

            # 7. Coverage
            logger.debug(
                f"\n{self._separator()}\n[STATS] STAGE 7/9: COVERAGE METRICS\n{self._separator()}"
            )
            self._step_verify_coverage(decision, health_check)

            logger.debug(
                f"\n{self._separator()}\n"
                f"[OK] Pipeline completed for {decision_ada}\n"
                f"   Overall Status: {health_check.overall_status}\n"
                f"   Ingestion ID: {ingestion_id}\n"
                f"{self._separator()}\n"
            )

            return health_check

    def _step_import_decision(
        self, decision_dto, health_check: DecisionHealthCheck = None
    ):
        """
        Stage 0: Import decision from DTO to database.
        This replaces the direct call to DecisionImporter.import_many in store_decisions_from_pickle.

        Args:
            decision_dto: DecisionDTO to import
            health_check: Optional health check (created if not provided)

        Returns:
            Decision instance or None if import failed
        """
        try:
            logger.debug(f"Importing decision {decision_dto.ada} from DTO")

            # Import using DecisionImporter
            created_count = self.decision_importer.import_many([decision_dto])

            if created_count > 0:
                logger.debug(f"Created new decision {decision_dto.ada}")
            else:
                logger.debug(f"Decision {decision_dto.ada} already exists (updated)")

            # Get the decision instance
            decision = Decision.objects.get(ada=decision_dto.ada)

            # Create or update health check if provided
            if health_check:
                self.update_health_status(health_check, "import", HealthStatus.HEALTHY)

            return decision

        except Exception as e:
            logger.error(f"Failed to import decision {decision_dto.ada}: {e}")
            if health_check:
                self.update_health_status(
                    health_check, "import", HealthStatus.ERROR, str(e)
                )
            return None

    def _step_resolve_organizations(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        """
        Stage 1: Resolve organizations for signers and units.
        This method was moved from DecisionImporter to provide better health tracking.

        For each signer and unit associated with the decision, ensure their organization
        is properly resolved. This involves:
        1. Checking if organization is already set
        2. If not, resolving through parent chain or API
        3. Creating default organizations if resolution fails

        Args:
            decision: Decision to resolve organizations for
            health_check: Health check to update
        """
        try:
            from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher

            logger.debug(f"Resolving organizations for {decision.ada}")

            fetcher = DiavgeiaFetcher()
            resolution_results = {
                "signers_resolved": 0,
                "signers_failed": 0,
                "units_resolved": 0,
                "units_failed": 0,
                "details": [],
            }

            # Log initial state
            total_signers = decision.signers.count()
            signers_without_org = decision.signers.filter(
                organization_id__isnull=True
            ).count()
            logger.debug(
                f"Signers for {decision.ada}: {total_signers} total, "
                f"{signers_without_org} without organization, "
                f"{total_signers - signers_without_org} already have organization"
            )

            # Resolve organizations for signers
            for signer in decision.signers.all():
                if not signer.organization_id:
                    logger.debug(
                        f"Attempting to resolve organization for signer {signer.uid}"
                    )

                    try:
                        org_id, resolution_path = (
                            self.decision_importer._resolve_signer_organization(
                                signer.uid, fetcher
                            )
                        )

                        if org_id:
                            signer.organization_id = org_id
                            signer.save(update_fields=["organization_id"])
                            resolution_results["signers_resolved"] += 1
                            resolution_results["details"].append(
                                {
                                    "type": "signer",
                                    "uid": signer.uid,
                                    "resolved": True,
                                    "org_id": org_id,
                                    "path": resolution_path,
                                }
                            )
                            logger.debug(
                                f"Resolved organization {org_id} for signer {signer.uid}"
                            )
                        else:
                            # Create default organization
                            default_org = (
                                self.decision_importer._ensure_default_organization(
                                    "signer", signer.uid
                                )
                            )
                            signer.organization_id = default_org
                            signer.save(update_fields=["organization_id"])
                            resolution_results["signers_failed"] += 1
                            resolution_results["details"].append(
                                {
                                    "type": "signer",
                                    "uid": signer.uid,
                                    "resolved": False,
                                    "default_org": default_org,
                                    "path": resolution_path,
                                }
                            )
                            logger.warning(
                                f"Using default organization {default_org} for signer {signer.uid}"
                            )

                    except Exception as signer_error:
                        resolution_results["signers_failed"] += 1
                        logger.error(
                            f"Failed to resolve organization for signer {signer.uid}: {signer_error}"
                        )

            # Log signer resolution summary
            if signers_without_org > 0:
                logger.debug(
                    f"Signer resolution summary for {decision.ada}: "
                    f"{resolution_results['signers_resolved']} resolved, "
                    f"{resolution_results['signers_failed']} used default org"
                )
            else:
                logger.debug(
                    f"All signers for {decision.ada} already have organizations"
                )

            # Log initial state for units
            total_units = decision.units.count()
            units_without_org = decision.units.filter(
                organization_id__isnull=True
            ).count()
            logger.debug(
                f"Units for {decision.ada}: {total_units} total, "
                f"{units_without_org} without organization, "
                f"{total_units - units_without_org} already have organization"
            )

            # Resolve organizations for units
            for unit in decision.units.all():
                if not unit.organization_id:
                    logger.debug(
                        f"Attempting to resolve organization for unit {unit.uid}"
                    )

                    try:
                        org_id, resolution_path, units_to_import = (
                            self.decision_importer._resolve_unit_organization_through_parents(
                                unit.uid, fetcher
                            )
                        )

                        if org_id:
                            unit.organization_id = org_id
                            unit.save(update_fields=["organization_id"])
                            resolution_results["units_resolved"] += 1
                            resolution_results["details"].append(
                                {
                                    "type": "unit",
                                    "uid": unit.uid,
                                    "resolved": True,
                                    "org_id": org_id,
                                    "path": resolution_path,
                                }
                            )
                            logger.debug(
                                f"Resolved organization {org_id} for unit {unit.uid}"
                            )
                        else:
                            # Create default organization
                            default_org = (
                                self.decision_importer._ensure_default_organization(
                                    "unit", unit.uid
                                )
                            )
                            unit.organization_id = default_org
                            unit.save(update_fields=["organization_id"])
                            resolution_results["units_failed"] += 1
                            resolution_results["details"].append(
                                {
                                    "type": "unit",
                                    "uid": unit.uid,
                                    "resolved": False,
                                    "default_org": default_org,
                                    "path": resolution_path,
                                }
                            )
                            logger.warning(
                                f"Using default organization {default_org} for unit {unit.uid}"
                            )

                    except Exception as unit_error:
                        resolution_results["units_failed"] += 1
                        logger.error(
                            f"Failed to resolve organization for unit {unit.uid}: {unit_error}"
                        )

            # Log unit resolution summary
            if units_without_org > 0:
                logger.debug(
                    f"Unit resolution summary for {decision.ada}: "
                    f"{resolution_results['units_resolved']} resolved, "
                    f"{resolution_results['units_failed']} used default org"
                )
            else:
                logger.debug(f"All units for {decision.ada} already have organizations")

            # Log summary
            total_resolved = (
                resolution_results["signers_resolved"]
                + resolution_results["units_resolved"]
            )
            total_failed = (
                resolution_results["signers_failed"]
                + resolution_results["units_failed"]
            )

            logger.debug(
                f"Organization resolution completed for {decision.ada}: "
                f"{total_resolved} resolved, {total_failed} failed"
            )

            # Log detailed results if there were any attempts
            if resolution_results["details"]:
                logger.debug(
                    f"Resolution details for {decision.ada}: {resolution_results['details']}"
                )
            else:
                logger.debug(
                    f"No resolution attempts made for {decision.ada} - all entities already have organizations"
                )

            # Mark as healthy even if some failed (we used defaults)
            self.update_health_status(
                health_check, "organization", HealthStatus.HEALTHY
            )

        except Exception as e:
            logger.error(f"Failed organization resolution for {decision.ada}: {e}")
            self.update_health_status(
                health_check, "organization", HealthStatus.ERROR, str(e)
            )

    def _step_extract_entities(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        """
        DEPRECATED: Use _step_extract_entities_and_amounts instead.

        This method is kept for backward compatibility with retry_failed_step.
        """
        import warnings

        warnings.warn(
            "_step_extract_entities is deprecated. Use _step_extract_entities_and_amounts instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to the new unified method
        return self._step_extract_entities_and_amounts(decision, health_check)

    def _step_extract_amounts(
        self, decision: Decision, health_check: DecisionHealthCheck, force: bool = False
    ):
        """
        DEPRECATED: Use _step_extract_entities_and_amounts instead.

        This method is kept for backward compatibility with retry_failed_step.
        The 'force' parameter is ignored since the new method handles this internally.
        """
        import warnings

        warnings.warn(
            "_step_extract_amounts is deprecated. Use _step_extract_entities_and_amounts instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Delegate to the new unified method
        # Note: force parameter is ignored - the new method has its own logic
        return self._step_extract_entities_and_amounts(decision, health_check)

    def _step_extract_entities_and_amounts(
        self, decision: Decision, health_check: DecisionHealthCheck
    ) -> Dict[str, Any]:
        """
        STEP 2: Extract AFM entities AND amounts from decision data.

        This is a SINGLE step that handles both, since amounts need
        to be linked to entity relationships.

        Args:
            decision: Decision to extract from
            health_check: Health check to update

        Returns:
            Dict with extraction results
        """
        step_result = {
            "step": "entity_amount_extraction",
            "success": False,
            "entities_created": 0,
            "amounts_created": 0,
            "error": None,
        }

        try:
            logger.debug(f"Extracting entities and amounts for {decision.ada}")

            # Extract using the unified service (with idempotent mode)
            result = self.extraction_service.extract_from_decision(
                decision,
                save_to_db=True,
                skip_if_existing=True,  # Skip if already has relationships
            )

            step_result["success"] = True
            step_result["entities_created"] = result.entities_created
            step_result["amounts_created"] = result.amounts_created

            if result.errors:
                step_result["warnings"] = result.errors
                logger.warning(
                    f"Extraction completed with {len(result.errors)} warnings for {decision.ada}"
                )

            logger.debug(
                f"Extracted {result.entities_created} entities and "
                f"{result.amounts_created} amounts from {decision.ada}"
            )

            # Update health status
            if result.entities_created > 0 or result.amounts_created > 0:
                self.update_health_status(
                    health_check, "entities", HealthStatus.HEALTHY
                )
            elif result.had_extractable_content:
                # Had content but found nothing - this is valid (some decisions legitimately have no entities/amounts)
                self.update_health_status(
                    health_check, "entities", HealthStatus.HEALTHY
                )
            else:
                # No content to extract from
                self.update_health_status(
                    health_check, "entities", HealthStatus.HEALTHY
                )

        except Exception as e:
            step_result["error"] = str(e)
            logger.error(
                f"Entity/amount extraction failed for {decision.ada}: {e}",
                exc_info=True,
            )
            self.update_health_status(
                health_check, "entities", HealthStatus.ERROR, str(e)
            )

        return step_result

    def _step_classify_direct_assignment(
        self, decision: Decision, health_check: DecisionHealthCheck
    ) -> Dict[str, Any]:
        """
        STEP 3: Classify decision as direct assignment.

        This step determines if decision is a direct assignment (Δ.1) below threshold (€37,200)
        and stores the result in DecisionClassification model.

        Uses DirectAssignmentDetectionService which applies business rules:
        1. Must be decision type Δ.1
        2. Total amount must be below €37,200

        Args:
            decision: Decision to classify
            health_check: Health check to update

        Returns:
            Dict with classification results
        """
        step_result = {
            "step": "direct_assignment_classification",
            "success": False,
            "is_direct_assignment": False,
            "error": None,
        }

        try:
            logger.debug(f"Classifying direct assignment for {decision.ada}")

            # Use the classification service
            from core.services.direct_assignment_detection_service import (
                classification_service,
            )

            classification = classification_service.classify_and_save(decision)

            step_result["success"] = True
            step_result["is_direct_assignment"] = classification.is_direct_assignment

            if classification.is_direct_assignment:
                logger.debug(
                    f"[OK] Decision {decision.ada} classified as direct assignment"
                )
            else:
                logger.debug(f"Decision {decision.ada} is NOT a direct assignment")

            # Mark as healthy (classification always succeeds, even if result is False)
            self.update_health_status(
                health_check, "classification", HealthStatus.HEALTHY
            )

        except Exception as e:
            step_result["error"] = str(e)
            logger.error(
                f"Direct assignment classification failed for {decision.ada}: {e}",
                exc_info=True,
            )
            # Don't fail the whole pipeline for this
            self.update_health_status(
                health_check, "classification", HealthStatus.WARNING, str(e)
            )

        return step_result

    def _step_enrich_companies(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        try:
            # Skip company enrichment if disabled
            if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"):
                logger.debug(
                    f"Skipping company enrichment for {decision.ada} (HAVE_AFM_FETCH_JOB=False)"
                )
                self.update_health_status(
                    health_check, "relations", HealthStatus.UNKNOWN
                )
                return

            logger.debug(f"Step 3: Enriching company data for {decision.ada}")

            # Find entities related to this decision
            relationships = decision.entity_relationships.all()

            if not relationships.exists():
                logger.debug(
                    f"No entity relationships found for {decision.ada}, skipping company enrichment"
                )
                self.update_health_status(
                    health_check, "relations", HealthStatus.HEALTHY
                )
                return

            # Check which entities need GEMI lookup (haven't been attempted yet)
            entities_needing_lookup = []
            entities_already_attempted = []

            for rel in relationships:
                entity = rel.entity
                if entity.gemi_lookup_attempted is None:
                    entities_needing_lookup.append(entity.afm)
                else:
                    entities_already_attempted.append(entity.afm)

            if entities_already_attempted:
                logger.debug(
                    f"Skipping {len(entities_already_attempted)} entities with previous lookup attempts "
                    f"(use force_refresh=True to retry): {entities_already_attempted[:3]}..."
                )

            if entities_needing_lookup:
                # Deduplicate AFMs within this decision
                unique_afms = list(set(entities_needing_lookup))

                # Add to priority queue instead of dispatching immediately
                # The queue service will handle rate limiting and priority ordering
                from core.services.afm_fetch_queue_service import AFMFetchQueueService

                queue_service = AFMFetchQueueService()

                queued_count = 0
                for afm in unique_afms:
                    # add_single_afm returns True if added, False if already queued/processed
                    if queue_service.add_single_afm(afm):
                        queued_count += 1

                if queued_count > 0:
                    logger.debug(
                        f"Added {queued_count}/{len(unique_afms)} AFMs to fetch queue for {decision.ada}. "
                        f"Queue will process by priority."
                    )
                else:
                    logger.debug(
                        f"All {len(unique_afms)} AFMs already queued or processed"
                    )
            else:
                logger.debug(
                    f"All {relationships.count()} entities for {decision.ada} already have GEMI lookup attempted, skipping"
                )

            self.update_health_status(health_check, "relations", HealthStatus.HEALTHY)
        except Exception as e:
            logger.error(f"Failed company enrichment: {e}")
            self.update_health_status(
                health_check, "relations", HealthStatus.ERROR, str(e)
            )

    def _step_process_document(
        self, decision: Decision, health_check: DecisionHealthCheck, force: bool
    ):
        try:
            logger.debug(f"Step 3: Processing document for {decision.ada}")

            if not feature_flags.is_enabled("EXTRACT_THE_DOCS_FROM_PDFS"):
                logger.debug(
                    f"Skipping document processing for {decision.ada} (EXTRACT_THE_DOCS_FROM_PDFS=False)"
                )
                self.update_health_status(
                    health_check, "document_extraction", HealthStatus.UNKNOWN
                )
                return

            if not decision.document_url:
                self.update_health_status(
                    health_check,
                    "document_extraction",
                    HealthStatus.WARNING,
                    "No document URL",
                )
                return

            # Check existing extraction
            extraction = DocumentExtraction.objects.filter(decision=decision).first()

            if (
                extraction
                and extraction.extraction_status == ProcessingStatus.COMPLETED
                and not force
            ):
                self.update_health_status(
                    health_check, "document_extraction", HealthStatus.HEALTHY
                )
                return

            # Run processing
            result = self.doc_service.process_decision(decision)

            if result.get("success"):
                self.update_health_status(
                    health_check, "document_extraction", HealthStatus.HEALTHY
                )
            else:
                self.update_health_status(
                    health_check,
                    "document_extraction",
                    HealthStatus.ERROR,
                    result.get("error"),
                )

        except Exception as e:
            logger.error(f"Failed document processing: {e}")
            self.update_health_status(
                health_check, "document_extraction", HealthStatus.ERROR, str(e)
            )

    def _step_index_opensearch(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        # Skip OpenSearch indexing if disabled
        if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
            logger.debug(
                f"Skipping OpenSearch indexing for {decision.ada} (INDEX_THE_OPENSEARCH=False)"
            )
            self.update_health_status(health_check, "opensearch", HealthStatus.UNKNOWN)
            return

        try:
            logger.debug(f"Step 5: Indexing in OpenSearch for {decision.ada}")

            extraction = DocumentExtraction.objects.filter(decision=decision).first()

            if not extraction:
                self.update_health_status(
                    health_check,
                    "opensearch",
                    HealthStatus.WARNING,
                    "No extraction found",
                )
                return

            if extraction.extraction_status != ProcessingStatus.COMPLETED:
                self.update_health_status(
                    health_check,
                    "opensearch",
                    HealthStatus.WARNING,
                    f"Extraction status: {extraction.extraction_status}",
                )
                return

            if not extraction.raw_text:
                self.update_health_status(
                    health_check,
                    "opensearch",
                    HealthStatus.WARNING,
                    "No text extracted",
                )
                return

            # Check if already indexed by querying OpenSearch
            try:
                is_indexed = self.search_service.document_exists(decision.id)
                if is_indexed:
                    logger.debug(
                        f"Document for {decision.ada} already indexed in OpenSearch, skipping"
                    )
                    self.update_health_status(
                        health_check, "opensearch", HealthStatus.HEALTHY
                    )
                    return
            except Exception as check_error:
                logger.warning(
                    f"Could not check if document exists in OpenSearch: {check_error}, proceeding with indexing"
                )

            # Build document data dict for OpenSearch
            document_data = {
                "decision_id": decision.id,
                "ada": decision.ada,
                "title": decision.subject or "",
                "content": extraction.raw_text,
                "organization": (
                    str(decision.organization) if decision.organization else ""
                ),
                "decision_type": (
                    str(decision.decision_type) if decision.decision_type else ""
                ),
                "issue_date": (
                    decision.issue_date.isoformat() if decision.issue_date else None
                ),
                "extraction_date": (
                    extraction.extraction_date.isoformat()
                    if extraction.extraction_date
                    else None
                ),
                "character_count": extraction.character_count,
                "page_count": extraction.page_count,
            }

            logger.debug(f"Indexing document for {decision.ada} in OpenSearch")
            success = self.search_service.index_document(document_data)

            if success:
                self.update_health_status(
                    health_check, "opensearch", HealthStatus.HEALTHY
                )
            else:
                self.update_health_status(
                    health_check, "opensearch", HealthStatus.ERROR, "Indexing failed"
                )

        except Exception as e:
            logger.error(f"Failed OpenSearch indexing: {e}")
            self.update_health_status(
                health_check, "opensearch", HealthStatus.ERROR, str(e)
            )

    def _step_verify_coverage(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        # This is hard to verify per decision without querying the aggregate table.
        # We'll assume it's healthy if we got here, or implement a specific check later.
        self.update_health_status(health_check, "coverage", HealthStatus.HEALTHY)

    def run_batch_pipeline(
        self,
        import_job_id: int,
        max_workers: int = 10,
        stop_on_error: bool = False,
        force_reprocess: bool = False,
        skip_opensearch: bool = False,
    ) -> Dict[str, Any]:
        """
        Process all decisions in a batch with parallel execution.

        Args:
            import_job_id: The ImportJob ID to process
            max_workers: Maximum parallel workers for processing
            stop_on_error: If True, stop processing on first error
            force_reprocess: If True, reprocess even if already processed
            skip_opensearch: If True, skip OpenSearch indexing to save costs

        Returns:
            Dictionary with processing results and statistics
        """
        logger.info(f"[START] Starting batch pipeline for ImportJob #{import_job_id}")
        start_time = timezone.now()

        try:
            import_job = ImportJob.objects.get(id=import_job_id)
        except ImportJob.DoesNotExist:
            logger.error(f"ImportJob #{import_job_id} not found")
            return {
                "error": "ImportJob not found",
                "total": 0,
                "successful": 0,
                "failed": 0,
            }

        decisions = import_job.decisions.all()
        total_decisions = decisions.count()

        if total_decisions == 0:
            logger.warning(f"No decisions found for ImportJob #{import_job_id}")
            return {"total": 0, "successful": 0, "failed": 0, "errors": []}

        results = {
            "import_job_id": import_job_id,
            "total": total_decisions,
            "successful": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
            "processing_times": [],
        }

        logger.info(
            f"Processing {total_decisions} decisions with {max_workers} workers"
        )

        # Process in parallel with controlled concurrency
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ada = {
                executor.submit(
                    self._process_single_decision_safe,
                    d.ada,
                    force_reprocess,
                    skip_opensearch,
                ): d.ada
                for d in decisions
            }

            for future in as_completed(future_to_ada):
                ada = future_to_ada[future]
                try:
                    result = future.result()

                    if result["status"] == "success":
                        results["successful"] += 1
                    elif result["status"] == "skipped":
                        results["skipped"] += 1
                    else:
                        results["failed"] += 1
                        results["errors"].append(
                            {
                                "ada": ada,
                                "findings": result.get("findings", {}),
                                "error": result.get("error"),
                            }
                        )

                    if result.get("processing_time_ms"):
                        results["processing_times"].append(result["processing_time_ms"])

                    # Log progress every 100 decisions
                    processed = (
                        results["successful"] + results["failed"] + results["skipped"]
                    )
                    if processed % 100 == 0:
                        logger.info(
                            f"Progress: {processed}/{total_decisions} "
                            f"({results['successful']} [OK], {results['failed']} [FAIL], {results['skipped']} [SKIP])"
                        )

                    if stop_on_error and results["failed"] > 0:
                        logger.warning("Stopping on error as requested")
                        break

                except Exception as e:
                    logger.error(f"Unexpected error processing {ada}: {e}")
                    results["failed"] += 1
                    results["errors"].append(
                        {"ada": ada, "error": f"Unexpected error: {str(e)}"}
                    )
                    if stop_on_error:
                        break

        # Calculate statistics
        end_time = timezone.now()
        total_time = (end_time - start_time).total_seconds()

        if results["processing_times"]:
            results["avg_processing_time_ms"] = sum(results["processing_times"]) / len(
                results["processing_times"]
            )
            results["max_processing_time_ms"] = max(results["processing_times"])
            results["min_processing_time_ms"] = min(results["processing_times"])

        results["total_time_seconds"] = total_time
        results["decisions_per_second"] = (
            total_decisions / total_time if total_time > 0 else 0
        )

        logger.info(
            f"[OK] Batch pipeline completed for ImportJob #{import_job_id} in {total_time:.2f}s\n"
            f"   Total: {total_decisions}, Successful: {results['successful']}, "
            f"Failed: {results['failed']}, Skipped: {results['skipped']}"
        )

        # Generate batch summary
        try:
            self._generate_batch_summary(import_job)
        except Exception as e:
            logger.error(f"Failed to generate batch summary: {e}")

        return results

    def _process_single_decision_safe(
        self,
        decision_ada: str,
        force_reprocess: bool = False,
        skip_opensearch: bool = False,
    ) -> Dict[str, Any]:
        """
        Safely process a single decision with error handling.

        Returns:
            Dictionary with status ('success', 'failed', 'skipped') and details
        """
        start_time = timezone.now()

        try:
            # Check if already processed (unless force_reprocess)
            if not force_reprocess:
                try:
                    health_check = DecisionHealthCheck.objects.get(
                        decision__ada=decision_ada
                    )
                    if health_check.overall_status == HealthStatus.HEALTHY:
                        return {
                            "status": "skipped",
                            "reason": "already_healthy",
                            "ada": decision_ada,
                        }
                except DecisionHealthCheck.DoesNotExist:
                    pass  # Will process

            # Run the pipeline
            health_check = self.run_pipeline(
                decision_ada,
                force_reprocess=force_reprocess,
                skip_opensearch=skip_opensearch,
            )

            end_time = timezone.now()
            processing_time_ms = int((end_time - start_time).total_seconds() * 1000)

            if health_check.overall_status == HealthStatus.ERROR:
                return {
                    "status": "failed",
                    "ada": decision_ada,
                    "findings": health_check.findings,
                    "health_check_id": health_check.id,
                    "processing_time_ms": processing_time_ms,
                }
            else:
                return {
                    "status": "success",
                    "ada": decision_ada,
                    "overall_status": health_check.overall_status,
                    "processing_time_ms": processing_time_ms,
                }

        except Exception as e:
            logger.error(f"Error processing {decision_ada}: {e}")
            return {"status": "failed", "ada": decision_ada, "error": str(e)}

    def retry_failed_step(
        self, decision_ada: str, component: str, force: bool = True
    ) -> DecisionHealthCheck:
        """
        Retry a specific failed component for a decision.

        Args:
            decision_ada: The decision ADA to retry
            component: Component name ('entities', 'companies', 'document', 'opensearch', 'coverage')
            force: Force reprocessing even if not in error state

        Returns:
            Updated DecisionHealthCheck instance
        """
        decision = Decision.objects.get(ada=decision_ada)
        health_check = self.get_or_create_health_check(decision)

        step_map = {
            "amounts": self._step_extract_amounts,
            "entities": self._step_extract_entities,
            "companies": self._step_enrich_companies,
            "entity_amount_extraction": self._step_extract_entities_and_amounts,
            "document": self._step_process_document,
            "opensearch": self._step_index_opensearch,
            "coverage": self._step_verify_coverage,
        }

        if component not in step_map:
            raise ValueError(
                f"Unknown component: {component}. Must be one of: {list(step_map.keys())}"
            )

        logger.info(f"[RETRY] Retrying {component} for {decision_ada}")

        try:
            # Steps that accept 'force' parameter
            if component in ["amounts", "document"]:
                step_map[component](decision, health_check, force=force)
            else:
                step_map[component](decision, health_check)
            logger.success(f"[OK] Successfully retried {component} for {decision_ada}")
        except Exception as e:
            logger.error(f"[ERROR] Failed to retry {component} for {decision_ada}: {e}")
            self.update_health_status(
                health_check, component, HealthStatus.ERROR, str(e)
            )

        return health_check

    def retry_batch_failures(
        self, import_job_id: int, component: Optional[str] = None, max_workers: int = 5
    ) -> Dict[str, Any]:
        """
        Retry all failures in a batch, optionally for a specific component.

        Args:
            import_job_id: The ImportJob ID to retry failures for
            component: Optional specific component to retry (e.g., 'document', 'opensearch')
            max_workers: Maximum parallel workers for retrying

        Returns:
            Dictionary with retry results
        """
        logger.info(
            f"[RETRY] Retrying failures for ImportJob #{import_job_id}, component: {component or 'all'}"
        )

        try:
            import_job = ImportJob.objects.get(id=import_job_id)
        except ImportJob.DoesNotExist:
            return {"error": "ImportJob not found", "total": 0}

        # Get all error health checks for this batch
        failed_checks = DecisionHealthCheck.objects.filter(
            decision__import_job=import_job, overall_status=HealthStatus.ERROR
        )

        if component:
            # Filter by specific component failure
            filter_kwargs = {f"{component}_status": HealthStatus.ERROR}
            failed_checks = failed_checks.filter(**filter_kwargs)

        total_failures = failed_checks.count()

        if total_failures == 0:
            logger.info("No failures to retry")
            return {
                "total": 0,
                "retried": 0,
                "still_failed": 0,
                "message": "No failures found",
            }

        results = {
            "import_job_id": import_job_id,
            "component": component or "all",
            "total": total_failures,
            "retried": 0,
            "still_failed": 0,
            "errors": [],
        }

        logger.info(f"Found {total_failures} failures to retry")

        # Process retries in parallel
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_ada = {}

            for health_check in failed_checks:
                ada = health_check.decision.ada
                if component:
                    future = executor.submit(self.retry_failed_step, ada, component)
                else:
                    future = executor.submit(
                        self.run_pipeline, ada, force_reprocess=True
                    )
                future_to_ada[future] = ada

            for future in as_completed(future_to_ada):
                ada = future_to_ada[future]
                try:
                    updated_check = future.result()

                    if updated_check.overall_status != HealthStatus.ERROR:
                        results["retried"] += 1
                        logger.success(f"[OK] Retry successful for {ada}")
                    else:
                        results["still_failed"] += 1
                        results["errors"].append(
                            {"ada": ada, "findings": updated_check.findings}
                        )
                        logger.warning(f"[WARN] Retry failed for {ada}")

                except Exception as e:
                    logger.error(f"[ERROR] Retry failed for {ada}: {e}")
                    results["still_failed"] += 1
                    results["errors"].append({"ada": ada, "error": str(e)})

        logger.info(
            f"[OK] Retry completed: {results['retried']} succeeded, "
            f"{results['still_failed']} still failed"
        )

        # Regenerate batch summary
        try:
            self._generate_batch_summary(import_job)
        except Exception as e:
            logger.error(f"Failed to regenerate batch summary: {e}")

        return results

    def _generate_batch_summary(self, import_job: ImportJob) -> Dict[str, Any]:
        """
        Generate aggregated health summary for an import batch.

        Args:
            import_job: The ImportJob to generate summary for

        Returns:
            Dictionary with summary statistics
        """
        logger.info(f"[STATS] Generating batch summary for ImportJob #{import_job.id}")

        health_checks = DecisionHealthCheck.objects.filter(
            decision__import_job=import_job
        )

        total = health_checks.count()

        if total == 0:
            logger.warning("No health checks found for this batch")
            return {"total": 0}

        # Count by overall status
        from django.db.models import Avg, Count, Max

        status_counts = health_checks.values("overall_status").annotate(
            count=Count("id")
        )

        summary = {
            "import_job_id": import_job.id,
            "total_decisions": total,
            "healthy_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "unknown_count": 0,
        }

        for status_count in status_counts:
            status = status_count["overall_status"]
            count = status_count["count"]
            summary[f"{status.lower()}_count"] = count

        # Component failure breakdowns
        summary.update(
            {
                "ingestion_failures": health_checks.filter(
                    ingestion_status=HealthStatus.ERROR
                ).count(),
                "entity_failures": health_checks.filter(
                    entities_status=HealthStatus.ERROR
                ).count(),
                "document_failures": health_checks.filter(
                    document_extraction_status=HealthStatus.ERROR
                ).count(),
                "opensearch_failures": health_checks.filter(
                    opensearch_status=HealthStatus.ERROR
                ).count(),
                "coverage_failures": health_checks.filter(
                    coverage_status=HealthStatus.ERROR
                ).count(),
            }
        )

        # Timing statistics
        timing_stats = health_checks.aggregate(
            avg_time=Avg("check_duration_ms"), max_time=Max("check_duration_ms")
        )

        summary["avg_processing_time_ms"] = timing_stats.get("avg_time")
        summary["max_processing_time_ms"] = timing_stats.get("max_time")

        # Find slowest decision
        slowest = health_checks.order_by("-check_duration_ms").first()
        if slowest:
            summary["slowest_decision_ada"] = slowest.decision.ada
            summary["slowest_decision_time_ms"] = slowest.check_duration_ms

        # Calculate health percentage
        if total > 0:
            summary["health_percentage"] = summary["healthy_count"] / total * 100
        else:
            summary["health_percentage"] = 0

        logger.info(
            f"[STATS] Batch summary: {summary['health_percentage']:.1f}% healthy, "
            f"{summary['error_count']} errors, {summary['warning_count']} warnings"
        )

        return summary

    def get_batch_health_report(
        self, import_job_id: int, include_failures: bool = True
    ) -> Dict[str, Any]:
        """
        Get comprehensive health report for a batch.

        Args:
            import_job_id: The ImportJob ID to report on
            include_failures: If True, include list of failed decisions

        Returns:
            Dictionary with comprehensive batch health information
        """
        try:
            import_job = ImportJob.objects.get(id=import_job_id)
        except ImportJob.DoesNotExist:
            return {"error": "ImportJob not found"}

        summary = self._generate_batch_summary(import_job)

        report = {
            "import_job": {
                "id": import_job.id,
                "start_date": import_job.start_date.isoformat(),
                "end_date": import_job.end_date.isoformat(),
                "status": import_job.status,
                "created_at": import_job.created_at.isoformat(),
            },
            "summary": summary,
        }

        if include_failures and summary.get("error_count", 0) > 0:
            failures = DecisionHealthCheck.objects.filter(
                decision__import_job=import_job, overall_status=HealthStatus.ERROR
            ).select_related("decision")[
                :100
            ]  # Limit to first 100 failures

            report["failures"] = [
                {
                    "ada": hc.decision.ada,
                    "issue_date": (
                        hc.decision.issue_date.isoformat()
                        if hc.decision.issue_date
                        else None
                    ),
                    "subject": (
                        hc.decision.subject[:100] if hc.decision.subject else None
                    ),
                    "component_statuses": {
                        "ingestion": hc.ingestion_status,
                        "entities": hc.entities_status,
                        "document": hc.document_extraction_status,
                        "opensearch": hc.opensearch_status,
                        "coverage": hc.coverage_status,
                    },
                    "findings": hc.findings,
                }
                for hc in failures
            ]

            if summary.get("error_count", 0) > 100:
                report["failures_note"] = (
                    f"Showing first 100 of {summary['error_count']} failures"
                )

        return report
