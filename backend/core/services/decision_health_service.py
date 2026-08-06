import time
from datetime import timedelta
from typing import Any, Dict, List, Optional

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.entities import DecisionEntityRelationship
from core.models.import_jobs import DateCoverage
from core.services.feature_flag_service import feature_flags
from core.services.opensearch_service import OpenSearchService
from django.utils import timezone
from loguru import logger


class DecisionHealthService:
    """
    Comprehensive health check service for the decision ingestion pipeline.

    Performs detailed checks on each stage of the pipeline:
    1. Ingestion: Basic decision data saved to database
    2. Relations: Signers, units, organization properly linked
    3. Entities: AFM entities extracted and associated
    4. Document Extraction: PDF downloaded and text extracted
    5. OpenSearch: Document indexed and searchable
    6. Coverage: DateCoverage records updated
    """

    def __init__(self):

        if feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
            self.opensearch_service = OpenSearchService()

    def check_decision_health(
        self, decision: Decision, force_refresh: bool = False
    ) -> DecisionHealthCheck:
        """
        Perform comprehensive health check on a decision.

        Args:
            decision: The Decision instance to check
            force_refresh: If True, always run fresh checks. If False, return cached results if recent.

        Returns:
            DecisionHealthCheck instance with all results
        """
        start_time = time.time()

        # Get or create health check record
        health_check, created = DecisionHealthCheck.objects.get_or_create(
            decision=decision,
            defaults={
                "overall_status": HealthStatus.UNKNOWN,
                "decision_issue_date": decision.issue_date,
            },
        )

        # Check if we need to refresh (if not forced and recent check exists)
        if not force_refresh and not created:
            # Consider results fresh if checked within last hour
            one_hour_ago = timezone.now() - timedelta(hours=1)
            if health_check.last_checked_at > one_hour_ago:
                logger.debug(f"Using cached health check for decision {decision.ada}")
                return health_check

        logger.info(f"Running health check for decision {decision.ada}")

        # Run all checks
        self._check_ingestion(decision, health_check)
        self._check_relations(decision, health_check)
        self._check_entities(decision, health_check)

        if feature_flags.is_enabled("EXTRACT_THE_DOCS_FROM_PDFS"):
            self._check_document_extraction(decision, health_check)

        if feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
            self._check_opensearch(decision, health_check)

        self._check_coverage(decision, health_check)

        # Calculate check duration
        end_time = time.time()
        health_check.check_duration_ms = int((end_time - start_time) * 1000)

        # Save results
        health_check.save()

        logger.info(
            f"Health check completed for {decision.ada}: {health_check.overall_status}"
        )
        return health_check

    def _check_ingestion(self, decision: Decision, health_check: DecisionHealthCheck):
        """Check if basic decision data is properly saved"""
        try:
            issues = []

            # Check required fields
            if not decision.ada:
                issues.append("Missing ADA identifier")

            if not decision.subject:
                issues.append("Missing subject/title")

            if not decision.issue_date:
                issues.append("Missing issue date")

            if not decision.decision_type:
                issues.append("Missing decision type")

            # Check document URL if applicable (use fallback which constructs URL from ADA)
            doc_url = getattr(decision, "document_url_or_fallback", None)
            if doc_url:
                if not str(doc_url).startswith("http"):
                    issues.append("Invalid document URL format")

            # Determine status
            if issues:
                status = (
                    HealthStatus.WARNING if len(issues) <= 2 else HealthStatus.ERROR
                )
                message = f"Found {len(issues)} ingestion issues"
            else:
                status = HealthStatus.HEALTHY
                message = "Decision properly ingested with all required fields"

            health_check.set_finding(
                "ingestion",
                status,
                message,
                {
                    "issues": issues,
                    "ada": decision.ada,
                    "has_document_url": bool(getattr(decision, "document_url", None)),
                },
            )

        except Exception as e:
            logger.error(f"Error checking ingestion for {decision.ada}: {e}")
            health_check.set_finding(
                "ingestion", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def _check_relations(self, decision: Decision, health_check: DecisionHealthCheck):
        """Check if relationships (signers, units, organization) are properly linked"""
        try:
            issues = []
            warnings = []

            # Check organization
            if not decision.organization:
                issues.append("No organization linked")
            else:
                # Check if organization exists and has basic data
                org = decision.organization
                if not org.label:
                    warnings.append(f"Organization {org.uid} missing label")

            # Check signers
            signer_count = decision.signers.count()
            if signer_count == 0:
                warnings.append("No signers linked")
            else:
                # Check if signers have basic data (using first_name and last_name)
                signers_without_name = decision.signers.filter(
                    first_name__isnull=True, last_name__isnull=True
                ).count()
                if signers_without_name > 0:
                    warnings.append(f"{signers_without_name} signers missing names")

            # Check units
            unit_count = decision.units.count()
            if unit_count == 0:
                warnings.append("No units linked")
            else:
                # Check if units have basic data
                units_without_label = decision.units.filter(label__isnull=True).count()
                if units_without_label > 0:
                    warnings.append(f"{units_without_label} units missing label")

            # Determine status
            if issues:
                status = HealthStatus.ERROR
                message = f"Critical relation issues: {', '.join(issues)}"
            elif warnings:
                status = HealthStatus.WARNING
                message = f"Minor relation issues: {', '.join(warnings)}"
            else:
                status = HealthStatus.HEALTHY
                message = "All relationships properly linked"

            health_check.set_finding(
                "relations",
                status,
                message,
                {
                    "issues": issues,
                    "warnings": warnings,
                    "signer_count": signer_count,
                    "unit_count": unit_count,
                    "has_organization": bool(decision.organization),
                },
            )

        except Exception as e:
            logger.error(f"Error checking relations for {decision.ada}: {e}")
            health_check.set_finding(
                "relations", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def _check_entities(self, decision: Decision, health_check: DecisionHealthCheck):
        """Check if AFM entities are properly extracted and associated"""
        try:
            # Get entity relationships
            entity_relationships = DecisionEntityRelationship.objects.filter(
                decision=decision
            ).select_related("entity")
            entity_count = entity_relationships.count()

            if entity_count == 0:
                # This might be normal for some decisions, so it's a warning not an error
                status = HealthStatus.WARNING
                message = (
                    "No AFM entities associated (may be normal for some decision types)"
                )
                details = {
                    "entity_count": 0,
                    "entities_with_company_data": 0,
                    "needs_company_data": 0,
                    "entities_needing_data": [],
                    "entities_with_errors": [],
                }
            else:
                # Check entity data quality
                entities_with_company_data = 0
                entities_needing_data = []
                entities_with_errors = []

                for rel in entity_relationships:
                    if rel.entity:
                        if rel.entity.gemi_lookup_success:
                            entities_with_company_data += 1
                        elif not rel.entity.gemi_lookup_attempted:
                            entities_needing_data.append(
                                {
                                    "afm": rel.entity.afm,
                                    "name": rel.entity.name or "Unknown",
                                    "role": rel.role,
                                    "reason": "Not attempted yet",
                                }
                            )
                        elif (
                            rel.entity.gemi_lookup_attempted
                            and not rel.entity.gemi_lookup_success
                        ):
                            entities_with_errors.append(
                                {
                                    "afm": rel.entity.afm,
                                    "name": rel.entity.name or "Unknown",
                                    "role": rel.role,
                                    "error": rel.entity.last_error or "Unknown error",
                                    "error_count": rel.entity.error_count,
                                    "last_attempt": (
                                        rel.entity.gemi_lookup_attempted.isoformat()
                                        if rel.entity.gemi_lookup_attempted
                                        else None
                                    ),
                                }
                            )

                # Determine status based on data completeness
                if entities_with_errors:
                    status = HealthStatus.ERROR
                    message = f"{len(entities_with_errors)} entities failed GEMI lookup, {len(entities_needing_data)} not attempted yet"
                elif entities_needing_data:
                    if (
                        len(entities_needing_data) > entity_count * 0.5
                    ):  # More than 50% need data
                        status = HealthStatus.WARNING
                        message = f"Many entities ({len(entities_needing_data)}/{entity_count}) still need company data"
                    else:
                        status = HealthStatus.WARNING
                        message = f"Some entities ({len(entities_needing_data)}/{entity_count}) need company data"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Entities properly extracted ({entity_count} found, all have company data)"

                details = {
                    "entity_count": entity_count,
                    "entities_with_company_data": entities_with_company_data,
                    "needs_company_data": len(entities_needing_data),
                    "entities_needing_data": entities_needing_data,
                    "entities_with_errors": entities_with_errors,
                }

            health_check.set_finding("entities", status, message, details)

        except Exception as e:
            logger.error(f"Error checking entities for {decision.ada}: {e}")
            health_check.set_finding(
                "entities", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def _check_document_extraction(
        self, decision: Decision, health_check: DecisionHealthCheck
    ):
        """Check if document is downloaded and text extracted"""
        try:
            # Check if decision has a document URL (stored or constructable from ADA)
            doc_url = getattr(decision, "document_url_or_fallback", None)
            if not doc_url:
                health_check.set_finding(
                    "document_extraction",
                    HealthStatus.WARNING,
                    "No document URL and no ADA to construct one",
                    {"has_document_url": False, "has_ada": bool(decision.ada)},
                )
                return

            has_stored_url = bool(getattr(decision, "document_url", None))
            details = {
                "has_document_url": has_stored_url,
                "has_ada": bool(decision.ada),
                "using_fallback": not has_stored_url,
            }

            # Check if extraction exists
            try:
                extraction = decision.text_extraction

                if extraction.extraction_status == ProcessingStatus.COMPLETED:
                    if (
                        extraction.raw_text
                        and len(extraction.raw_text.strip()) > 10
                    ):
                        status = HealthStatus.HEALTHY
                        message = "Document successfully extracted"
                    else:
                        status = HealthStatus.WARNING
                        message = "Extraction completed but text appears empty"

                elif extraction.extraction_status == ProcessingStatus.FAILED:
                    status = HealthStatus.ERROR
                    message = f"Extraction failed: {extraction.error_message or 'Unknown error'}"

                elif extraction.extraction_status == ProcessingStatus.PROCESSING:
                    status = HealthStatus.WARNING
                    message = "Extraction still in progress"

                elif extraction.extraction_status == ProcessingStatus.NEEDS_VISION:
                    status = HealthStatus.WARNING
                    message = "Document needs OCR processing"

                else:  # PENDING or other
                    status = HealthStatus.WARNING
                    message = f"Extraction pending (status: {extraction.extraction_status})"

                details.update({
                    "has_extraction": True,
                    "status": extraction.extraction_status,
                    "provider": extraction.extraction_provider,
                    "character_count": extraction.character_count,
                    "page_count": extraction.page_count,
                    "retry_count": extraction.retry_count,
                    "error_message": extraction.error_message,
                })

            except DocumentExtraction.DoesNotExist:
                status = HealthStatus.ERROR
                message = "Document extraction record missing"
                details.update({"has_extraction": False})

            health_check.set_finding("document_extraction", status, message, details)

        except Exception as e:
            logger.error(f"Error checking document extraction for {decision.ada}: {e}")
            health_check.set_finding(
                "document_extraction", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def _check_opensearch(self, decision: Decision, health_check: DecisionHealthCheck):
        """Check if document is indexed in OpenSearch and searchable"""
        try:
            # First check if document should be in OpenSearch
            should_be_indexed = False
            extraction_text = None

            if hasattr(decision, "text_extraction"):
                try:
                    extraction = decision.text_extraction
                    if (
                        extraction.extraction_status == ProcessingStatus.COMPLETED
                        and extraction.raw_text
                    ):
                        should_be_indexed = True
                        extraction_text = extraction.raw_text[
                            :100
                        ]  # First 100 chars for search test
                except DocumentExtraction.DoesNotExist:
                    pass

            if not should_be_indexed:
                status = HealthStatus.HEALTHY  # No indexing needed is fine
                message = "No document text to index - OpenSearch not needed"
                details = {"should_be_indexed": False}
            else:

                if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH"):
                    status = HealthStatus.UNKNOWN
                    message = "OpenSearch indexing disabled via settings"
                    details = {"should_be_indexed": True, "indexing_disabled": True}
                    health_check.set_finding("opensearch", status, message, details)
                    return
                # Check if document exists in OpenSearch
                doc_exists = self.opensearch_service.document_exists(decision.ada)

                if not doc_exists:
                    status = HealthStatus.ERROR
                    message = "Document missing from OpenSearch index"
                    details = {
                        "should_be_indexed": True,
                        "exists_in_opensearch": False,
                        "search_test_passed": False,
                    }
                else:
                    # Test searchability with a snippet of the actual text
                    search_test_passed = False
                    if extraction_text:
                        # Use a few words from the document to test search
                        test_query = " ".join(
                            extraction_text.split()[:3]
                        )  # First 3 words
                        if test_query.strip():
                            search_results = self.opensearch_service.search_documents(
                                test_query, size=10
                            )
                            # Check if our decision appears in results
                            hits = search_results.get("hits", {}).get("hits", [])
                            search_test_passed = any(
                                result.get("_source", {}).get("ada") == decision.ada
                                for result in hits
                            )

                    if search_test_passed:
                        status = HealthStatus.HEALTHY
                        message = "Document indexed and searchable in OpenSearch"
                    else:
                        status = HealthStatus.WARNING
                        message = "Document indexed but search test failed"

                    details = {
                        "should_be_indexed": True,
                        "exists_in_opensearch": True,
                        "search_test_passed": search_test_passed,
                        "test_query": test_query if extraction_text else None,
                    }

            health_check.set_finding("opensearch", status, message, details)

        except Exception as e:
            logger.error(f"Error checking OpenSearch for {decision.ada}: {e}")
            health_check.set_finding(
                "opensearch", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def _check_coverage(self, decision: Decision, health_check: DecisionHealthCheck):
        """Check if DateCoverage records are properly updated"""
        try:
            if not decision.issue_date or not decision.organization:
                status = HealthStatus.WARNING
                message = "Cannot check coverage - missing issue_date or organization"
                details = {
                    "has_issue_date": bool(decision.issue_date),
                    "has_organization": bool(decision.organization),
                    "coverage_records_found": 0,
                }
            else:
                # Check for organization coverage
                # Use localdate() to match the timezone used in DateCoverage
                from django.utils.timezone import localdate

                issue_date = localdate(decision.issue_date)
                org_coverage = DateCoverage.objects.filter(
                    date=issue_date,
                    organization=decision.organization,
                    unit__isnull=True,
                    signer__isnull=True,
                ).first()

                coverage_records = 0
                issues = []

                if org_coverage:
                    coverage_records += 1
                    # Check if count seems reasonable (not zero and not wildly off)
                    actual_count = Decision.objects.filter(
                        organization=decision.organization, issue_date_day=issue_date
                    ).count()

                    if org_coverage.decision_count == 0:
                        issues.append("Organization coverage shows zero decisions")
                    elif abs(org_coverage.decision_count - actual_count) > 1:
                        issues.append(
                            f"Coverage count mismatch: recorded={org_coverage.decision_count}, actual={actual_count}"
                        )
                else:
                    issues.append("No organization coverage record found")

                # Check signer coverage (if decision has signers)
                if decision.signers.exists():
                    for signer in decision.signers.all():
                        signer_coverage = DateCoverage.objects.filter(
                            date=issue_date,
                            signer=signer,
                            organization__isnull=True,
                            unit__isnull=True,
                        ).first()

                        if signer_coverage:
                            coverage_records += 1
                        else:
                            issues.append(f"No coverage record for signer {signer.uid}")

                # Determine status
                if issues:
                    status = (
                        HealthStatus.WARNING
                    )  # Coverage issues are usually not critical
                    message = f"Coverage issues found: {', '.join(issues[:2])}"  # Limit message length
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Coverage records properly maintained ({coverage_records} records)"

                details = {
                    "has_issue_date": True,
                    "has_organization": True,
                    "coverage_records_found": coverage_records,
                    "issues": issues,
                }

            health_check.set_finding("coverage", status, message, details)

        except Exception as e:
            logger.error(f"Error checking coverage for {decision.ada}: {e}")
            health_check.set_finding(
                "coverage", HealthStatus.ERROR, f"Check failed: {str(e)}"
            )

    def bulk_check_decisions(
        self, decisions: List[Decision], progress_callback=None
    ) -> Dict[str, Any]:
        """
        Run health checks on multiple decisions.

        Args:
            decisions: List of Decision instances to check
            progress_callback: Optional function to call with progress updates

        Returns:
            Summary statistics and list of health check results
        """
        results = []
        total_count = len(decisions)

        for i, decision in enumerate(decisions):
            if progress_callback:
                progress_callback(i + 1, total_count, decision.ada)

            try:
                health_check = self.check_decision_health(decision)
                results.append(health_check)
            except Exception as e:
                logger.error(f"Failed to check decision {decision.ada}: {e}")
                continue

        # Calculate summary statistics
        summary = {
            "total_checked": len(results),
            "healthy": sum(
                1 for r in results if r.overall_status == HealthStatus.HEALTHY
            ),
            "warnings": sum(
                1 for r in results if r.overall_status == HealthStatus.WARNING
            ),
            "errors": sum(1 for r in results if r.overall_status == HealthStatus.ERROR),
            "unknown": sum(
                1 for r in results if r.overall_status == HealthStatus.UNKNOWN
            ),
        }

        # Component-specific statistics
        component_stats = {}
        for component in [
            "ingestion",
            "relations",
            "entities",
            "document_extraction",
            "opensearch",
            "coverage",
        ]:
            component_stats[component] = {
                "healthy": sum(
                    1
                    for r in results
                    if getattr(r, f"{component}_status") == HealthStatus.HEALTHY
                ),
                "warnings": sum(
                    1
                    for r in results
                    if getattr(r, f"{component}_status") == HealthStatus.WARNING
                ),
                "errors": sum(
                    1
                    for r in results
                    if getattr(r, f"{component}_status") == HealthStatus.ERROR
                ),
            }

        return {
            "summary": summary,
            "component_stats": component_stats,
            "health_checks": results,
        }

    def get_problematic_decisions(
        self,
        limit: int = 100,
        component: Optional[str] = None,
        status_filter: Optional[str] = None,
    ) -> List[DecisionHealthCheck]:
        """
        Get decisions with health issues for investigation.

        Args:
            limit: Maximum number of results to return
            component: Filter by specific component ('ingestion', 'relations', etc.)
            status_filter: Filter by status ('ERROR', 'WARNING', etc.)

        Returns:
            List of DecisionHealthCheck instances with issues
        """
        queryset = DecisionHealthCheck.objects.select_related("decision").order_by(
            "-last_checked_at"
        )

        if status_filter:
            if component:
                # Filter by specific component status
                filter_field = f"{component}_status"
                queryset = queryset.filter(**{filter_field: status_filter})
            else:
                # Filter by overall status
                queryset = queryset.filter(overall_status=status_filter)
        else:
            # Default to showing problems (errors and warnings)
            queryset = queryset.filter(has_errors=True) | queryset.filter(
                has_warnings=True
            )

        return list(queryset[:limit])
