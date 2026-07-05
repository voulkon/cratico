from datetime import timedelta

from api.utils.date_utils import _parse_optional_date_range, _validate_temporal_span
from api.utils.sorting import apply_decision_sorting
from core.decorators.cache_decorator import cached_view
from core.models.decisions import Decision
from core.models.entities import DecisionAmountField
from core.services.feature_flag_service import feature_flags

from core.services.search_analytics_service import SearchAnalyticsService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.core.paginator import Paginator
from django.db import models

from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .base import serialize_decision_with_entities


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
@cached_view(
    cache_prefix="explore_date_range",
    ttl=60 * 60,  # 1 hour — global date boundaries rarely change
    log_cache_operations=True,
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_date_range_global")
def explore_date_range_api_dev(request):
    """Get the global date range and activity overview for temporal exploration"""
    try:
        # Get all decisions queryset (no entity filtering)
        decisions_qs = Decision.objects.all()

        # Single aggregation: date range + count + total amount.
        # We use Decision.amount (the legacy field) here — NOT because accurate
        # amounts via DecisionAmountField are inherently slow, but because this
        # endpoint has no date filter: it must discover the global boundaries
        # first.  Without a date filter, the DecisionAmountField JOIN would scan
        # the entire table.  Every other explore_* endpoint applies a date filter
        # BEFORE computing accurate amounts, so they remain fast and precise.
        # This is the ONLY endpoint that uses the legacy field for this reason.
        date_stats = decisions_qs.aggregate(
            earliest_date=models.Min("issue_date_day"),
            latest_date=models.Max("issue_date_day"),
            total_decisions=models.Count("id"),
            total_amount=models.Sum("amount"),
        )

        total_amount = date_stats["total_amount"] or 0

        if not date_stats["earliest_date"]:
            return Response(
                {
                    "has_data": False,
                    "message": "No decisions found in the database. Contact the administrator if you expect data to be available.",
                    "date_range": None,
                    "activity_chart": [],
                }
            )

        # Calculate optimal granularity based on data span
        earliest = date_stats["earliest_date"]
        latest = date_stats["latest_date"]
        span_days = (latest - earliest).days

        # Choose granularity based on data span (week/quarter have no precomputed field)
        if span_days <= 31:  # Less than a month - daily
            granularity = "day"
            period_column = "issue_date_day"
        elif span_days <= 1825:  # Up to 5 years - monthly
            granularity = "month"
            period_column = "issue_date_month"
        else:  # More than 5 years - yearly
            granularity = "year"
            period_column = "issue_date_year"

        # Get activity data for mini chart - fallback to old amount for aggregation performance
        activity_data = (
            decisions_qs.annotate(period=models.F(period_column))
            .values("period")
            .annotate(
                count=models.Count("id"),
                total_amount=models.Sum(
                    "amount"
                ),  # Keep legacy for aggregation performance
            )
            .order_by("period")
        )

        # Format activity chart data
        chart_data = []
        for item in activity_data:
            period_val = item["period"]
            period_str = (
                str(period_val)
                if granularity == "year"
                else (period_val.isoformat() if period_val else None)
            )
            chart_data.append(
                {
                    "period": period_str,
                    "count": item["count"],
                    "amount": float(item["total_amount"] or 0),
                }
            )

        return Response(
            {
                "has_data": True,
                "date_range": {
                    "earliest": earliest,
                    "latest": latest,
                    "span_days": span_days,
                    "recommended_granularity": granularity,
                },
                "summary": {
                    "total_decisions": date_stats["total_decisions"],
                    "total_amount": float(total_amount),
                    "avg_daily_decisions": round(
                        date_stats["total_decisions"] / max(span_days, 1), 2
                    ),
                    "avg_daily_amount": round(
                        float(total_amount) / max(span_days, 1), 2
                    ),
                },
                "activity_chart": {
                    "data": chart_data,
                    "granularity": granularity,
                },
            }
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
    ],
)
@cached_view(
    cache_prefix="explore_statistics",
    cache_params=["start_date", "end_date"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
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
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_decisions_search")
def explore_decisions_api_dev(request):
    """Get paginated decisions for temporal exploration across all organizations"""
    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    search_query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    sort_by = request.GET.get("sort_by", "recent")

    # Filters
    decision_types_str = request.GET.get("decision_types", "")
    organization_ids_str = request.GET.get("organization_ids", "")
    min_amount_str = request.GET.get("min_amount", "")
    max_amount_str = request.GET.get("max_amount", "")

    # Parse decision types
    decision_type_uids = []
    if decision_types_str:
        decision_type_uids = [
            t.strip() for t in decision_types_str.split(",") if t.strip()
        ]

    # Parse organization IDs
    organization_ids = []
    if organization_ids_str:
        organization_ids = [
            o.strip() for o in organization_ids_str.split(",") if o.strip()
        ]

    # Parse amount filters
    min_amount = None
    max_amount = None
    try:
        if min_amount_str:
            min_amount = float(min_amount_str)
        if max_amount_str:
            max_amount = float(max_amount_str)
    except ValueError:
        return Response({"error": "Invalid amount format"}, status=400)

    # Parse date range via shared helper
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

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
                "start_date": start_date_str,
                "end_date": end_date_str,
                "status": status_filter,
                "sort_by": sort_by,
                "decision_types": decision_types_str,
                "organization_ids": organization_ids_str,
                "min_amount": min_amount_str,
                "max_amount": max_amount_str,
            },
        )

    try:
        # Get all decisions with date-range filter applied via custom queryset
        decisions_qs = Decision.objects.filter_by_date_range(start_dt, end_dt)

        # Apply search filter
        if search_query:
            # Always search by subject and ADA (decision metadata)
            q_filter = models.Q(subject__icontains=search_query) | models.Q(
                ada__icontains=search_query
            )

            # Only search content if PostgreSQL indexing is enabled
            if feature_flags.is_enabled("INDEX_THE_POSTGRES"):
                from django.contrib.postgres.search import SearchQuery

                search_query_obj = SearchQuery(search_query)
                q_filter |= models.Q(text_extraction__search_vector=search_query_obj)

            decisions_qs = decisions_qs.filter(q_filter).distinct()

        # Apply status filter
        if status_filter:
            decisions_qs = decisions_qs.filter(status=status_filter)

        # Apply decision type filter
        if decision_type_uids:
            decisions_qs = decisions_qs.filter(
                decision_type__uid__in=decision_type_uids
            )

        # Apply organization filter
        if organization_ids:
            decisions_qs = decisions_qs.filter(organization__uid__in=organization_ids)

        # Annotate with the sum of linked DecisionAmountField amounts.
        # Because we've already filtered by date (and optionally org/type/status),
        # this JOIN only touches the DecisionAmountField rows for the filtered
        # decisions — not the entire table.  That's the key: filter first, then
        # compute accurate amounts on the small subset.
        decisions_qs = decisions_qs.annotate(
            calculated_amount=models.Sum(
                "amount_fields__amount",
                filter=models.Q(amount_fields__associated_relationship__isnull=False),
            )
        )

        # Apply amount filters
        if min_amount is not None:
            decisions_qs = decisions_qs.filter(amount__gte=min_amount)

        if max_amount is not None:
            decisions_qs = decisions_qs.filter(amount__lte=max_amount)

        # Apply sorting via shared utility
        decisions_qs = apply_decision_sorting(
            decisions_qs, sort_by,
            amount_field="calculated_amount",
            date_field="issue_date_day",
        )

        # Add prefetch_related for optimization
        decisions_qs = decisions_qs.select_related(
            "decision_type", "organization", "text_extraction"
        ).prefetch_related("kae_amounts", "signers")

        # Pagination
        paginator = Paginator(decisions_qs, page_size)
        page_obj = paginator.get_page(page)

        # Log search completion
        if search_tracking:
            search_log = SearchAnalyticsService.log_search_complete(
                search_tracking, paginator.count
            )

        # ── Batch-fetch entity relationships (eliminates N+1) ──────────────
        from core.models.entities import DecisionEntityRelationship
        from django.db.models import Sum

        decision_ids = [d.id for d in page_obj]
        entity_relationships_qs = (
            DecisionEntityRelationship.objects.filter(decision_id__in=decision_ids)
            .select_related("entity")
            .annotate(total_amount=Sum("linked_amounts__amount"))
        )

        relationships_by_decision = {}
        for rel in entity_relationships_qs:
            if rel.decision_id not in relationships_by_decision:
                relationships_by_decision[rel.decision_id] = []
            relationships_by_decision[rel.decision_id].append({
                "role": rel.role,
                "entity": {
                    "afm": rel.entity.afm,
                    "name": rel.entity.name,
                    "entity_type": rel.entity.entity_type,
                },
                "total_amount": float(rel.total_amount) if rel.total_amount else 0,
            })

        # Serialize results with entity data embedded
        results = []
        for decision in page_obj:
            entity_rels = relationships_by_decision.get(decision.id, [])
            decision_data = serialize_decision_with_entities(decision, entity_rels)

            # Use calculated amount if available
            if (
                hasattr(decision, "calculated_amount")
                and decision.calculated_amount is not None
            ):
                decision_data["amount"] = float(decision.calculated_amount)

            # Add organization as object for temporal exploration
            if decision.organization:
                decision_data["organization"] = {
                    "uid": decision.organization.uid,
                    "label": decision.organization.label,
                }
            results.append(decision_data)

        response_data = {
            "results": results,
            "pagination": {
                "current_page": page,
                "total_pages": paginator.num_pages,
                "total_count": paginator.count,
                "has_next": page_obj.has_next(),
                "has_previous": page_obj.has_previous(),
                "page_size": page_size,
            },
            "filters": {
                "search_query": search_query,
                "status": status_filter,
                "start_date": start_date_str,
                "end_date": end_date_str,
                "sort_by": sort_by,
                "decision_types": decision_types_str,
                "organization_ids": organization_ids_str,
                "min_amount": min_amount,
                "max_amount": max_amount,
            },
        }

        # Add search tracking ID for frontend click tracking
        if search_tracking and "search_log" in locals():
            response_data["search_log_id"] = search_log.id

        return Response(response_data)

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
@cached_view(
    cache_prefix="explore_decision_types",
    cache_params=["start_date", "end_date"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
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
@cached_view(
    cache_prefix="explore_orgs",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
    defer_on_miss=True,
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
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
