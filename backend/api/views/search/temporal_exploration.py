from datetime import timedelta

from api.utils.date_utils import _parse_optional_date_range
from api.utils.sorting import apply_decision_sorting
from core.decorators.cache_decorator import cached_view
from core.models.decisions import Decision
from core.services.feature_flag_service import feature_flags
from core.services.financial_calculation_service import FinancialCalculationService
from core.services.search_analytics_service import SearchAnalyticsService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.core.paginator import Paginator
from django.db import models

from django.utils import timezone
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .base import calculate_financial_summary, serialize_decision_with_content_info


@swagger_auto_schema(...)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def explore_date_range_api_dev(request):
    """Get the global date range and activity overview for temporal exploration"""
    # Move all explore_* endpoints here


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def explore_statistics_api_dev(request):
    """Get statistics for temporal exploration across all organizations"""
    # Move temporal exploration endpoints here


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
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_date_range_global")
def explore_date_range_api_dev(request):
    """Get the global date range and activity overview for temporal exploration"""
    try:
        # Use financial service for improved calculations
        financial_service = FinancialCalculationService()

        # Get all decisions queryset (no entity filtering)
        decisions_qs = Decision.objects.all()

        # Get date range with accurate financial calculations
        date_stats = decisions_qs.aggregate(
            earliest_date=models.Min("issue_date_day"),
            latest_date=models.Max("issue_date_day"),
            total_decisions=models.Count("id"),
        )

        # Use financial service to get accurate total amounts across system
        total_amount_accurate = financial_service.get_global_financial_summary(
            decisions_queryset=decisions_qs
        )["total_amount"]

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

        # Calculate some useful stats for the chart
        amounts = [item["amount"] for item in chart_data if item["amount"] > 0]
        counts = [item["count"] for item in chart_data]

        chart_stats = {
            "max_amount": max(amounts) if amounts else 0,
            "max_count": max(counts) if counts else 0,
            "avg_amount": sum(amounts) / len(amounts) if amounts else 0,
            "avg_count": sum(counts) / len(counts) if counts else 0,
            "periods_with_activity": len([c for c in counts if c > 0]),
            "total_periods": len(chart_data),
        }

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
                    "total_amount": float(total_amount_accurate),  # Use accurate amount
                    "total_amount_legacy": float(
                        decisions_qs.aggregate(total=models.Sum("amount"))["total"] or 0
                    ),  # For comparison
                    "avg_daily_decisions": round(
                        date_stats["total_decisions"] / max(span_days, 1), 2
                    ),
                    "avg_daily_amount": round(
                        float(total_amount_accurate) / max(span_days, 1), 2
                    ),
                },
                "activity_chart": {
                    "data": chart_data,
                    "granularity": granularity,
                    "stats": chart_stats,
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
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_statistics_global")
def explore_statistics_api_dev(request):
    """Get statistics for temporal exploration across all organizations"""
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    # Default to last 12 months if no dates provided
    end_date = end_dt if end_dt else timezone.now()
    start_date = start_dt if start_dt else end_date - timedelta(days=365)

    try:
        # Use financial service for accurate calculations
        financial_service = FinancialCalculationService()

        # Get all decisions (no entity filtering)
        decisions_qs = Decision.objects.all()

        # Apply date filters (pass datetimes directly since they're already TZ-aware)
        filtered_qs = decisions_qs.filter_by_date_range(start_date, end_date)

        # Calculate basic statistics using calculated amounts for accuracy
        # We annotate with the sum of linked amounts per decision
        stats_qs = filtered_qs.annotate(
            calculated_amount=models.Sum(
                "amount_fields__amount",
                filter=models.Q(amount_fields__associated_relationship__isnull=False),
            )
        )

        stats = stats_qs.aggregate(
            total_decisions=models.Count("id"),
            avg_amount=models.Avg("calculated_amount"),
            max_amount=models.Max("calculated_amount"),
            min_amount=models.Min("calculated_amount"),
        )

        # Get accurate financial summary using financial service
        financial_summary = financial_service.get_global_financial_summary(filtered_qs)

        # Enhanced calculate_financial_summary that uses both approaches
        enhanced_financial_summary = calculate_financial_summary(filtered_qs)

        # Count unique organizations with decisions in this period
        organizations_count = filtered_qs.values("organization").distinct().count()

        # Monthly breakdown for charts using legacy amounts for performance
        try:
            monthly_stats = (
                filtered_qs.annotate(month=models.F("issue_date_month"))
                .values("month")
                .annotate(
                    count=models.Count("id"),
                    amount=models.Sum("amount"),  # Legacy for chart performance
                )
                .order_by("month")
            )
        except Exception:
            monthly_stats = []

        # Top decision types with legacy amounts
        top_types = (
            filtered_qs.values("decision_type__label")
            .annotate(
                count=models.Count("id"),
                total_amount=models.Sum("amount"),  # Legacy for aggregation
            )
            .order_by("-count")[:10]
        )

        # Top organizations by decision count with legacy amounts
        top_organizations = (
            filtered_qs.values("organization__label", "organization__uid")
            .annotate(
                count=models.Count("id"),
                total_amount=models.Sum("amount"),  # Legacy for aggregation
            )
            .order_by("-count")[:10]
        )

        # Status breakdown
        status_breakdown = (
            filtered_qs.values("status")
            .annotate(count=models.Count("id"))
            .order_by("-count")
        )

        # Recent decisions
        recent_decisions = filtered_qs.order_by("-issue_date_day")[:5].values(
            "ada",
            "subject",
            "issue_date_day",
            "amount",
            "decision_type__label",
            "organization__label",
            "organization__uid",
        )

        return Response(
            {
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "days_count": (end_date - start_date).days + 1,
                },
                "summary": {
                    "decisions": {
                        "total_count": stats["total_decisions"] or 0,
                        "avg_amount": float(stats["avg_amount"] or 0),
                        "max_amount": float(stats["max_amount"] or 0),
                        "min_amount": float(stats["min_amount"] or 0),
                    },
                    "financial": enhanced_financial_summary,
                    "financial_accurate": {
                        "total_amount": float(financial_summary["total_amount"]),
                        "calculation_method": financial_summary["calculation_method"],
                        "accuracy_improvement": float(
                            financial_summary["accuracy_improvement"]
                        ),
                    },
                    "organizations_count": organizations_count,
                    "status_breakdown": {
                        item["status"]: item["count"] for item in status_breakdown
                    },
                },
                "charts": {
                    "monthly_breakdown": [
                        {
                            "month": (
                                item["month"].isoformat()
                                if hasattr(item["month"], "isoformat")
                                else str(item["month"])
                            ),
                            "count": item["count"],
                            "amount": float(item["amount"] or 0),
                        }
                        for item in monthly_stats
                    ],
                    "top_decision_types": [
                        {
                            "type": item["decision_type__label"] or "Unknown",
                            "count": item["count"],
                            "total_amount": float(item["total_amount"] or 0),
                        }
                        for item in top_types
                    ],
                    "top_organizations": [
                        {
                            "name": item["organization__label"] or "Unknown",
                            "uid": item["organization__uid"],
                            "count": item["count"],
                            "total_amount": float(item["total_amount"] or 0),
                        }
                        for item in top_organizations
                    ],
                },
                "recent_decisions": [
                    {
                        "ada": item["ada"],
                        "subject": item["subject"],
                        "issue_date": (
                            item["issue_date_day"].isoformat()
                            if item["issue_date_day"]
                            else None
                        ),
                        "amount": float(item["amount"]) if item["amount"] else None,
                        "decision_type": item["decision_type__label"],
                        "organization": item["organization__label"],
                        "organization_id": item["organization__uid"],
                    }
                    for item in recent_decisions
                ],
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

        # Annotate with calculated amount from DecisionAmountField
        # This sums up amounts that are linked to entity relationships
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

        # Serialize results using the new function
        results = []
        for decision in page_obj:
            decision_data = serialize_decision_with_content_info(decision)

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
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_decision_types")
def explore_decision_types_api_dev(request):
    """Get available decision types for temporal exploration"""
    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    try:
        # Get all decisions with date-range filter applied via custom queryset
        decisions_qs = Decision.objects.filter_by_date_range(start_dt, end_dt)

        # Get decision types with counts and financial data
        decision_types = (
            decisions_qs.values("decision_type__uid", "decision_type__label")
            .annotate(
                count=models.Count("id", distinct=True),
                total_amount=models.Sum(
                    "amount_fields__amount",
                    filter=models.Q(
                        amount_fields__associated_relationship__isnull=False
                    ),
                ),
                # Use legacy amount for max as approximation since max of sum is hard
                max_amount=models.Max("amount"),
            )
            .filter(decision_type__uid__isnull=False)  # Exclude decisions without types
            .order_by("-count")
        )

        # Format response
        formatted_types = []
        for dt in decision_types:
            count = dt["count"]
            total = float(dt["total_amount"] or 0)
            formatted_types.append(
                {
                    "uid": dt["decision_type__uid"],
                    "label": dt["decision_type__label"],
                    "count": count,
                    "total_amount": total,
                    "avg_amount": total / count if count > 0 else 0,
                    "max_amount": float(dt["max_amount"] or 0),
                }
            )

        return Response(
            {"decision_types": formatted_types, "total_types": len(formatted_types)}
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
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of organizations to return",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@cached_view(
    cache_prefix="explore_orgs",
    cache_params=["start_date", "end_date", "limit"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_organizations")
def explore_organizations_api_dev(request):
    """Get organizations with decision activity for temporal exploration"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 50))

    try:
        from core.services.analytics_precalc_service import compute_explore_orgs

        return Response(compute_explore_orgs(start_date_str, end_date_str, limit))

    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
