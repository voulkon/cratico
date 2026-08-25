from api.utils.date_utils import _parse_optional_date_range, _validate_temporal_span
from core.decorators.cache_decorator import cached_view
from core.models.decisions import Decision

from core.services.search_analytics_service import SearchAnalyticsService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response



@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="explore_date_range",
    ttl=60 * 60,  # 1 hour — global date boundaries rarely change
    log_cache_operations=True,
)
@monitor_query_performance(operation="temporal_date_range_global")
def explore_date_range_api_dev(request):
    """Get the global date range and activity overview for temporal exploration.

    Delegates to the shared ``compute_date_range`` projection — same logic
    (date aggregation, granularity selection, activity-chart building) used
    by the entity, relationship, and unified endpoints.

    Uses ``Decision.amount`` (the legacy field) for aggregation — NOT the
    accurate ``DecisionAmountField`` join — because this endpoint has no
    date filter: it must discover global boundaries first, and a
    ``DecisionAmountField`` JOIN would scan the entire table.
    """
    try:
        from core.services.decision_projections import compute_date_range

        decisions_qs = Decision.objects.all()
        result = compute_date_range(decisions_qs)

        if not result["has_data"]:
            result["message"] = (
                "No decisions found in the database. "
                "Contact the administrator if you expect data to be available."
            )

        return Response(result)

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="explore_statistics",
    cache_params=["start_date", "end_date"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@monitor_query_performance(operation="temporal_statistics_global")
def explore_statistics_api_dev(request):
    """Get statistics for temporal exploration across all organizations"""
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    span_err = _validate_temporal_span(start_dt, end_dt)
    if span_err:
        return span_err

    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")

    try:
        from core.services.analytics_precalc_service import compute_explore_statistics

        return Response(
            compute_explore_statistics(
                start_dt=start_dt,
                end_dt=end_dt,
                start_date_str=start_date_str,
                end_date_str=end_date_str,
            )
        )

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "page",
            openapi.IN_QUERY,
            description="Page number",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "page_size",
            openapi.IN_QUERY,
            description="Page size",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "q", openapi.IN_QUERY, description="Search query", type=openapi.TYPE_STRING
        ),
        openapi.Parameter(
            "status",
            openapi.IN_QUERY,
            description="Filter by status",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "sort_by",
            openapi.IN_QUERY,
            description="Sort by: recent, amount_desc, amount_asc",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "decision_types",
            openapi.IN_QUERY,
            description="Comma-separated decision type UIDs",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "organization_ids",
            openapi.IN_QUERY,
            description="Comma-separated organization UIDs",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "min_amount",
            openapi.IN_QUERY,
            description="Minimum amount filter",
            type=openapi.TYPE_NUMBER,
        ),
        openapi.Parameter(
            "max_amount",
            openapi.IN_QUERY,
            description="Maximum amount filter",
            type=openapi.TYPE_NUMBER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@monitor_query_performance(operation="temporal_decisions_search")
def explore_decisions_api_dev(request):
    """Get paginated decisions for temporal exploration across all organizations.

    Delegates filtering to ``apply_decision_facets`` and pagination to
    ``paginate_decisions`` (the shared layer).  Keeps the temporal-span
    guard (≤32 days) and search-analytics tracking that are intentionally
    scoped to the explore endpoint.
    """
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    search_query = request.GET.get("q", "")

    # Parse date range via shared helper (also validates format)
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    # Keep temporal-span guard — the unified endpoint intentionally omits
    # this because entity/relationship sources need 6-month+ ranges.
    span_err = _validate_temporal_span(start_dt, end_dt)
    if span_err:
        return span_err

    # Start search analytics tracking
    search_tracking = None
    if search_query:
        search_tracking = SearchAnalyticsService.log_search_start(
            query=search_query,
            search_types=["metadata", "content"],
            entity_type="temporal",
            entity_id="all",
            request=request,
            filters_applied={
                "start_date": request.GET.get("start_date", ""),
                "end_date": request.GET.get("end_date", ""),
                "status": request.GET.get("status", ""),
                "sort_by": request.GET.get("sort_by", "recent"),
            },
        )

    try:
        from core.services.decision_facets import apply_decision_facets
        from core.services.decision_projections import paginate_decisions

        # Build base queryset and apply all standard facets via shared layer
        # (date range, search, status, decision types, org IDs, amount
        # range, direct-only, viewed, sort — with calculated_amount annot.)
        decisions_qs = Decision.objects.all()
        decisions_qs = apply_decision_facets(decisions_qs, request=request)

        # Build filters dict for response echo
        filters = {
            "search_query": search_query,
            "status": request.GET.get("status", ""),
            "start_date": request.GET.get("start_date", ""),
            "end_date": request.GET.get("end_date", ""),
            "sort_by": request.GET.get("sort_by", "recent"),
            "decision_types": request.GET.get("decision_types", ""),
            "organization_ids": request.GET.get("organization_ids", ""),
            "min_amount": request.GET.get("min_amount", ""),
            "max_amount": request.GET.get("max_amount", ""),
        }

        # Paginate via shared layer (handles select_related, N+1 entity
        # relationships, calculated_amount→amount, organization object)
        result = paginate_decisions(
            decisions_qs,
            page=page,
            page_size=page_size,
            filters=filters,
        )

        # Log search completion (uses total_count from paginate_decisions)
        if search_tracking:
            search_log = SearchAnalyticsService.log_search_complete(
                search_tracking, result["pagination"]["total_count"]
            )
            result["search_log_id"] = search_log.id

        return Response(result)

    except ValueError as e:
        return Response({"error": str(e)}, status=400)
    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="explore_decision_types",
    cache_params=["start_date", "end_date"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@monitor_query_performance(operation="temporal_decision_types")
def explore_decision_types_api_dev(request):
    """Get available decision types for temporal exploration"""
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    span_err = _validate_temporal_span(start_dt, end_dt)
    if span_err:
        return span_err

    try:
        from core.services.analytics_precalc_service import compute_explore_decision_types

        return Response(compute_explore_decision_types(start_dt=start_dt, end_dt=end_dt))

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of organizations to return",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Number of organizations to skip (for infinite-scroll pagination)",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="explore_orgs",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@monitor_query_performance(operation="temporal_organizations")
def explore_organizations_api_dev(request):
    """Get organizations with decision activity for temporal exploration"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 50))
    offset = int(request.GET.get("offset", 0))

    # Validate temporal span on the raw query params
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err
    span_err = _validate_temporal_span(start_dt, end_dt)
    if span_err:
        return span_err

    try:
        from core.services.analytics_precalc_service import compute_explore_orgs

        return Response(compute_explore_orgs(start_date_str, end_date_str, limit, offset))

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
