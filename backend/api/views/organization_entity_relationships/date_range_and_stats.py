"""
Relationship Date Range & Statistics Views

Provides endpoints for:
- Date range and activity overview for an AFM↔Organization pair
- Filtered statistics for a date range within an AFM↔Organization relationship
"""

from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship
from core.services.decision_facets import amount_sum_excluding_kae
from core.services.financial_calculation_service import financial_service
from django.conf import settings
from django.db import models
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response


def _get_relationship_decisions_qs(afm: str, org_uid: str):
    """
    Build a queryset for decisions linking a specific entity (by AFM)
    and a specific organization.
    """
    return Decision.objects.filter(
        id__in=DecisionEntityRelationship.objects.filter(
            entity__afm=afm
        ).values_list("decision_id", flat=True),
        organization__uid=org_uid,
    )


@swagger_auto_schema(
    method="get",
    manual_parameters=[],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
def relationship_date_range_api(request, afm, orgUid):
    """
    Get the available date range and activity overview for a specific
    AFM↔Organization relationship.

    Returns:
        - earliest_date: first decision date in the relationship
        - latest_date: last decision date in the relationship
        - total_decisions: count of all decisions in the relationship
        - monthly_activity: array of {period, count, amount} for chart
    """
    try:
        decisions_qs = _get_relationship_decisions_qs(afm, orgUid)

        # Delegate to shared projection (single source of truth for date-range
        # metadata, activity chart, and granularity logic)
        from core.services.decision_projections import compute_date_range

        result = compute_date_range(decisions_qs)

        if not result["has_data"]:
            result["message"] = (
                "No decisions found for this entity-organization pair."
            )
            return Response(result)

        # stats are now computed inside compute_date_range — no enrichment needed
        return Response(result)

    except Exception as e:
        logger.exception(
            "Error in relationship_date_range_api for afm={}, orgUid={}",
            afm,
            orgUid,
        )
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": None,
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
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
def relationship_statistics_api(request, afm, orgUid):
    """
    Get server-computed statistics for a specific AFM↔Organization
    relationship filtered by a date range.

    Returns:
        - total_decisions: count of decisions in the window
        - total_amount: sum of all decision amounts
        - avg_amount: average decision amount
        - decisions_with_amounts: count of decisions with non-zero amounts

    Supports partial date ranges: a lone ``start_date`` filters >= start,
    a lone ``end_date`` filters <= end.  Both can be omitted.
    """
    from core.services.decision_facets import (
        apply_date_range,
        parse_date_range_from_request,
    )

    start_dt, end_dt, err = parse_date_range_from_request(request)
    if err:
        return err

    try:
        decisions_qs = _get_relationship_decisions_qs(afm, orgUid)

        # Apply date filter via shared facet (supports partial ranges)
        decisions_qs = apply_date_range(decisions_qs, start_dt=start_dt, end_dt=end_dt)

        # Use financial service for accurate calculations (verified-aware)
        try:
            financial_summary = financial_service.get_global_financial_summary(
                decisions_queryset=decisions_qs
            )
            total_amount = financial_summary.total_amount
        except Exception:
            # Fall back to verified-aware aggregation over amount fields
            total_amount = float(
                decisions_qs.annotate(acc_total=amount_sum_excluding_kae())
                .aggregate(total=models.Sum("acc_total"))["total"]
                or 0
            )

        stats = decisions_qs.aggregate(
            total_decisions=models.Count("id"),
            decisions_with_amounts=models.Count(
                "id", filter=models.Q(amount__isnull=False, amount__gt=0)
            ),
        )

        total_decisions = stats["total_decisions"] or 0
        avg_amount = (float(total_amount) / total_decisions) if total_decisions else 0

        return Response(
            {
                "total_decisions": total_decisions,
                "total_amount": float(total_amount),
                "avg_amount": avg_amount,
                "decisions_with_amounts": stats["decisions_with_amounts"] or 0,
            }
        )

    except Exception as e:
        logger.exception(
            "Error in relationship_statistics_api for afm={}, orgUid={}",
            afm,
            orgUid,
        )
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": None,
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
def relationship_decision_types_api(request, afm, orgUid):
    """
    Get unique decision types with counts and financial data for an
    AFM↔Organization relationship, optionally filtered by date range.

    Scans the entire relationship queryset — not just a paginated batch —
    so users can discover and filter by every type that exists.
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:
        decisions_qs = _get_relationship_decisions_qs(afm, orgUid)

        # Apply date filter. Unlike relationship_statistics_api, partial ranges
        # are supported: a lone start_date filters >= start, a lone end_date
        # filters <= end. This matches the entity/explore decision-types
        # endpoints and avoids silently dropping a filter the client sent.
        if start_date_str or end_date_str:
            start_dt = parse_date(start_date_str) if start_date_str else None
            end_dt = parse_date(end_date_str) if end_date_str else None
            if start_dt:
                decisions_qs = decisions_qs.filter(issue_date_day__gte=start_dt)
            if end_dt:
                decisions_qs = decisions_qs.filter(issue_date_day__lte=end_dt)

        # Use shared projection (single source of truth for the uid-grouped aggregation)
        from core.services.decision_projections import aggregate_decision_types

        return Response(aggregate_decision_types(decisions_qs))

    except Exception as e:
        logger.exception(
            "Error in relationship_decision_types_api for afm={}, orgUid={}",
            afm,
            orgUid,
        )
        return Response(
            {"error": f"Internal server error: {str(e)}"},
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
            "sort_by",
            openapi.IN_QUERY,
            description="Sort: recent, oldest, amount_desc, amount_asc",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "q",
            openapi.IN_QUERY,
            description="Search query",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "decision_types",
            openapi.IN_QUERY,
            description="Comma-separated decision type UIDs",
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
def relationship_decisions_api(request, afm, orgUid):
    """
    Get paginated decisions for an AFM↔Organization relationship.

    Uses the shared facet layer (date range, search, sort, decision types,
    amount range) and the shared paginated-decisions projection.
    """
    from core.services.decision_facets import (
        apply_decision_facets,
        parse_date_range_from_request,
        parse_sort_by,
    )
    from core.services.decision_projections import paginate_decisions

    start_dt, end_dt, err = parse_date_range_from_request(request)
    if err:
        return err

    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))

    try:
        decisions_qs = _get_relationship_decisions_qs(afm, orgUid)

        # Apply shared facets
        qs = apply_decision_facets(
            decisions_qs,
            start_dt=start_dt,
            end_dt=end_dt,
            request=request,
        )

        return Response(paginate_decisions(qs, page=page, page_size=page_size))

    except Exception as e:
        logger.exception(
            "Error in relationship_decisions_api for afm={}, orgUid={}",
            afm,
            orgUid,
        )
        return Response(
            {"error": f"Internal server error: {str(e)}"},
            status=500,
        )
