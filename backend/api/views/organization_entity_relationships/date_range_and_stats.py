"""
Relationship Date Range & Statistics Views

Provides endpoints for:
- Date range and activity overview for an AFM↔Organization pair
- Filtered statistics for a date range within an AFM↔Organization relationship
"""

from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship
from core.services.financial_calculation_service import FinancialCalculationService
from django.conf import settings
from django.db import models
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
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
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
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

        date_stats = decisions_qs.aggregate(
            earliest_date=models.Min("issue_date_day"),
            latest_date=models.Max("issue_date_day"),
            total_decisions=models.Count("id"),
        )

        if not date_stats["earliest_date"]:
            return Response(
                {
                    "has_data": False,
                    "message": "No decisions found for this entity-organization pair.",
                    "date_range": None,
                    "activity_chart": [],
                }
            )

        earliest = date_stats["earliest_date"]
        latest = date_stats["latest_date"]
        span_days = (latest - earliest).days

        # Choose granularity based on data span
        if span_days <= 31:
            granularity = "day"
            period_column = "issue_date_day"
        elif span_days <= 1825:
            granularity = "month"
            period_column = "issue_date_month"
        else:
            granularity = "year"
            period_column = "issue_date_year"

        # Activity data
        activity_data = (
            decisions_qs.annotate(period=models.F(period_column))
            .values("period")
            .annotate(count=models.Count("id"), total_amount=models.Sum("amount"))
            .order_by("period")
        )

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
                    "earliest": earliest.isoformat(),
                    "latest": latest.isoformat(),
                    "span_days": span_days,
                    "recommended_granularity": granularity,
                },
                "summary": {
                    "total_decisions": date_stats["total_decisions"],
                    "avg_daily_decisions": round(
                        date_stats["total_decisions"] / max(span_days, 1), 2
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
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def relationship_statistics_api(request, afm, orgUid):
    """
    Get server-computed statistics for a specific AFM↔Organization
    relationship filtered by a date range.

    Returns:
        - total_decisions: count of decisions in the window
        - total_amount: sum of all decision amounts
        - avg_amount: average decision amount
        - decisions_with_amounts: count of decisions with non-zero amounts
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    if not start_date_str or not end_date_str:
        return Response(
            {"error": "start_date and end_date are required"}, status=400
        )

    try:
        start_date = parse_date(start_date_str)
        end_date = parse_date(end_date_str)

        if not start_date or not end_date:
            return Response(
                {"error": "Invalid date format. Expected YYYY-MM-DD."}, status=400
            )

        if start_date > end_date:
            return Response(
                {"error": "start_date must be before or equal to end_date"},
                status=400,
            )

        decisions_qs = _get_relationship_decisions_qs(afm, orgUid)

        # Filter by date range
        decisions_qs = decisions_qs.filter(
            issue_date_day__gte=start_date,
            issue_date_day__lte=end_date,
        )

        # Use financial service for accurate calculations
        try:
            financial_service = FinancialCalculationService()
            financial_summary = financial_service.get_global_financial_summary(
                decisions_queryset=decisions_qs
            )
            total_amount = financial_summary.get("total_amount", 0)
        except Exception:
            # Fall back to simple aggregation
            total_amount = float(
                decisions_qs.aggregate(total=models.Sum("amount"))["total"] or 0
            )

        stats = decisions_qs.aggregate(
            total_decisions=models.Count("id"),
            avg_amount=models.Avg("amount"),
            decisions_with_amounts=models.Count(
                "id", filter=models.Q(amount__isnull=False, amount__gt=0)
            ),
        )

        return Response(
            {
                "total_decisions": stats["total_decisions"] or 0,
                "total_amount": float(total_amount),
                "avg_amount": float(stats["avg_amount"] or 0),
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
