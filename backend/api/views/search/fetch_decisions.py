from api.utils.date_utils import _parse_optional_date_range
from core.decorators.cache_decorator import cached_view
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "organization_uid",
            openapi.IN_QUERY,
            description="Filter by specific organization UID",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "entity_afm",
            openapi.IN_QUERY,
            description="Filter by specific entity AFM",
            type=openapi.TYPE_STRING,
        ),
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
            description="Results per page",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "q",
            openapi.IN_QUERY,
            description="Search query",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "status",
            openapi.IN_QUERY,
            description="Decision status filter",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "sort_by",
            openapi.IN_QUERY,
            description="Sort order (entity_amount_desc, entity_amount_asc, recent)",
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
        openapi.Parameter(
            "direct_assignments_only",
            openapi.IN_QUERY,
            description="Filter to show only direct assignment decisions (below €37,200 threshold)",
            type=openapi.TYPE_BOOLEAN,
            default=False,
        ),
    ],
)
@cached_view(
    cache_prefix="explore_decisions",
    cache_params=[
        "start_date",
        "end_date",
        "page",
        "page_size",
        "sort_by",
        "organization_uid",
        "entity_afm",
        "direct_assignments_only",
    ],
    end_date_param="end_date",
    should_cache_fn=lambda req: (
        not req.GET.get("q")  # No search query
        and not req.GET.get("decision_types")  # No decision type filters
        and not req.GET.get("organization_ids")  # No org ID filters
        and not req.GET.get("min_amount")  # No amount filters
        and not req.GET.get("max_amount")
        # Specific entity+org pair queries are never pre-warmed, so defer_on_miss
        # would return 202 forever.  Run them synchronously instead — they are
        # heavily filtered and fast.
        and not (req.GET.get("entity_afm") and req.GET.get("organization_uid"))
    ),
    defer_on_miss=True,
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def explore_decisions_optimized_api(request):
    """
    OPTIMIZED: Get paginated decisions with entity amounts included upfront.
    This endpoint eliminates the N+1 query problem by including entity relationship
    data in the initial response, sorted by amount descending by default.

    Supports filtering by:
    - organization_uid: Get all decisions from a specific organization
    - entity_afm: Get all decisions involving a specific entity
    - Both: Drill down to org-entity relationship decisions
    - direct_assignments_only: Filter to show only direct assignment decisions
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    search_query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    sort_by = request.GET.get("sort_by", "entity_amount_desc")  # Default to amount desc

    # Filters
    organization_uid = request.GET.get("organization_uid", "")
    entity_afm = request.GET.get("entity_afm", "")
    decision_types_str = request.GET.get("decision_types", "")
    organization_ids_str = request.GET.get("organization_ids", "")
    min_amount_str = request.GET.get("min_amount", "")
    max_amount_str = request.GET.get("max_amount", "")
    direct_assignments_only = request.GET.get(
        "direct_assignments_only", ""
    ).lower() in ["true", "1", "yes"]

    # Parse filters
    decision_type_uids = (
        [t.strip() for t in decision_types_str.split(",") if t.strip()]
        if decision_types_str
        else []
    )
    organization_ids = (
        [o.strip() for o in organization_ids_str.split(",") if o.strip()]
        if organization_ids_str
        else []
    )

    min_amount = None
    max_amount = None
    try:
        if min_amount_str:
            min_amount = float(min_amount_str)
        if max_amount_str:
            max_amount = float(max_amount_str)
    except ValueError:
        return Response({"error": "Invalid amount format"}, status=400)

    try:
        # Parse date range via shared helper
        start_dt, end_dt, err = _parse_optional_date_range(request)
        if err:
            return err

        from core.services.analytics_precalc_service import compute_explore_decisions

        response_data = compute_explore_decisions(
            start_dt=start_dt,
            end_dt=end_dt,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            page=page,
            page_size=page_size,
            search_query=search_query,
            status_filter=status_filter,
            sort_by=sort_by,
            organization_uid=organization_uid,
            entity_afm=entity_afm,
            decision_type_uids=decision_type_uids,
            organization_ids=organization_ids,
            min_amount=min_amount,
            max_amount=max_amount,
            direct_assignments_only=direct_assignments_only,
        )

        return Response(response_data)

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
