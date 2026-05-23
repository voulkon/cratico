import json

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.decision_health_service import DecisionHealthService
from core.services.opensearch_service import OpenSearchService
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Investigate decisions with health issues and suggest fixes"

    def add_arguments(self, parser):
        parser.add_argument(
            "--component",
            choices=[
                "ingestion",
                "relations",
                "entities",
                "document_extraction",
                "opensearch",
                "coverage",
            ],
            help="Focus investigation on a specific component",
        )

        parser.add_argument(
            "--status",
            choices=["ERROR", "WARNING"],
            default="ERROR",
            help="Investigation focus (default: ERROR)",
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum number of decisions to investigate (default: 50)",
        )

        parser.add_argument(
            "--auto-fix",
            action="store_true",
            help="Attempt automatic fixes where possible (use with caution!)",
        )

        parser.add_argument(
            "--detailed-analysis",
            action="store_true",
            help="Perform detailed analysis of each issue",
        )

        parser.add_argument(
            "--export-report", type=str, help="Export investigation report to file"
        )

    def handle(self, *args, **options):
        self.health_service = DecisionHealthService()
        self.opensearch_service = OpenSearchService()

        # Get problematic decisions
        problematic_decisions = self._get_problematic_decisions(options)

        if not problematic_decisions:
            self.stdout.write(
                self.style.SUCCESS("No problematic decisions found! [EVENT]")
            )
            return

        self.stdout.write(f"Found {len(problematic_decisions)} decisions with issues")

        # Investigate each decision
        investigation_results = []
        for i, health_check in enumerate(problematic_decisions, 1):
            self.stdout.write(
                f"\n[{i}/{len(problematic_decisions)}] Investigating {health_check.decision.ada}"
            )

            result = self._investigate_decision(health_check, options)
            investigation_results.append(result)

            if options["auto_fix"] and result.get("fixable_issues"):
                self._attempt_fixes(health_check, result, options)

        # Summary report
        self._generate_summary_report(investigation_results, options)

        # Export report if requested
        if options["export_report"]:
            self._export_investigation_report(
                investigation_results, options["export_report"]
            )

    def _get_problematic_decisions(self, options):
        """Get decisions with health issues"""
        queryset = DecisionHealthCheck.objects.select_related("decision")

        if options["status"] == "ERROR":
            queryset = queryset.filter(has_errors=True)
        elif options["status"] == "WARNING":
            queryset = queryset.filter(has_warnings=True)

        if options["component"]:
            # Filter by specific component status
            component_filter = f"{options['component']}_status"
            queryset = queryset.filter(**{component_filter: options["status"]})

        return list(queryset.order_by("-last_checked_at")[: options["limit"]])

    def _investigate_decision(self, health_check, options):
        """Investigate a single decision's health issues"""
        decision = health_check.decision
        investigation = {
            "ada": decision.ada,
            "issues": [],
            "fixable_issues": [],
            "recommendations": [],
            "technical_details": {},
        }

        # Investigate each component
        for component in [
            "ingestion",
            "relations",
            "entities",
            "document_extraction",
            "opensearch",
            "coverage",
        ]:
            component_status = getattr(health_check, f"{component}_status")

            if options["component"] and component != options["component"]:
                continue

            if component_status in [HealthStatus.ERROR, HealthStatus.WARNING]:
                issue_details = self._investigate_component(
                    component, decision, health_check, options
                )
                investigation["issues"].append(issue_details)

                if issue_details.get("fixable"):
                    investigation["fixable_issues"].append(issue_details)

        return investigation

    def _investigate_component(self, component, decision, health_check, options):
        """Investigate a specific component issue"""
        finding = health_check.get_finding(component)

        issue = {
            "component": component,
            "status": getattr(health_check, f"{component}_status"),
            "message": finding.get("message", "No message available"),
            "details": finding.get("details", {}),
            "fixable": False,
            "fix_suggestions": [],
            "technical_analysis": {},
        }

        # Component-specific investigation
        if component == "ingestion":
            issue.update(self._investigate_ingestion(decision, options))
        elif component == "relations":
            issue.update(self._investigate_relations(decision, options))
        elif component == "entities":
            issue.update(self._investigate_entities(decision, options))
        elif component == "document_extraction":
            issue.update(self._investigate_document_extraction(decision, options))
        elif component == "opensearch":
            issue.update(self._investigate_opensearch(decision, options))
        elif component == "coverage":
            issue.update(self._investigate_coverage(decision, options))

        return issue

    def _investigate_ingestion(self, decision, options):
        """Investigate ingestion issues"""
        analysis = {
            "technical_analysis": {"missing_fields": [], "invalid_data": []},
            "fix_suggestions": [],
        }

        # Check for missing required fields
        required_fields = ["ada", "subject", "issue_date", "decision_type"]
        for field in required_fields:
            if not getattr(decision, field, None):
                analysis["technical_analysis"]["missing_fields"].append(field)
                analysis["fix_suggestions"].append(
                    f"Refetch decision data to populate {field}"
                )

        # Check data quality
        if decision.subject and len(decision.subject.strip()) < 5:
            analysis["technical_analysis"]["invalid_data"].append("Subject too short")
            analysis["fix_suggestions"].append(
                "Subject appears truncated - refetch from API"
            )

        if analysis["fix_suggestions"]:
            analysis["fixable"] = True

        return analysis

    def _investigate_relations(self, decision, options):
        """Investigate relationship issues"""
        analysis = {
            "technical_analysis": {
                "missing_organization": not bool(decision.organization),
                "signer_count": decision.signers.count(),
                "unit_count": decision.units.count(),
                "orphaned_relations": [],
            },
            "fix_suggestions": [],
        }

        if not decision.organization:
            analysis["fix_suggestions"].append("Refetch organization data from API")
            analysis["fixable"] = True

        if analysis["technical_analysis"]["signer_count"] == 0:
            analysis["fix_suggestions"].append(
                "Check if signers were properly imported"
            )

        if analysis["technical_analysis"]["unit_count"] == 0:
            analysis["fix_suggestions"].append("Check if units were properly imported")

        return analysis

    def _investigate_entities(self, decision, options):
        """Investigate entity extraction issues"""
        from core.models.entities import DecisionEntityRelationship

        analysis = {
            "technical_analysis": {
                "entity_count": 0,
                "entities_needing_company_data": 0,
                "extraction_attempted": False,
            },
            "fix_suggestions": [],
        }

        entity_rels = DecisionEntityRelationship.objects.filter(decision=decision)
        analysis["technical_analysis"]["entity_count"] = entity_rels.count()

        if entity_rels.exists():
            needing_data = sum(
                1
                for rel in entity_rels
                if rel.afm_entity and rel.afm_entity.needs_company_data_fetch
            )
            analysis["technical_analysis"][
                "entities_needing_company_data"
            ] = needing_data

            if needing_data > 0:
                analysis["fix_suggestions"].append(
                    "Trigger company data fetching for entities"
                )
                analysis["fixable"] = True
        else:
            # Check if extraction was attempted
            if (
                hasattr(decision, "text_extraction")
                and decision.text_extraction.extraction_status
                == ProcessingStatus.COMPLETED
            ):
                analysis["technical_analysis"]["extraction_attempted"] = True
                analysis["fix_suggestions"].append(
                    "Re-run entity extraction on document text"
                )
                analysis["fixable"] = True
            else:
                analysis["fix_suggestions"].append(
                    "Ensure document extraction completes first"
                )

        return analysis

    def _investigate_document_extraction(self, decision, options):
        """Investigate document extraction issues"""
        analysis = {
            "technical_analysis": {
                "has_document_url": bool(getattr(decision, "document_url", None)),
                "extraction_exists": False,
                "extraction_status": None,
                "error_details": None,
            },
            "fix_suggestions": [],
        }

        if not analysis["technical_analysis"]["has_document_url"]:
            analysis["fix_suggestions"].append(
                "No document URL available - extraction not possible"
            )
            return analysis

        try:
            extraction = decision.text_extraction
            analysis["technical_analysis"]["extraction_exists"] = True
            analysis["technical_analysis"][
                "extraction_status"
            ] = extraction.extraction_status
            analysis["technical_analysis"]["error_details"] = extraction.error_message

            if extraction.extraction_status == ProcessingStatus.FAILED:
                analysis["fix_suggestions"].append(
                    "Retry document extraction with different provider"
                )
                analysis["fixable"] = True
            elif extraction.extraction_status == ProcessingStatus.PENDING:
                analysis["fix_suggestions"].append("Check if extraction task is stuck")
                analysis["fixable"] = True
            elif extraction.extraction_status == ProcessingStatus.NEEDS_VISION:
                analysis["fix_suggestions"].append("Route to OCR processing pipeline")
                analysis["fixable"] = True

        except DocumentExtraction.DoesNotExist:
            analysis["fix_suggestions"].append(
                "Create extraction record and queue processing"
            )
            analysis["fixable"] = True

        return analysis

    def _investigate_opensearch(self, decision, options):
        """Investigate OpenSearch indexing issues"""
        analysis = {
            "technical_analysis": {
                "should_be_indexed": False,
                "exists_in_opensearch": False,
                "search_test_passed": False,
                "opensearch_connectivity": False,
            },
            "fix_suggestions": [],
        }

        # Check if decision should be in OpenSearch
        try:
            extraction = decision.text_extraction
            if (
                extraction.extraction_status == ProcessingStatus.COMPLETED
                and extraction.raw_text
            ):
                analysis["technical_analysis"]["should_be_indexed"] = True
        except DocumentExtraction.DoesNotExist:
            analysis["fix_suggestions"].append("Complete document extraction first")
            return analysis

        if not analysis["technical_analysis"]["should_be_indexed"]:
            analysis["fix_suggestions"].append(
                "Document extraction needed before indexing"
            )
            return analysis

        # Test OpenSearch connectivity
        try:
            analysis["technical_analysis"][
                "opensearch_connectivity"
            ] = self.opensearch_service.health_check()
        except Exception as e:
            analysis["fix_suggestions"].append(
                f"OpenSearch connectivity issue: {str(e)}"
            )
            return analysis

        # Check if document exists
        try:
            if settings.INDEX_THE_OPENSEARCH:
                analysis["technical_analysis"]["exists_in_opensearch"] = (
                    self.opensearch_service.document_exists(decision.ada)
                )
        except Exception as e:
            analysis["fix_suggestions"].append(
                f"Error checking document existence: {str(e)}"
            )
            return analysis

        if not analysis["technical_analysis"]["exists_in_opensearch"]:
            analysis["fix_suggestions"].append("Re-trigger OpenSearch indexing")
            analysis["fixable"] = True
        else:
            # Test searchability
            try:
                extraction = decision.text_extraction
                test_query = " ".join(extraction.raw_text.split()[:3])
                if test_query.strip():
                    search_results = self.opensearch_service.search_documents(
                        test_query, size=10
                    )
                    analysis["technical_analysis"]["search_test_passed"] = any(
                        result.get("ada") == decision.ada
                        for result in search_results.get("hits", [])
                    )

                    if not analysis["technical_analysis"]["search_test_passed"]:
                        analysis["fix_suggestions"].append(
                            "Document indexed but not searchable - re-index"
                        )
                        analysis["fixable"] = True
            except Exception as e:
                analysis["fix_suggestions"].append(f"Search test failed: {str(e)}")

        return analysis

    def _investigate_coverage(self, decision, options):
        """Investigate coverage tracking issues"""
        from core.models.import_jobs import DateCoverage

        analysis = {
            "technical_analysis": {
                "has_required_data": False,
                "coverage_records_exist": False,
                "count_mismatch": False,
            },
            "fix_suggestions": [],
        }

        if not decision.issue_date or not decision.organization:
            analysis["fix_suggestions"].append(
                "Missing required data (issue_date or organization)"
            )
            return analysis

        analysis["technical_analysis"]["has_required_data"] = True

        # Check for coverage records
        issue_date = decision.issue_date.date()
        coverage = DateCoverage.objects.filter(
            date=issue_date,
            organization=decision.organization,
            unit__isnull=True,
            signer__isnull=True,
        ).first()

        analysis["technical_analysis"]["coverage_records_exist"] = bool(coverage)

        if not coverage:
            analysis["fix_suggestions"].append(
                "Regenerate coverage records for this date/organization"
            )
            analysis["fixable"] = True
        else:
            # Check count accuracy
            actual_count = Decision.objects.filter(
                organization=decision.organization, issue_date__date=issue_date
            ).count()

            if abs(coverage.decision_count - actual_count) > 1:
                analysis["technical_analysis"]["count_mismatch"] = True
                analysis["fix_suggestions"].append(
                    f"Coverage count mismatch: recorded={coverage.decision_count}, actual={actual_count}"
                )
                analysis["fixable"] = True

        return analysis

    def _attempt_fixes(self, health_check, investigation_result, options):
        """Attempt automatic fixes for issues"""
        self.stdout.write(f"  Attempting fixes for {health_check.decision.ada}...")

        for issue in investigation_result["fixable_issues"]:
            component = issue["component"]

            try:
                if component == "document_extraction":
                    self._fix_document_extraction(health_check.decision, issue)
                elif component == "opensearch":
                    self._fix_opensearch(health_check.decision, issue)
                elif component == "entities":
                    self._fix_entities(health_check.decision, issue)
                elif component == "coverage":
                    self._fix_coverage(health_check.decision, issue)
                else:
                    self.stdout.write(f"    No automatic fix available for {component}")

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"    Fix failed for {component}: {str(e)}")
                )

    def _fix_document_extraction(self, decision, issue):
        """Fix document extraction issues"""
        from core.tasks import process_document_task

        if not getattr(decision, "document_url", None):
            return

        # Queue document processing
        process_document_task.delay(decision.ada)
        self.stdout.write(f"    [OK] Queued document processing for {decision.ada}")

    def _fix_opensearch(self, decision, issue):
        """Fix OpenSearch indexing issues"""
        from core.signals import index_document_in_opensearch

        try:
            extraction = decision.text_extraction
            if extraction.extraction_status == ProcessingStatus.COMPLETED:
                # Trigger indexing signal
                index_document_in_opensearch(
                    sender=type(extraction), instance=extraction, created=False
                )
                self.stdout.write(
                    f"    [OK] Re-triggered OpenSearch indexing for {decision.ada}"
                )
        except Exception as e:
            self.stdout.write(f"    [FAIL] Failed to fix OpenSearch: {str(e)}")

    def _fix_entities(self, decision, issue):
        """Fix entity extraction issues"""
        from core.models.entities import DecisionEntityRelationship
        from core.tasks import fetch_company_data_for_entities

        # Trigger entity company data fetching
        entity_rels = DecisionEntityRelationship.objects.filter(decision=decision)
        if entity_rels.exists():
            afms = [rel.afm_entity.afm for rel in entity_rels if rel.afm_entity]
            if afms:
                fetch_company_data_for_entities.delay(afms)
                self.stdout.write(
                    f"    [OK] Triggered company data fetching for {len(afms)} entities"
                )

    def _fix_coverage(self, decision, issue):
        """Fix coverage tracking issues"""
        # Trigger coverage update via signal
        from core.signals import update_organization_coverage

        try:
            update_organization_coverage(sender=type(decision), instance=decision)
            self.stdout.write(f"    [OK] Updated coverage records for {decision.ada}")
        except Exception as e:
            self.stdout.write(f"    [FAIL] Failed to fix coverage: {str(e)}")

    def _generate_summary_report(self, investigation_results, options):
        """Generate investigation summary"""
        total_decisions = len(investigation_results)

        # Count issues by component
        component_issues = {}
        fixable_count = 0

        for result in investigation_results:
            for issue in result["issues"]:
                component = issue["component"]
                component_issues[component] = component_issues.get(component, 0) + 1

            if result["fixable_issues"]:
                fixable_count += 1

        self.stdout.write(f"\n{'='*50}")
        self.stdout.write("INVESTIGATION SUMMARY")
        self.stdout.write(f"{'='*50}")
        self.stdout.write(f"Total Decisions Investigated: {total_decisions}")
        self.stdout.write(f"Decisions with Fixable Issues: {fixable_count}")

        self.stdout.write(f"\nIssues by Component:")
        for component, count in sorted(component_issues.items()):
            self.stdout.write(f"  {component.replace('_', ' ').title()}: {count}")

    def _export_investigation_report(self, investigation_results, filename):
        """Export detailed investigation report"""
        report_data = {
            "investigation_date": timezone.now().isoformat(),
            "total_decisions": len(investigation_results),
            "decisions": investigation_results,
        }

        with open(filename, "w") as f:
            json.dump(report_data, f, indent=2)

        self.stdout.write(f"Investigation report exported to {filename}")
