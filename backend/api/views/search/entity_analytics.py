import traceback
from datetime import datetime, timedelta

from core.models.organizations import Organization, Signer, Unit
from core.services.feature_flag_service import feature_flags
from core.services.financial_calculation_service import financial_service
from core.services.search_analytics_service import SearchAnalyticsService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.core.paginator import Paginator
from django.db import models
from django.db.models.functions import (
    TruncDay,
    TruncMonth,
    TruncQuarter,
    TruncWeek,
    TruncYear,
)
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .base import (
    calculate_financial_summary,
    get_entity_decisions_queryset,
    get_entity_info,
    serialize_decision_with_content_info,
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
@monitor_query_performance(include_context=True)
def entity_statistics_api_dev(request, entity_type, entity_id):
    """Get statistics for a specific entity using the enhanced financial service."""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    # Default to last 12 months if no dates provided
    if not end_date_str:
        end_date = timezone.now()
    else:
        try:
            # Parse date and make it timezone-aware
            end_date_parsed = parse_date(end_date_str)
            if not end_date_parsed:
                raise ValueError("Invalid date format")
            end_date = timezone.make_aware(
                datetime.combine(end_date_parsed, datetime.max.time())
            )
        except (ValueError, TypeError) as e:
            return Response({"error": f"Invalid end_date format: {e}"}, status=400)

    if not start_date_str:
        start_date = end_date - timedelta(days=365)
    else:
        try:
            # Parse date and make it timezone-aware
            start_date_parsed = parse_date(start_date_str)
            if not start_date_parsed:
                raise ValueError("Invalid date format")
            start_date = timezone.make_aware(
                datetime.combine(start_date_parsed, datetime.min.time())
            )
        except (ValueError, TypeError) as e:
            return Response({"error": f"Invalid start_date format: {e}"}, status=400)

    try:
        # Get entity info
        entity_info = get_entity_info(entity_type, entity_id)

        # Special handling for AFM entities using financial service
        if entity_type == "afm":
            from core.models.entities import AFMEntity

            try:
                afm_entity = AFMEntity.objects.get(afm=entity_id)

                # Use financial service for comprehensive statistics
                financial_summary = financial_service.get_entity_financial_summary(
                    afm_entity, start_date=start_date, end_date=end_date
                )

                # Get timeline data for charts
                timeline_data = financial_service.get_entity_timeline_data(
                    afm_entity,
                    start_date=start_date,
                    end_date=end_date,
                    granularity="month",
                )

                return Response(
                    {
                        "entity": entity_info,
                        "date_range": {
                            "start_date": start_date.isoformat(),
                            "end_date": end_date.isoformat(),
                        },
                        "statistics": {
                            "total_decisions": financial_summary["decision_count"],
                            "total_amount": float(financial_summary["total_received"]),
                            "avg_amount": float(financial_summary["avg_amount"]),
                            "unique_organizations": financial_summary[
                                "unique_organizations"
                            ],
                            "unique_roles": len(financial_summary["role_breakdown"]),
                        },
                        "financial_summary": financial_summary,
                        "timeline_data": timeline_data,
                        "data_source": "financial_service",
                    }
                )

            except AFMEntity.DoesNotExist:
                # Fall back to legacy approach if AFM entity doesn't exist
                pass

        # Legacy approach for non-AFM entities or fallback
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Apply date filters
        filtered_qs = decisions_qs.filter(
            issue_date__gte=start_date, issue_date__lte=end_date
        )

        # Calculate basic statistics using legacy approach
        stats = filtered_qs.aggregate(
            total_decisions=models.Count("id"),
            avg_amount=models.Avg("amount"),
            max_amount=models.Max("amount"),
            min_amount=models.Min("amount"),
            total_amount=models.Sum("amount"),
        )

        # Calculate financial summary using enhanced base function
        financial_summary = calculate_financial_summary(
            filtered_qs, entity_id, entity_type
        )

        # Monthly breakdown for charts
        try:
            monthly_stats = (
                filtered_qs.annotate(month=TruncMonth("issue_date"))
                .values("month")
                .annotate(count=models.Count("id"), amount=models.Sum("amount"))
                .order_by("month")
            )
        except Exception:
            monthly_stats = []
            monthly_stats = []

        # Top decision types
        top_types = (
            filtered_qs.values("decision_type__label")
            .annotate(count=models.Count("id"), total_amount=models.Sum("amount"))
            .order_by("-count")[:10]
        )

        # Status breakdown
        status_breakdown = (
            filtered_qs.values("status")
            .annotate(count=models.Count("id"))
            .order_by("-count")
        )

        # Recent decisions
        recent_decisions = filtered_qs.order_by("-issue_date")[:5].values(
            "ada", "subject", "issue_date", "amount", "decision_type__label"
        )

        return Response(
            {
                "entity": entity_info,
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
                    "financial": financial_summary,
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
                },
                "recent_decisions": [
                    {
                        "ada": item["ada"],
                        "subject": item["subject"],
                        "issue_date": (
                            item["issue_date"].isoformat()
                            if item["issue_date"]
                            else None
                        ),
                        "amount": float(item["amount"]) if item["amount"] else None,
                        "decision_type": item["decision_type__label"],
                    }
                    for item in recent_decisions
                ],
            }
        )

    except (Organization.DoesNotExist, Signer.DoesNotExist, Unit.DoesNotExist):
        return Response({"error": "Entity not found"}, status=404)
    except Exception as e:
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
        # Add decision type filtering
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
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def entity_decisions_api_dev(request, entity_type, entity_id):
    """Get paginated decisions for a specific entity"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 20))
    search_query = request.GET.get("q", "")
    status_filter = request.GET.get("status", "")
    sort_by = request.GET.get("sort_by", "recent")

    # New filters
    decision_types_str = request.GET.get("decision_types", "")
    min_amount_str = request.GET.get("min_amount", "")
    max_amount_str = request.GET.get("max_amount", "")

    # Parse decision types
    decision_type_uids = []
    if decision_types_str:
        decision_type_uids = [
            t.strip() for t in decision_types_str.split(",") if t.strip()
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

    # Start search analytics tracking
    search_tracking = None
    if search_query:
        search_tracking = SearchAnalyticsService.log_search_start(
            query=search_query,
            search_types=["metadata", "content"],
            entity_type=entity_type,
            entity_id=entity_id,
            request=request,
            filters_applied={
                "start_date": start_date_str,
                "end_date": end_date_str,
                "status": status_filter,
                "sort_by": sort_by,
                "decision_types": decision_types_str,
                "min_amount": min_amount_str,
                "max_amount": max_amount_str,
            },
        )

    try:
        # Get decisions queryset
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Apply date filters if provided with timezone awareness
        if start_date_str:
            start_date_parsed = parse_date(start_date_str)
            if start_date_parsed:
                start_date = timezone.make_aware(
                    datetime.combine(start_date_parsed, datetime.min.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__gte=start_date)

        if end_date_str:
            end_date_parsed = parse_date(end_date_str)
            if end_date_parsed:
                end_date = timezone.make_aware(
                    datetime.combine(end_date_parsed, datetime.max.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__lte=end_date)

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

        # Apply amount filters
        if min_amount is not None:
            decisions_qs = decisions_qs.filter(amount__gte=min_amount)

        if max_amount is not None:
            decisions_qs = decisions_qs.filter(amount__lte=max_amount)

        # Apply sorting
        if sort_by == "amount_desc":
            decisions_qs = decisions_qs.annotate(
                amount_for_sorting=models.Case(
                    models.When(amount__isnull=True, then=models.Value(-999999999)),
                    models.When(amount=0, then=models.Value(-999999998)),
                    default=models.F("amount"),
                    output_field=models.DecimalField(),
                )
            ).order_by("-amount_for_sorting", "-issue_date")

        elif sort_by == "amount_asc":
            decisions_qs = decisions_qs.annotate(
                amount_for_sorting=models.Case(
                    models.When(amount__isnull=True, then=models.Value(999999999)),
                    models.When(amount=0, then=models.Value(999999998)),
                    default=models.F("amount"),
                    output_field=models.DecimalField(),
                )
            ).order_by("amount_for_sorting", "-issue_date")

        else:  # recent (default)
            decisions_qs = decisions_qs.order_by("-issue_date")

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
            "granularity",
            openapi.IN_QUERY,
            description="Timeline granularity: day, week, month, quarter, year",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def entity_timeline_api_dev(request, entity_type, entity_id):
    """Get timeline data for a specific entity"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    granularity = request.GET.get(
        "granularity", "month"
    )  # day, week, month, quarter, year

    # Default to last 12 months if no dates provided
    if not end_date_str:
        end_date = timezone.now()
    else:
        try:
            end_date_parsed = parse_date(end_date_str)
            if not end_date_parsed:
                raise ValueError("Invalid date format")
            end_date = timezone.make_aware(
                datetime.combine(end_date_parsed, datetime.max.time())
            )
        except (ValueError, TypeError) as e:
            return Response({"error": f"Invalid end_date format: {e}"}, status=400)

    if not start_date_str:
        start_date = end_date - timedelta(days=365)
    else:
        try:
            start_date_parsed = parse_date(start_date_str)
            if not start_date_parsed:
                raise ValueError("Invalid date format")
            start_date = timezone.make_aware(
                datetime.combine(start_date_parsed, datetime.min.time())
            )
        except (ValueError, TypeError) as e:
            return Response({"error": f"Invalid start_date format: {e}"}, status=400)

    try:
        # Get decisions queryset for the entity
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Apply date filters
        decisions_qs = decisions_qs.filter(
            issue_date__gte=start_date, issue_date__lte=end_date
        )

        # Choose appropriate truncation function based on granularity
        if granularity == "day":
            trunc_func = TruncDay
        elif granularity == "week":
            trunc_func = TruncWeek
        elif granularity == "month":
            trunc_func = TruncMonth
        elif granularity == "quarter":
            trunc_func = TruncQuarter
        elif granularity == "year":
            trunc_func = TruncYear
        else:
            return Response(
                {"error": f"Invalid granularity: {granularity}"}, status=400
            )

        # Get timeline data
        timeline_data = (
            decisions_qs.annotate(period=trunc_func("issue_date"))
            .values("period")
            .annotate(
                count=models.Count("id"),
                total_amount=models.Sum("amount"),
                avg_amount=models.Avg("amount"),
            )
            .order_by("period")
        )

        # Format results
        formatted_timeline = []
        for item in timeline_data:
            formatted_timeline.append(
                {
                    "period": item["period"].isoformat() if item["period"] else None,
                    "count": item["count"],
                    "total_amount": float(item["total_amount"] or 0),
                    "avg_amount": float(item["avg_amount"] or 0),
                }
            )

        return Response(
            {
                "entity": {"type": entity_type, "id": entity_id},
                "timeline": formatted_timeline,
                "period": {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "granularity": granularity,
                },
                "summary": {
                    "total_periods": len(formatted_timeline),
                    "total_decisions": sum(
                        item["count"] for item in formatted_timeline
                    ),
                    "total_amount": sum(
                        item["total_amount"] for item in formatted_timeline
                    ),
                },
            }
        )

    except (Organization.DoesNotExist, Signer.DoesNotExist, Unit.DoesNotExist):
        return Response({"error": "Entity not found"}, status=404)
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
def entity_decision_types_api_dev(request, entity_type, entity_id):
    """Get available decision types for a specific entity"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    try:
        # Get decisions queryset
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Apply date filters if provided
        if start_date_str:
            start_date_parsed = parse_date(start_date_str)
            if start_date_parsed:
                start_date = timezone.make_aware(
                    datetime.combine(start_date_parsed, datetime.min.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__gte=start_date)

        if end_date_str:
            end_date_parsed = parse_date(end_date_str)
            if end_date_parsed:
                end_date = timezone.make_aware(
                    datetime.combine(end_date_parsed, datetime.max.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__lte=end_date)

        # Get decision types with counts and financial data
        decision_types = (
            decisions_qs.values("decision_type__uid", "decision_type__label")
            .annotate(
                count=models.Count("id"),
                total_amount=models.Sum("amount"),
                avg_amount=models.Avg("amount"),
                max_amount=models.Max("amount"),
            )
            .filter(decision_type__uid__isnull=False)  # Exclude decisions without types
            .order_by("-count")
        )

        # Format response
        formatted_types = []
        for dt in decision_types:
            formatted_types.append(
                {
                    "uid": dt["decision_type__uid"],
                    "label": dt["decision_type__label"],
                    "count": dt["count"],
                    "total_amount": float(dt["total_amount"] or 0),
                    "avg_amount": float(dt["avg_amount"] or 0),
                    "max_amount": float(dt["max_amount"] or 0),
                }
            )

        return Response(
            {
                "entity": {"type": entity_type, "id": entity_id},
                "decision_types": formatted_types,
                "total_types": len(formatted_types),
            }
        )

    except (Organization.DoesNotExist, Signer.DoesNotExist, Unit.DoesNotExist):
        return Response({"error": "Entity not found"}, status=404)
    except Exception as e:
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
def entity_date_range_api_dev(request, entity_type, entity_id):
    """Get the available date range and activity overview for an entity"""
    try:
        # Get decisions queryset for the entity
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Get date range
        date_stats = decisions_qs.aggregate(
            earliest_date=models.Min("issue_date"),
            latest_date=models.Max("issue_date"),
            total_decisions=models.Count("id"),
            total_amount=models.Sum("amount"),
        )

        if not date_stats["earliest_date"]:
            return Response(
                {
                    "entity": {"type": entity_type, "id": entity_id},
                    "has_data": False,
                    "message": "No decisions found for this entity. Contact the administrator if you expect data to be available.",
                    "date_range": None,
                    "activity_chart": [],
                }
            )

        # Calculate optimal granularity based on data span
        earliest = date_stats["earliest_date"]
        latest = date_stats["latest_date"]
        span_days = (latest - earliest).days

        # Choose granularity based on data span
        if span_days <= 31:  # Less than a month - daily
            granularity = "day"
            trunc_func = TruncDay
        elif span_days <= 365:  # Less than a year - weekly
            granularity = "week"
            trunc_func = TruncWeek
        elif span_days <= 1825:  # Less than 5 years - monthly
            granularity = "month"
            trunc_func = TruncMonth
        else:  # More than 5 years - quarterly
            granularity = "quarter"
            trunc_func = TruncQuarter

        # Get activity data for mini chart
        activity_data = (
            decisions_qs.annotate(period=trunc_func("issue_date"))
            .values("period")
            .annotate(count=models.Count("id"), total_amount=models.Sum("amount"))
            .order_by("period")
        )

        # Format activity chart data
        chart_data = []
        for item in activity_data:
            chart_data.append(
                {
                    "period": item["period"].isoformat() if item["period"] else None,
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
                "entity": {"type": entity_type, "id": entity_id},
                "has_data": True,
                "date_range": {
                    "earliest": earliest.date().isoformat(),
                    "latest": latest.date().isoformat(),
                    "span_days": span_days,
                    "recommended_granularity": granularity,
                },
                "summary": {
                    "total_decisions": date_stats["total_decisions"],
                    "total_amount": float(date_stats["total_amount"] or 0),
                    "avg_daily_decisions": round(
                        date_stats["total_decisions"] / max(span_days, 1), 2
                    ),
                    "avg_daily_amount": round(
                        float(date_stats["total_amount"] or 0) / max(span_days, 1), 2
                    ),
                },
                "activity_chart": {
                    "data": chart_data,
                    "granularity": granularity,
                    "stats": chart_stats,
                },
            }
        )

    except (Organization.DoesNotExist, Signer.DoesNotExist, Unit.DoesNotExist):
        return Response({"error": "Entity not found"}, status=404)
    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
