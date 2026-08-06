from datetime import datetime, timedelta

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.services.decision_health_service import DecisionHealthService
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db import models
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone


@staff_member_required
def health_dashboard_view(request):
    """Dashboard view showing health statistics"""
    # Get filter parameters
    status_filter = request.GET.get(
        "status", ""
    )  # 'ERROR', 'WARNING', or empty for all
    component_filter = request.GET.get(
        "component", ""
    )  # specific component or empty for all

    # Get recent health checks (convert to list to avoid slice/filter issue)
    recent_checks_queryset = DecisionHealthCheck.objects.select_related(
        "decision"
    ).order_by("-last_checked_at")[:100]
    recent_checks = list(recent_checks_queryset)

    # Calculate statistics
    stats = {
        "total": len(recent_checks),
        "healthy": sum(
            1 for hc in recent_checks if hc.overall_status == HealthStatus.HEALTHY
        ),
        "warnings": sum(
            1 for hc in recent_checks if hc.overall_status == HealthStatus.WARNING
        ),
        "errors": sum(
            1 for hc in recent_checks if hc.overall_status == HealthStatus.ERROR
        ),
        "unknown": sum(
            1 for hc in recent_checks if hc.overall_status == HealthStatus.UNKNOWN
        ),
    }

    # Component statistics
    component_stats = {}
    components = [
        "ingestion",
        "relations",
        "entities",
        "document_extraction",
        "opensearch",
        "coverage",
    ]
    for component in components:
        component_stats[component] = {
            "healthy": sum(
                1
                for hc in recent_checks
                if getattr(hc, f"{component}_status") == HealthStatus.HEALTHY
            ),
            "warnings": sum(
                1
                for hc in recent_checks
                if getattr(hc, f"{component}_status") == HealthStatus.WARNING
            ),
            "errors": sum(
                1
                for hc in recent_checks
                if getattr(hc, f"{component}_status") == HealthStatus.ERROR
            ),
        }

    # Recent problematic decisions (get fresh data for problems)
    recent_problems_query = DecisionHealthCheck.objects.filter(
        models.Q(has_errors=True) | models.Q(has_warnings=True)
    ).select_related("decision")

    # Apply filters
    if status_filter == "ERROR":
        recent_problems_query = recent_problems_query.filter(has_errors=True)
    elif status_filter == "WARNING":
        recent_problems_query = recent_problems_query.filter(
            has_warnings=True, has_errors=False
        )

    if component_filter:
        # Filter by specific component status
        filter_dict = {
            f"{component_filter}_status__in": [HealthStatus.ERROR, HealthStatus.WARNING]
        }
        recent_problems_query = recent_problems_query.filter(**filter_dict)

    recent_problems = recent_problems_query.order_by("-last_checked_at")[:50]

    # Issue type breakdown - analyze common issues
    issue_breakdown = {}
    for health_check in recent_problems:
        if health_check.findings:
            for component, finding in health_check.findings.items():
                if finding.get("status") in ["ERROR", "WARNING"]:
                    if component not in issue_breakdown:
                        issue_breakdown[component] = {
                            "count": 0,
                            "messages": {},
                        }
                    issue_breakdown[component]["count"] += 1
                    msg = finding.get("message", "Unknown issue")
                    issue_breakdown[component]["messages"][msg] = (
                        issue_breakdown[component]["messages"].get(msg, 0) + 1
                    )

    context = {
        "title": "Decision Health Dashboard",
        "stats": stats,
        "component_stats": component_stats,
        "recent_problems": recent_problems,
        "issue_breakdown": issue_breakdown,
        "status_filter": status_filter,
        "component_filter": component_filter,
        "components": components,
    }

    return render(request, "admin/decision_health_dashboard.html", context)


@staff_member_required
def refresh_single_check(request, pk):
    """Refresh health check for a single decision"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    health_service = DecisionHealthService()

    try:
        health_service.check_decision_health(health_check.decision, force_refresh=True)
        messages.success(
            request, f"Health check refreshed for decision {health_check.decision.ada}"
        )
    except Exception as e:
        messages.error(request, f"Failed to refresh health check: {str(e)}")

    return redirect("admin:core_decisionhealthcheck_changelist")


@staff_member_required
def bulk_check_view(request):
    """View for running bulk health checks"""
    if request.method == "POST":
        # Parse parameters
        days_back = int(request.POST.get("days_back", 7))
        organization_id = request.POST.get("organization_id")
        limit = int(request.POST.get("limit", 100))

        # Build query for decisions to check
        start_date = datetime.now() - timedelta(days=days_back)

        queryset = Decision.objects.filter(issue_date__gte=start_date)
        if organization_id:
            queryset = queryset.filter(organization_id=organization_id)

        decisions = list(queryset.order_by("-issue_date")[:limit])

        # Run health checks
        health_service = DecisionHealthService()
        results = health_service.bulk_check_decisions(decisions)

        context = {
            "title": "Bulk Health Check Results",
            "results": results,
            "checked_count": len(decisions),
        }

        return render(request, "admin/bulk_health_check_results.html", context)

    # GET request - show form
    context = {
        "title": "Bulk Health Check",
    }

    return render(request, "admin/bulk_health_check.html", context)


@staff_member_required
def quick_health_check_view(request):
    """Quick health check for recent decisions"""

    if request.method == "POST":
        # Run health check
        days = int(request.POST.get("days", 1))
        limit = int(request.POST.get("limit", 20))

        # Get recent decisions
        since_date = timezone.now() - timedelta(days=days)
        recent_decisions = Decision.objects.filter(issue_date__gte=since_date).order_by(
            "-issue_date"
        )[:limit]

        if recent_decisions:
            health_service = DecisionHealthService()
            results = health_service.bulk_check_decisions(list(recent_decisions))

            context = {
                "title": "Quick Health Check Results",
                "results": results,
                "checked_decisions": len(recent_decisions),
                "days": days,
            }
            return render(request, "admin/quick_health_results.html", context)
        else:
            context = {
                "title": "Quick Health Check",
                "no_decisions": True,
                "days": days,
            }
            return render(request, "admin/quick_health_check.html", context)

    # GET request - show form
    context = {
        "title": "Quick Health Check",
    }
    return render(request, "admin/quick_health_check.html", context)


@staff_member_required
def health_check_detail_view(request, pk):
    """Detailed view for a single health check with actionable insights"""
    health_check = get_object_or_404(
        DecisionHealthCheck.objects.select_related("decision"), pk=pk
    )

    context = {
        "title": f"Health Check Detail - {health_check.decision.ada}",
        "health_check": health_check,
    }

    return render(request, "admin/health_check_detail.html", context)


@staff_member_required
def fix_entity_data(request, pk):
    """Trigger company data fetch for entities in a decision using existing task infrastructure"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    # Get entities that need data
    from core.models.entities import DecisionEntityRelationship
    from core.tasks.tasks_entities import fetch_company_data_for_single_afm

    entity_relationships = DecisionEntityRelationship.objects.filter(
        decision=decision
    ).select_related("entity")

    afms_to_fetch = []
    afms_failed = []

    for rel in entity_relationships:
        if rel.entity:
            if not rel.entity.gemi_lookup_attempted:
                afms_to_fetch.append(rel.entity.afm)
            elif not rel.entity.gemi_lookup_success:
                afms_failed.append((rel.entity.afm, rel.entity.last_error or "Unknown"))

    if afms_to_fetch:
        # Use existing Celery task infrastructure (same as original flow)
        # This is rate-limited at 6/minute by the task decorator
        for afm in afms_to_fetch:
            fetch_company_data_for_single_afm.delay(afm)

        messages.success(
            request,
            f"[OK] Queued {len(afms_to_fetch)} AFMs for GEMI lookup: {', '.join(afms_to_fetch)}. "
            f"Tasks use the same infrastructure that should have run automatically. "
            f"Check Celery logs to see why they didn't run initially.",
        )

    if afms_failed:
        messages.warning(
            request,
            f"[WARN]️ {len(afms_failed)} AFMs previously failed: {', '.join(f'{afm} ({err})' for afm, err in afms_failed)}. "
            f"These will NOT be retried automatically. Check if errors are persistent or transient.",
        )

    if not afms_to_fetch and not afms_failed:
        messages.info(request, "No entities need company data fetch")

    return redirect("admin:health_check_detail", pk=pk)


@staff_member_required
def retry_document_extraction(request, pk):
    """Retry document extraction for a decision"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    try:
        from core.models.document_analysis import DocumentExtraction, ProcessingStatus

        # Check if extraction exists and get status
        try:
            extraction = decision.text_extraction
            old_status = extraction.extraction_status

            # Reset to pending to trigger reprocessing
            extraction.extraction_status = ProcessingStatus.PENDING
            extraction.error_message = None
            extraction.save(update_fields=["extraction_status", "error_message"])

            messages.info(
                request, f"[FILE] Reset extraction status from {old_status} to PENDING"
            )
        except DocumentExtraction.DoesNotExist:
            # Create extraction record if it doesn't exist
            if decision.document_url_or_fallback:
                DocumentExtraction.objects.create(
                    decision=decision, extraction_status=ProcessingStatus.PENDING
                )
                messages.info(
                    request,
                    "[FILE] Created extraction record for decision with document URL",
                )
            else:
                messages.error(
                    request, "[ERROR] Decision has no document URL to extract (and no ADA)"
                )
                return redirect("admin:health_check_detail", pk=pk)

        # Trigger extraction task
        from core.tasks.tasks_document_processing import (
            process_single_decision_document,
        )

        process_single_decision_document.delay(decision.id)

        messages.success(
            request,
            f"[OK] Queued document extraction task for {decision.ada}. "
            f"Monitor Celery worker logs for progress.",
        )
    except Exception as e:
        messages.error(request, f"[ERROR] Failed to trigger extraction: {str(e)}")
        logger.exception(f"Error in retry_document_extraction for {decision.ada}")

    return redirect("admin:health_check_detail", pk=pk)


@staff_member_required
def reindex_opensearch(request, pk):
    """Reindex decision in OpenSearch"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    try:
        from core.services.opensearch_service import OpenSearchService

        opensearch_service = OpenSearchService()

        # Check if we have text to index
        has_text = False
        try:
            extraction = decision.text_extraction
            has_text = bool(
                extraction.raw_text and len(extraction.raw_text.strip()) > 10
            )
        except:
            pass

        if not has_text:
            messages.warning(
                request,
                f"[WARN]️ Decision {decision.ada} has no extracted text. "
                f"Fix document extraction first before indexing.",
            )
            return redirect("admin:health_check_detail", pk=pk)

        # Re-index the decision
        success = opensearch_service.index_decision(decision)

        if success:
            messages.success(
                request, f"[OK] Successfully re-indexed {decision.ada} in OpenSearch"
            )
        else:
            messages.warning(
                request,
                f"[WARN]️ Re-indexing completed but may have issues. Check OpenSearch logs.",
            )
    except Exception as e:
        messages.error(request, f"[ERROR] Failed to re-index: {str(e)}")
        logger.exception(f"Error in reindex_opensearch for {decision.ada}")

    return redirect("admin:health_check_detail", pk=pk)


@staff_member_required
def reextract_entities(request, pk):
    """Re-extract AFM entities from decision using existing extraction service"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    try:
        from core.models.entities import DecisionEntityRelationship
        from core.services.entity_extraction_service import EntityExtractionService

        # Delete existing relationships to start fresh
        existing_count = DecisionEntityRelationship.objects.filter(
            decision=decision
        ).count()
        if existing_count > 0:
            DecisionEntityRelationship.objects.filter(decision=decision).delete()
            messages.info(
                request,
                f"[PURGE]️ Deleted {existing_count} existing entity relationships",
            )

        # Extract entities using existing service
        service = EntityExtractionService()
        entities = service.extract_afm_entities_from_decision(
            decision, save_relationships=True, skip_existing=False
        )

        if entities:
            messages.success(
                request,
                f"[OK] Extracted {len(entities)} entities from {decision.ada}. "
                f"AFMs: {', '.join(e.afm for e in entities[:5])}{'...' if len(entities) > 5 else ''}",
            )

            # Optionally queue company data fetch
            afms_needing_data = [e.afm for e in entities if not e.gemi_lookup_attempted]
            if afms_needing_data:
                messages.info(
                    request,
                    f"[INFO] {len(afms_needing_data)} entities need company data. "
                    f"Use 'Fetch Company Data' button to queue lookups.",
                )
        else:
            messages.warning(request, f"[WARN]️ No AFM entities found in {decision.ada}")

    except Exception as e:
        messages.error(request, f"[ERROR] Failed to extract entities: {str(e)}")
        logger.exception(f"Error in reextract_entities for {decision.ada}")

    return redirect("admin:health_check_detail", pk=pk)


@staff_member_required
def relink_relations(request, pk):
    """Re-link decision relationships (signers, units, organization)"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    try:
        # This would need access to the original import service that links relations
        # For now, provide diagnostic information

        diagnostics = []

        # Check organization
        if not decision.organization:
            if hasattr(decision, "organization_uid"):
                diagnostics.append(
                    f"Missing organization. UID in data: {decision.organization_uid}"
                )
            else:
                diagnostics.append(
                    "Missing organization. No UID found in decision data."
                )

        # Check signers
        signer_count = decision.signers.count()
        if signer_count == 0:
            diagnostics.append(
                "No signers linked. Check if signer data exists in extra_field_values_json."
            )

        # Check units
        unit_count = decision.units.count()
        if unit_count == 0:
            diagnostics.append(
                "No units linked. Check if unit data exists in extra_field_values_json."
            )

        if diagnostics:
            messages.warning(
                request, f"[WARN]️ Relation issues found: {' | '.join(diagnostics)}"
            )
            messages.info(
                request,
                "[INFO] Automatic relation linking requires re-importing the decision with proper linking logic. "
                "This typically happens during initial import. Check import logs for this ADA.",
            )
        else:
            messages.success(request, "[OK] All relations appear properly linked")

    except Exception as e:
        messages.error(request, f"[ERROR] Failed to check relations: {str(e)}")
        logger.exception(f"Error in relink_relations for {decision.ada}")

    return redirect("admin:health_check_detail", pk=pk)


@staff_member_required
def update_coverage(request, pk):
    """Update date coverage for this decision's organization and date"""
    health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
    decision = health_check.decision

    try:
        from core.models.import_jobs import DateCoverage

        if not decision.organization or not decision.issue_date:
            messages.error(
                request,
                "[ERROR] Cannot update coverage: decision missing organization or issue_date",
            )
            return redirect("admin:health_check_detail", pk=pk)

        # Get or create coverage record
        coverage, created = DateCoverage.objects.get_or_create(
            organization=decision.organization,
            date=decision.issue_date.date(),
            defaults={"decision_count": 0, "is_complete": False},
        )

        # Recalculate decision count
        actual_count = Decision.objects.filter(
            organization=decision.organization,
            issue_date_day=decision.issue_date_day,
        ).count()

        old_count = coverage.decision_count
        coverage.decision_count = actual_count
        coverage.save(update_fields=["decision_count"])

        if created:
            messages.success(
                request,
                f"[OK] Created coverage record for {decision.organization.label} on {decision.issue_date.date()} "
                f"with {actual_count} decisions",
            )
        else:
            messages.success(
                request,
                f"[OK] Updated coverage: {old_count} → {actual_count} decisions "
                f"for {decision.organization.label} on {decision.issue_date.date()}",
            )

    except Exception as e:
        messages.error(request, f"[ERROR] Failed to update coverage: {str(e)}")
        logger.exception(f"Error in update_coverage for {decision.ada}")

    return redirect("admin:health_check_detail", pk=pk)
