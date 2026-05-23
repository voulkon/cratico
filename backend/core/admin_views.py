import calendar
from datetime import date, datetime, timedelta

from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.models.import_jobs import DateCoverage
from core.models.organizations import (
    Organization,
    OrganizationStatus,
    Signer,
    SignerUnit,
    Unit,
)
from core.services.decision_analysis_service import DecisionAnalysisService
from core.services.organization_chart_service import OrganizationChartService
from core.services.search_service import SearchService
from django.contrib.admin.views.decorators import staff_member_required
from django.http import JsonResponse
from django.shortcuts import render
from loguru import logger


def get_month_calendar_data(month, year, entity_type, entity_id):
    """Generate calendar data for a specific month including decision counts"""
    # Get first and last day of the month
    first_day = date(year, month, 1)
    # Last day is first day of next month - 1 day
    if month == 12:
        last_day = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last_day = date(year, month + 1, 1) - timedelta(days=1)

    # Get calendar info
    calendar.monthcalendar(year, month)

    # Get decision coverage data if an entity is selected
    coverage_data = {}
    if entity_id:
        # Get the date coverage for the selected entity
        coverage_query = DateCoverage.objects.filter(date__year=year, date__month=month)

        if entity_type == "organization":
            coverage_query = coverage_query.filter(organization_id=entity_id)
        else:
            coverage_query = coverage_query.filter(signer_id=entity_id)

        # Create lookup by date
        for coverage in coverage_query:
            coverage_data[coverage.date] = coverage.decision_count

    # Build calendar data
    calendar_data = []

    # Add days from previous month to fill first week
    first_weekday = first_day.weekday()  # Monday is 0, Sunday is 6
    first_weekday = (first_weekday + 1) % 7  # Convert to Sunday is 0

    if first_weekday > 0:
        # Calculate days from previous month
        prev_month = month - 1
        prev_year = year
        if prev_month < 1:
            prev_month = 12
            prev_year -= 1

        prev_month_days = calendar.monthrange(prev_year, prev_month)[1]
        for i in range(first_weekday):
            day_num = prev_month_days - first_weekday + i + 1
            calendar_data.append(
                {
                    "day": day_num,
                    "date": date(prev_year, prev_month, day_num).isoformat(),
                    "is_current_month": False,
                    "count": 0,
                    "has_data": False,
                }
            )

    # Add days from current month
    for day in range(1, last_day.day + 1):
        current_date = date(year, month, day)
        count = coverage_data.get(current_date, 0)
        calendar_data.append(
            {
                "day": day,
                "date": current_date.isoformat(),
                "is_current_month": True,
                "count": count,
                "has_data": count > 0,
            }
        )

    # Add days from next month to fill last week
    remaining_days = 42 - len(calendar_data)  # 6 weeks × 7 days = 42
    if remaining_days > 0:
        next_month = month + 1
        next_year = year
        if next_month > 12:
            next_month = 1
            next_year += 1

        for day in range(1, remaining_days + 1):
            calendar_data.append(
                {
                    "day": day,
                    "date": date(next_year, next_month, day).isoformat(),
                    "is_current_month": False,
                    "count": 0,
                    "has_data": False,
                }
            )

    return calendar_data


@staff_member_required
def coverage_explorer(request):
    """View for exploring decision coverage by organization, unit, or signer"""
    # Get selected entity
    entity_type = request.GET.get(
        "entity_type", "organization"
    )  # 'organization', 'unit', or 'signer'
    entity_id = request.GET.get("entity_id")

    # Get view type (quarter, year, or multi-year)
    view_type = request.GET.get("view", "quarter")  # 'quarter', 'year', or 'multi-year'

    # Get the current month or the requested month
    month_param = request.GET.get("month", "")
    year_param = request.GET.get("year", "")

    try:
        month = int(month_param) if month_param else datetime.now().month
    except ValueError:
        month = datetime.now().month

    try:
        year = int(year_param) if year_param else datetime.now().year
    except ValueError:
        year = datetime.now().year

    # Handle entity type validation
    if entity_type not in ["organization", "unit", "signer"]:
        entity_type = "organization"  # Default fallback

    if view_type == "multi-year":
        # Create multi-year view (10 years centered around current year)
        start_year = year - 5
        end_year = year + 4

        multi_year_data = []
        for target_year in range(start_year, end_year + 1):
            # Get year summary data
            year_summary = get_year_summary_data(target_year, entity_type, entity_id)
            multi_year_data.append(
                {
                    "year": target_year,
                    "total_decisions": year_summary["total_decisions"],
                    "months_with_data": year_summary["months_with_data"],
                    "has_data": year_summary["total_decisions"] > 0,
                }
            )

        # Calculate navigation links for multi-year view
        prev_decade_year = year - 10
        next_decade_year = year + 10

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "center_year": year,
            "multi_year_data": multi_year_data,
            "start_year": start_year,
            "end_year": end_year,
            "prev_decade_year": prev_decade_year,
            "next_decade_year": next_decade_year,
        }
    elif view_type == "year":
        # Existing year view logic
        year_calendar = []
        for month_offset in range(12):
            target_month = month_offset + 1
            target_year = year

            month_data = {
                "month": target_month,
                "year": target_year,
                "name": calendar.month_name[target_month],
                "days": get_month_calendar_data(
                    target_month, target_year, entity_type, entity_id
                ),
            }
            year_calendar.append(month_data)

        # Calculate navigation links for year view
        prev_year = year - 1
        next_year = year + 1

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "year": year,
            "year_calendar": year_calendar,
            "prev_year": prev_year,
            "next_year": next_year,
        }
    else:
        # Existing quarter view logic
        quarter_calendar = []
        for month_offset in range(-1, 2):
            target_month = month + month_offset
            target_year = year

            if target_month < 1:
                target_month += 12
                target_year -= 1
            elif target_month > 12:
                target_month -= 12
                target_year += 1

            month_data = {
                "month": target_month,
                "year": target_year,
                "name": calendar.month_name[target_month],
                "days": get_month_calendar_data(
                    target_month, target_year, entity_type, entity_id
                ),
            }
            quarter_calendar.append(month_data)

        # Calculate navigation links for quarter
        prev_quarter_month = month - 3
        prev_quarter_year = year
        if prev_quarter_month < 1:
            prev_quarter_month += 12
            prev_quarter_year -= 1

        next_quarter_month = month + 3
        next_quarter_year = year
        if next_quarter_month > 12:
            next_quarter_month -= 12
            next_quarter_year += 1

        # Create quarter name
        if month in (1, 2, 3):
            quarter_name = "Q1"
        elif month in (4, 5, 6):
            quarter_name = "Q2"
        elif month in (7, 8, 9):
            quarter_name = "Q3"
        else:
            quarter_name = "Q4"

        quarter_name = f"{quarter_name} {year}"

        context = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": get_entity_name(entity_type, entity_id),
            "view_type": view_type,
            "year": year,
            "quarter_name": quarter_name,
            "quarter_calendar": quarter_calendar,
            "prev_quarter_month": prev_quarter_month,
            "prev_quarter_year": prev_quarter_year,
            "next_quarter_month": next_quarter_month,
            "next_quarter_year": next_quarter_year,
        }

    return render(request, "admin/coverage_explorer.html", context)


def get_entity_name(entity_type, entity_id):
    """Helper function to get entity name"""
    entity_name = None
    if entity_id:
        try:
            if entity_type == "organization":
                org = Organization.objects.get(uid=entity_id)
                entity_name = org.label
            elif entity_type == "unit":
                unit = Unit.objects.get(uid=entity_id)
                entity_name = unit.label
            else:  # signer
                signer = Signer.objects.get(uid=entity_id)
                entity_name = f"{signer.last_name}, {signer.first_name}"
        except (Organization.DoesNotExist, Unit.DoesNotExist, Signer.DoesNotExist):
            pass
    return entity_name


def get_year_summary_data(year, entity_type, entity_id):
    """Get summary data for a specific year"""
    total_decisions = 0
    months_with_data = 0

    if entity_id:
        # Get coverage data for the entire year
        coverage_query = DateCoverage.objects.filter(date__year=year)

        if entity_type == "organization":
            coverage_query = coverage_query.filter(organization_id=entity_id)
        else:
            coverage_query = coverage_query.filter(signer_id=entity_id)

        # Sum total decisions
        total_decisions = sum(coverage.decision_count for coverage in coverage_query)

        # Count months with data
        months_with_data = coverage_query.values("date__month").distinct().count()

    return {"total_decisions": total_decisions, "months_with_data": months_with_data}


@staff_member_required
def entity_search(request):
    """Search for organizations, units, or signers for the coverage explorer."""
    query = request.GET.get("q", "")
    entity_type = request.GET.get("entity_type", "organization")

    search_service = SearchService()
    results = []

    if query:
        if entity_type == "organization":
            organizations = search_service.search_organizations(query)
            results = [
                {
                    "id": org.uid,
                    "text": org.label,
                    "latin_name": org.latin_name,
                }
                for org in organizations
            ]

            # If no organizations found, search for units
            if not results:
                units = search_service.search_units(query)
                results = [
                    {
                        "id": unit.uid,
                        "text": unit.label,
                        "latin_name": None,  # Units don't have latin_name
                        "type": "unit",  # Add type to distinguish from organizations
                    }
                    for unit in units
                ]
        elif entity_type == "unit":
            units = search_service.search_units(query)
            results = [
                {
                    "id": unit.uid,
                    "text": unit.label,
                    "latin_name": None,
                    "organization": (
                        unit.organization.label if unit.organization else None
                    ),
                    "organization_id": (
                        unit.organization.uid if unit.organization else None
                    ),
                }
                for unit in units
            ]
        else:  # signers
            signers = search_service.search_signers(query)
            results = [
                {
                    "id": signer.uid,
                    "text": f"{signer.last_name}, {signer.first_name}",
                    "last_name": signer.last_name,
                    "first_name": signer.first_name,
                    "organization": (
                        signer.organization.label if signer.organization else None
                    ),
                    "organization_id": (
                        signer.organization.uid if signer.organization else None
                    ),
                }
                for signer in signers
            ]

    return JsonResponse({"results": results})


@staff_member_required
def organization_network(request):
    """View for visualizing organization networks"""
    org_uid = request.GET.get("org_uid")
    depth = int(request.GET.get("depth", 2))

    # Get initial organization
    org = None
    if org_uid:
        org = Organization.objects.get(pk=org_uid)

    # Get organizations for dropdown
    organizations = Organization.objects.filter(status=OrganizationStatus.ACTIVE)[:100]

    # Build network data
    nodes = []
    edges = []

    if org:
        # Add the main organization
        nodes.append(
            {
                "id": org.uid,
                "label": org.label,
                "group": "organization",
                "title": f"Organization: {org.label}",
                "level": 0,
            }
        )

        # Add units
        for unit in Unit.objects.filter(organization=org):
            nodes.append(
                {
                    "id": f"unit_{unit.uid}",
                    "label": unit.label,
                    "group": "unit",
                    "title": f"Unit: {unit.label}",
                    "level": 1,
                }
            )
            # Connect to organization
            edges.append(
                {
                    "from": org.uid,
                    "to": f"unit_{unit.uid}",
                    "title": "Has Unit",
                    "arrows": "to",
                }
            )

            # Add parent-child unit relationships
            if unit.parent:
                edges.append(
                    {
                        "from": f"unit_{unit.parent.uid}",
                        "to": f"unit_{unit.uid}",
                        "title": "Parent Unit",
                        "arrows": "to",
                        "dashes": True,
                    }
                )

        # Add signers
        for signer in Signer.objects.filter(organization=org):
            nodes.append(
                {
                    "id": f"signer_{signer.uid}",
                    "label": f"{signer.first_name} {signer.last_name}",
                    "group": "signer",
                    "title": f"Signer: {signer.first_name} {signer.last_name}",
                    "level": 2,
                }
            )
            # Connect to organization
            edges.append(
                {
                    "from": org.uid,
                    "to": f"signer_{signer.uid}",
                    "title": "Has Signer",
                    "arrows": "to",
                }
            )

            # Connect signers to units
            for signer_unit in SignerUnit.objects.filter(signer=signer):
                edges.append(
                    {
                        "from": f"signer_{signer.uid}",
                        "to": f"unit_{signer_unit.unit.uid}",
                        "title": f"Position: {signer_unit.position.label}",
                        "arrows": "to",
                    }
                )

        # Add supervisor relationship if depth > 1 and it exists
        if depth > 1 and org.supervisor_org_uid:
            try:
                supervisor = Organization.objects.get(uid=org.supervisor_org_uid)
                nodes.append(
                    {
                        "id": supervisor.uid,
                        "label": supervisor.label,
                        "group": "supervisor",
                        "title": f"Supervisor: {supervisor.label}",
                        "level": -1,
                    }
                )
                edges.append(
                    {
                        "from": supervisor.uid,
                        "to": org.uid,
                        "title": "Supervises",
                        "arrows": "to",
                        "width": 2,
                    }
                )
            except Organization.DoesNotExist:
                pass

    return render(
        request,
        "admin/organization_network.html",
        {
            "organization": org,
            "organizations": organizations,
            "nodes": nodes,
            "edges": edges,
        },
    )


@staff_member_required
def organization_org_chart(request):
    """View for traditional org chart visualization"""
    org_uid = request.GET.get("org_uid")

    # Use shared service for core business logic
    chart_service = OrganizationChartService()
    org_chart_data = chart_service.get_organization_chart_data(org_uid)

    # Admin-specific rendering
    return render(
        request,
        "admin/organization_chart.html",
        {
            "org_chart_data": org_chart_data,
        },
    )


def build_unit_tree(unit):
    """Helper function to build hierarchical unit tree"""
    # Create unit node
    unit_data = {"id": unit.uid, "name": unit.label, "title": "Unit", "children": []}

    # Add signers as children
    for signer_unit in SignerUnit.objects.filter(unit=unit).select_related(
        "signer", "position"
    ):
        unit_data["children"].append(
            {
                "id": signer_unit.signer.uid,
                "name": f"{signer_unit.signer.first_name} {signer_unit.signer.last_name}",
                "title": signer_unit.position.label,
                "className": "signer-node",
            }
        )

    # Recursively add child units
    for child_unit in Unit.objects.filter(parent=unit):
        unit_data["children"].append(build_unit_tree(child_unit))

    return unit_data


@staff_member_required
def document_processing_dashboard(request):
    """Dashboard for document extraction processing status"""
    from django.db.models import Avg, Count, ExpressionWrapper, fields
    from django.db.models.functions import TruncDate

    # Status breakdown
    status_counts = (
        DocumentExtraction.objects.values("extraction_status")
        .annotate(count=Count("id"))
        .order_by("extraction_status")
    )

    # Provider breakdown
    provider_counts = (
        DocumentExtraction.objects.exclude(extraction_provider__isnull=True)
        .values("extraction_provider")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Processing time by provider
    provider_times = (
        DocumentExtraction.objects.exclude(processing_time_ms__isnull=True)
        .values("extraction_provider")
        .annotate(
            avg_time=ExpressionWrapper(
                Avg("processing_time_ms") / 1000, output_field=fields.FloatField()
            )
        )
        .order_by("extraction_provider")
    )

    # Daily processing volume
    daily_volume = (
        DocumentExtraction.objects.exclude(extraction_date__isnull=True)
        .annotate(date=TruncDate("extraction_date"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("-date")[:30]
    )

    # Success rate over time (last 30 days)
    success_rates = []
    for day_data in daily_volume:
        day = day_data["date"]
        total = day_data["count"]
        success = DocumentExtraction.objects.filter(
            extraction_date__date=day, extraction_status=ProcessingStatus.COMPLETED
        ).count()

        if total > 0:
            success_rates.append({"date": day, "rate": round(success / total * 100, 1)})

    # Recent failures
    recent_failures = DocumentExtraction.objects.filter(
        extraction_status=ProcessingStatus.FAILED
    ).order_by("-updated_at")[:10]

    context = {
        "status_counts": status_counts,
        "provider_counts": provider_counts,
        "provider_times": provider_times,
        "daily_volume": daily_volume,
        "success_rates": success_rates,
        "recent_failures": recent_failures,
        "total_extractions": DocumentExtraction.objects.count(),
        "total_completed": DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.COMPLETED
        ).count(),
        "total_failed": DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.FAILED
        ).count(),
        "pending_count": DocumentExtraction.objects.filter(
            extraction_status__in=[
                ProcessingStatus.PENDING,
                ProcessingStatus.PROCESSING,
                ProcessingStatus.NEEDS_VISION,
            ]
        ).count(),
    }

    return render(request, "admin/document_processing_dashboard.html", context)


@staff_member_required
def document_search(request):
    """Advanced search interface for document content"""
    query = request.GET.get("q", "")
    provider = request.GET.get("provider", "")
    status = request.GET.get("status", "")
    is_scanned = request.GET.get("is_scanned", "")

    search_service = SearchService()

    # Convert is_scanned to boolean if provided
    is_scanned_bool = None
    if is_scanned:
        is_scanned_bool = is_scanned == "true"

    # Perform search
    search_results = search_service.search_documents(
        query=query, provider=provider, status=status, is_scanned=is_scanned_bool
    )

    results = search_results["results"]
    count = search_results["count"]

    # Get form options
    options = search_service.get_document_search_options()

    context = {
        "query": query,
        "results": results,
        "count": count,
        "providers": options["providers"],
        "statuses": options["statuses"],
        "provider_filter": provider,
        "status_filter": status,
        "is_scanned_filter": is_scanned,
    }

    return render(request, "admin/document_search.html", context)


@staff_member_required
def daily_decision_analysis(request):
    """Admin view for analyzing daily decision composition"""
    # Get target date from request
    date_param = request.GET.get("date", "")

    try:
        if date_param:
            target_date = datetime.strptime(date_param, "%Y-%m-%d").date()
        else:
            target_date = date.today() - timedelta(days=1)  # Default to yesterday
    except ValueError:
        target_date = date.today() - timedelta(days=1)

    # Initialize analysis service
    analysis_service = DecisionAnalysisService()

    # Get comprehensive analysis
    analysis_data = analysis_service.get_daily_decision_analysis(target_date)

    # Calculate navigation dates
    prev_date = target_date - timedelta(days=1)
    next_date = target_date + timedelta(days=1)

    # Don't allow future dates
    if next_date > date.today():
        next_date = None

    context = {
        "target_date": target_date,
        "prev_date": prev_date,
        "next_date": next_date,
        "analysis": analysis_data,
    }

    return render(request, "admin/daily_decision_analysis.html", context)


@staff_member_required
def decision_analysis_api(request):
    """JSON API endpoint for decision analysis data"""
    target_date_str = request.GET.get("date")
    comparison_dates = request.GET.getlist("compare_dates")

    analysis_service = DecisionAnalysisService()

    try:
        if target_date_str:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
            analysis_data = analysis_service.get_daily_decision_analysis(target_date)
        elif comparison_dates:
            # Compare multiple dates
            dates = [datetime.strptime(d, "%Y-%m-%d").date() for d in comparison_dates]
            analysis_data = analysis_service.compare_daily_patterns(dates)
        else:
            # Default to yesterday
            target_date = date.today() - timedelta(days=1)
            analysis_data = analysis_service.get_daily_decision_analysis(target_date)

        return JsonResponse(analysis_data, safe=False)

    except ValueError as e:
        return JsonResponse({"error": f"Invalid date format: {str(e)}"}, status=400)
    except Exception as e:
        logger.error(f"Decision analysis API error: {str(e)}")
        return JsonResponse({"error": "Internal server error"}, status=500)


@staff_member_required
def fetch_daily_decisions(request):
    """Admin view to trigger fetching decisions for a specific day"""
    if request.method == "POST":
        target_date_str = request.POST.get("date")
        request.POST.get("force", False)

        try:
            target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return JsonResponse(
                {"success": False, "error": "Invalid date format"}, status=400
            )

        try:
            # Import here to avoid circular imports
            from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
            from core.importers.decisions import DecisionImporter
            from core.services.decision_ingestion_service import (
                DecisionIngestionService,
            )

            # Create service components
            fetcher = DiavgeiaFetcher()
            decision_importer = DecisionImporter()
            service = DecisionIngestionService(
                diavgeia_fetcher=fetcher,
                decision_importer=decision_importer,
            )

            # Fetch decisions for the day
            result = service.fetch_daily_decisions(
                target_date=target_date, save_to_db=True
            )

            return JsonResponse(
                {
                    "success": True,
                    "message": f'Successfully fetched {result["processed_count"]} decisions for {target_date}',
                    "processed_count": result["processed_count"],
                    "date": target_date.isoformat(),
                }
            )

        except Exception as e:
            logger.error(f"Error fetching decisions for {target_date}: {str(e)}")
            return JsonResponse(
                {"success": False, "error": f"Failed to fetch decisions: {str(e)}"},
                status=500,
            )

    return JsonResponse({"success": False, "error": "Method not allowed"}, status=405)
