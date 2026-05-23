"""
Direct Assignment Analytics Views

Analytical endpoints for exploring direct assignment patterns and financial flows.
These views focus on WHO receives money through direct assignments and HOW MUCH,
following the same pattern as organization_entity_relationships views.

Key use cases:
- Top entities receiving direct assignment money (by org or globally)
- Top organizations giving out direct assignments (by entity or globally)
- Temporal exploration of direct assignment patterns
- Monitoring and statistics
"""

import traceback

from core.decorators.cache_decorator import cached_view
from core.models.decision_classification import DecisionClassification
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.models.organizations import Organization
from core.services.financial_calculation_service import financial_service
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.db.models import Avg, Count, Max, Min, Sum
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


def _parse_and_validate_date_range(request, context_label: str = None):
    """
    Parse and validate start_date and end_date from request query parameters.

    Returns:
        Tuple of (start_date, end_date, error_response)
        Returns timezone-aware datetime objects for proper comparison with DateTimeFields.
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    if not start_date_str or not end_date_str:
        return (
            None,
            None,
            Response({"error": "start_date and end_date are required"}, status=400),
        )

    try:
        start_datetime = parse_datetime(start_date_str)
        end_datetime = parse_datetime(end_date_str)

        if start_datetime is None or end_datetime is None:
            return (
                None,
                None,
                Response(
                    {
                        "error": "Invalid date format. Expected ISO 8601 format (e.g., '2025-12-22T16:27:17.386689Z')"
                    },
                    status=400,
                ),
            )

        # Make timezone-aware if naive (Django USE_TZ = True requires this)
        if timezone.is_naive(start_datetime):
            start_datetime = timezone.make_aware(start_datetime)
        if timezone.is_naive(end_datetime):
            end_datetime = timezone.make_aware(end_datetime)

    except (ValueError, AttributeError) as e:
        return (
            None,
            None,
            Response({"error": f"Invalid date format: {str(e)}"}, status=400),
        )

    if start_datetime > end_datetime:
        return (
            None,
            None,
            Response(
                {"error": "start_date must be before or equal to end_date"}, status=400
            ),
        )

    if (end_datetime - start_datetime).days > 365:
        context_info = f" for {context_label}" if context_label else ""
        logger.warning(
            f"Large date range requested{context_info}: "
            f"{start_datetime} to {end_datetime} ({(end_datetime - start_datetime).days} days)"
        )

    return start_datetime, end_datetime, None


@swagger_auto_schema(
    method="get",
    operation_description="Get top entities receiving direct assignment money from a specific organization",
    manual_parameters=[
        openapi.Parameter(
            "organization_uid",
            openapi.IN_PATH,
            description="Organization UID",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
            default=10,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
            default=0,
        ),
    ],
    responses={
        200: openapi.Response(
            description="Top entities receiving direct assignment money",
            examples={
                "application/json": {
                    "organization": {"uid": "99221811", "label": "ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ"},
                    "date_range": {
                        "start": "2025-01-01T00:00:00Z",
                        "end": "2025-12-31T23:59:59Z",
                    },
                    "results": [
                        {
                            "entity_afm": "123456789",
                            "entity_name": "ΕΤΑΙΡΕΙΑ ΑΕ",
                            "entity_type": "COMPANY",
                            "total_amount": "125000.50",
                            "decision_count": 15,
                            "avg_amount": "8333.37",
                            "max_amount": "35000.00",
                            "min_amount": "500.00",
                        }
                    ],
                    "pagination": {
                        "limit": 10,
                        "offset": 0,
                        "total_count": 45,
                        "has_more": True,
                    },
                    "summary": {
                        "total_direct_assignment_amount": "1250000.00",
                        "total_direct_assignments": 150,
                        "unique_entities": 45,
                    },
                }
            },
        )
    },
)
@cached_view(
    cache_prefix="da_org_recipients",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="direct_assignments_top_recipients_by_org")
def organization_direct_assignment_top_recipients(request, organization_uid):
    """
    Get top entities receiving direct assignment money from an organization.

    Shows which vendors/companies receive the most money via direct assignments
    (below €37,200 threshold) from a specific organization.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label=f"organization {organization_uid} direct assignments"
    )
    if error_response:
        return error_response

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 10))
    offset = int(request.GET.get("offset", 0))

    # Try cache first
    cache_key = response_cache.build_key(
        "org_top_recipients",
        uid=organization_uid,
        start=start_date_str,
        end=end_date_str,
        limit=limit,
        offset=offset,
    )
    cached_response = response_cache.get(cache_key)
    if cached_response is not None:
        return Response(cached_response)

    try:
        try:
            organization = Organization.objects.get(uid=organization_uid)
        except Organization.DoesNotExist:
            return Response(
                {"error": f"Organization with UID '{organization_uid}' not found"},
                status=404,
            )

        # Query direct assignments for this organization
        # Using the MONEY_RECEIVED_ROLES from financial_service
        roles = financial_service.MONEY_RECEIVED_ROLES

        # Base filter — reused across all queries to avoid repeating 5 filter conditions
        base_filter = dict(
            decision__organization=organization,
            decision__issue_date__gte=start_date,
            decision__issue_date__lte=end_date,
            decision__classification__is_direct_assignment=True,
            role__in=roles,
        )

        # Get top entities receiving direct assignment money
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values("entity__afm", "entity__name", "entity__entity_type")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
                avg_amount=Avg("linked_amounts__amount"),
                max_amount=Max("linked_amounts__amount"),
                min_amount=Min("linked_amounts__amount"),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Combine total_count + summary_stats into a single query
        # (previously these were 2 separate queries with the same filter)
        combined_stats = DecisionEntityRelationship.objects.filter(
            **base_filter
        ).aggregate(
            # For pagination
            unique_entities=Count("entity", distinct=True),
            # For summary
            total_amount=Sum("linked_amounts__amount"),
            total_decisions=Count("decision", distinct=True),
        )
        total_count = combined_stats["unique_entities"] or 0

        # Format results
        formatted_results = [
            {
                "entity_afm": r["entity__afm"],
                "entity_name": r["entity__name"],
                "entity_type": r["entity__entity_type"],
                "total_amount": str(r["total_amount"]) if r["total_amount"] else "0",
                "decision_count": r["decision_count"],
                "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
                "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
                "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
            }
            for r in results
        ]

        response_data = {
            "organization": {
                "uid": organization.uid,
                "label": organization.label,
            },
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
            },
            "results": formatted_results,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            },
            "summary": {
                "total_direct_assignment_amount": str(
                    combined_stats["total_amount"] or 0
                ),
                "total_direct_assignments": combined_stats["total_decisions"] or 0,
                "unique_entities": combined_stats["unique_entities"] or 0,
            },
        }

        # Cache the response
        response_cache.set(cache_key, response_data, end_date=end_date)

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in organization_direct_assignment_top_recipients: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get top organizations giving direct assignment money to a specific entity",
    manual_parameters=[
        openapi.Parameter(
            "afm",
            openapi.IN_PATH,
            description="Entity AFM",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
            default=10,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
            default=0,
        ),
    ],
)
@cached_view(
    cache_prefix="da_entity_orgs",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="direct_assignments_top_organizations_by_entity")
def entity_direct_assignment_top_organizations(request, afm):
    """
    Get top organizations giving direct assignment money to an entity.

    Shows which organizations gave the most money via direct assignments
    to a specific vendor/company.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label=f"entity {afm} direct assignments"
    )
    if error_response:
        return error_response

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 10))
    offset = int(request.GET.get("offset", 0))

    # Try cache first
    cache_key = response_cache.build_key(
        "entity_top_orgs",
        afm=afm,
        start=start_date_str,
        end=end_date_str,
        limit=limit,
        offset=offset,
    )
    cached_response = response_cache.get(cache_key)
    if cached_response is not None:
        return Response(cached_response)

    try:
        try:
            entity = AFMEntity.objects.get(afm=afm)
        except AFMEntity.DoesNotExist:
            return Response({"error": f"Entity with AFM '{afm}' not found"}, status=404)

        roles = financial_service.MONEY_RECEIVED_ROLES

        # Base filter — reused across all queries
        base_filter = dict(
            entity=entity,
            decision__issue_date__gte=start_date,
            decision__issue_date__lte=end_date,
            decision__classification__is_direct_assignment=True,
            role__in=roles,
        )

        # Get top organizations for this entity's direct assignments
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values("decision__organization__uid", "decision__organization__label")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
                avg_amount=Avg("linked_amounts__amount"),
                max_amount=Max("linked_amounts__amount"),
                min_amount=Min("linked_amounts__amount"),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Combine total_count + summary_stats into a single query
        combined_stats = DecisionEntityRelationship.objects.filter(
            **base_filter
        ).aggregate(
            unique_organizations=Count("decision__organization", distinct=True),
            total_amount=Sum("linked_amounts__amount"),
            total_decisions=Count("decision", distinct=True),
        )
        total_count = combined_stats["unique_organizations"] or 0

        # Format results
        formatted_results = [
            {
                "organization_uid": r["decision__organization__uid"],
                "organization_label": r["decision__organization__label"],
                "total_amount": str(r["total_amount"]) if r["total_amount"] else "0",
                "decision_count": r["decision_count"],
                "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
                "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
                "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
            }
            for r in results
        ]

        response_data = {
            "entity": {
                "afm": entity.afm,
                "name": entity.name,
                "entity_type": entity.entity_type,
            },
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
            },
            "results": formatted_results,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            },
            "summary": {
                "total_direct_assignment_amount": str(
                    combined_stats["total_amount"] or 0
                ),
                "total_direct_assignments": combined_stats["total_decisions"] or 0,
                "unique_organizations": combined_stats["unique_organizations"] or 0,
            },
        }

        # Cache the response
        response_cache.set(cache_key, response_data, end_date=end_date)

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in entity_direct_assignment_top_organizations: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get top organization-entity pairs for direct assignments globally",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
            default=20,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
            default=0,
        ),
    ],
)
@cached_view(
    cache_prefix="da_top_pairs",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="direct_assignments_top_pairs_global")
def direct_assignment_top_pairs_global(request):
    """
    Get top organization-entity pairs for direct assignments across all data.

    TEMPORAL EXPLORATION endpoint - shows the biggest direct assignment
    financial flows between any organization and any entity in a date range.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label="global direct assignments"
    )
    if error_response:
        return error_response

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 20))
    offset = int(request.GET.get("offset", 0))

    try:
        roles = financial_service.MONEY_RECEIVED_ROLES

        # Base filter — reused across all queries
        base_filter = dict(
            decision__issue_date__gte=start_date,
            decision__issue_date__lte=end_date,
            decision__classification__is_direct_assignment=True,
            role__in=roles,
        )

        # Get top org-entity pairs for direct assignments
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values(
                "decision__organization__uid",
                "decision__organization__label",
                "entity__afm",
                "entity__name",
                "entity__entity_type",
            )
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
                avg_amount=Avg("linked_amounts__amount"),
                max_amount=Max("linked_amounts__amount"),
                min_amount=Min("linked_amounts__amount"),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Combine total_count + summary_stats into a single query
        combined_stats = DecisionEntityRelationship.objects.filter(
            **base_filter
        ).aggregate(
            unique_org_entity_pairs=Count("id", distinct=True),
            total_amount=Sum("linked_amounts__amount"),
            total_decisions=Count("decision", distinct=True),
            unique_organizations=Count("decision__organization", distinct=True),
            unique_entities=Count("entity", distinct=True),
        )
        total_count = combined_stats["unique_org_entity_pairs"] or 0

        # Format results
        formatted_results = [
            {
                "organization": {
                    "uid": r["decision__organization__uid"],
                    "label": r["decision__organization__label"],
                },
                "entity": {
                    "afm": r["entity__afm"],
                    "name": r["entity__name"],
                    "entity_type": r["entity__entity_type"],
                },
                "total_amount": str(r["total_amount"]) if r["total_amount"] else "0",
                "decision_count": r["decision_count"],
                "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
                "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
                "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
            }
            for r in results
        ]

        response_data = {
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
            },
            "results": formatted_results,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            },
            "summary": {
                "total_direct_assignment_amount": str(
                    combined_stats["total_amount"] or 0
                ),
                "total_direct_assignments": combined_stats["total_decisions"] or 0,
                "unique_organizations": combined_stats["unique_organizations"] or 0,
                "unique_entities": combined_stats["unique_entities"] or 0,
            },
        }

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in direct_assignment_top_pairs_global: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get top entities (vendors) receiving direct assignment money globally",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
            default=20,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
            default=0,
        ),
        openapi.Parameter(
            "sort_by",
            openapi.IN_QUERY,
            description="Sort by: 'amount' (default) or 'frequency'",
            type=openapi.TYPE_STRING,
            enum=["amount", "frequency"],
            default="amount",
        ),
    ],
)
@cached_view(
    cache_prefix="da_top_entities",
    cache_params=["start_date", "end_date", "limit", "offset", "sort_by"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="direct_assignments_top_entities_global")
def direct_assignment_top_entities_global(request):
    """
    Get top entities (vendors/companies) receiving direct assignment money globally.

    LEADERBOARD endpoint - shows which entities receive the most across ALL organizations.
    Can sort by total amount (champion by €) or by frequency (champion by # of contracts).
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label="global entity champions"
    )
    if error_response:
        return error_response

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 20))
    offset = int(request.GET.get("offset", 0))
    sort_by = request.GET.get("sort_by", "amount")

    # Try cache first
    cache_key = response_cache.build_key(
        "top_entities",
        start=start_date_str,
        end=end_date_str,
        limit=limit,
        offset=offset,
        sort=sort_by,
    )
    cached_response = response_cache.get(cache_key)
    if cached_response is not None:
        return Response(cached_response)

    try:
        roles = financial_service.MONEY_RECEIVED_ROLES

        # Base filter — reused across all queries
        base_filter = dict(
            decision__issue_date__gte=start_date,
            decision__issue_date__lte=end_date,
            decision__classification__is_direct_assignment=True,
            role__in=roles,
        )

        # Determine sort order
        if sort_by == "frequency":
            order_by = "-decision_count"
            metric_label = "Most Direct Assignments Received"
        else:  # amount
            order_by = "-total_amount"
            metric_label = "Highest Direct Assignment Revenue"

        # Get top entities globally
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values("entity__afm", "entity__name", "entity__entity_type")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
                avg_amount=Avg("linked_amounts__amount"),
                max_amount=Max("linked_amounts__amount"),
                min_amount=Min("linked_amounts__amount"),
                organization_count=Count("decision__organization", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by(order_by)[offset : offset + limit]
        )

        # Combine total_count + summary_stats into a single query
        combined_stats = DecisionEntityRelationship.objects.filter(
            **base_filter
        ).aggregate(
            unique_entities=Count("entity", distinct=True),
            total_amount=Sum("linked_amounts__amount"),
            total_decisions=Count("decision", distinct=True),
            unique_organizations=Count("decision__organization", distinct=True),
        )
        total_count = combined_stats["unique_entities"] or 0

        # Format results
        formatted_results = [
            {
                "rank": offset + i + 1,
                "entity_afm": r["entity__afm"],
                "entity_name": r["entity__name"],
                "entity_type": r["entity__entity_type"],
                "total_amount": str(r["total_amount"]) if r["total_amount"] else "0",
                "decision_count": r["decision_count"],
                "organization_count": r["organization_count"],
                "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
                "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
                "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
            }
            for i, r in enumerate(results)
        ]

        response_data = {
            "metric": metric_label,
            "sort_by": sort_by,
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
            },
            "results": formatted_results,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            },
            "summary": {
                "total_direct_assignment_amount": str(
                    combined_stats["total_amount"] or 0
                ),
                "total_direct_assignments": combined_stats["total_decisions"] or 0,
                "unique_entities": combined_stats["unique_entities"] or 0,
                "unique_organizations": combined_stats["unique_organizations"] or 0,
            },
        }

        # Cache the response
        response_cache.set(cache_key, response_data, end_date=end_date)

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in direct_assignment_top_entities_global: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get top organizations giving out direct assignment money globally",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
            default=20,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
            default=0,
        ),
        openapi.Parameter(
            "sort_by",
            openapi.IN_QUERY,
            description="Sort by: 'amount' (default) or 'frequency'",
            type=openapi.TYPE_STRING,
            enum=["amount", "frequency"],
            default="amount",
        ),
    ],
)
@cached_view(
    cache_prefix="da_top_orgs",
    cache_params=["start_date", "end_date", "limit", "offset", "sort_by"],
    end_date_param="end_date",
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="direct_assignments_top_organizations_global")
def direct_assignment_top_organizations_global(request):
    """
    Get top organizations giving out direct assignment money globally.

    LEADERBOARD endpoint - shows which organizations spend the most on direct assignments.
    Can sort by total amount (biggest spender) or by frequency (most contracts issued).
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label="global organization champions"
    )
    if error_response:
        return error_response

    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 20))
    offset = int(request.GET.get("offset", 0))
    sort_by = request.GET.get("sort_by", "amount")

    # Try cache first
    cache_key = response_cache.build_key(
        "top_orgs",
        start=start_date_str,
        end=end_date_str,
        limit=limit,
        offset=offset,
        sort=sort_by,
    )
    cached_response = response_cache.get(cache_key)
    if cached_response is not None:
        return Response(cached_response)

    try:
        roles = financial_service.MONEY_RECEIVED_ROLES

        # Base filter — reused across all queries
        base_filter = dict(
            decision__issue_date__gte=start_date,
            decision__issue_date__lte=end_date,
            decision__classification__is_direct_assignment=True,
            role__in=roles,
        )

        # Determine sort order
        if sort_by == "frequency":
            order_by = "-decision_count"
            metric_label = "Most Direct Assignments Issued"
        else:  # amount
            order_by = "-total_amount"
            metric_label = "Highest Direct Assignment Spending"

        # Get top organizations globally
        results = list(
            DecisionEntityRelationship.objects.filter(**base_filter)
            .values("decision__organization__uid", "decision__organization__label")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
                avg_amount=Avg("linked_amounts__amount"),
                max_amount=Max("linked_amounts__amount"),
                min_amount=Min("linked_amounts__amount"),
                entity_count=Count("entity", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by(order_by)[offset : offset + limit]
        )

        # Combine total_count + summary_stats into a single query
        combined_stats = DecisionEntityRelationship.objects.filter(
            **base_filter
        ).aggregate(
            unique_organizations=Count("decision__organization", distinct=True),
            total_amount=Sum("linked_amounts__amount"),
            total_decisions=Count("decision", distinct=True),
            unique_entities=Count("entity", distinct=True),
        )
        total_count = combined_stats["unique_organizations"] or 0

        # Format results
        formatted_results = [
            {
                "rank": offset + i + 1,
                "organization_uid": r["decision__organization__uid"],
                "organization_label": r["decision__organization__label"],
                "total_amount": str(r["total_amount"]) if r["total_amount"] else "0",
                "decision_count": r["decision_count"],
                "entity_count": r["entity_count"],
                "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
                "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
                "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
            }
            for i, r in enumerate(results)
        ]

        response_data = {
            "metric": metric_label,
            "sort_by": sort_by,
            "date_range": {
                "start": start_date_str,
                "end": end_date_str,
            },
            "results": formatted_results,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "total_count": total_count,
                "has_more": offset + limit < total_count,
            },
            "summary": {
                "total_direct_assignment_amount": str(
                    combined_stats["total_amount"] or 0
                ),
                "total_direct_assignments": combined_stats["total_decisions"] or 0,
                "unique_organizations": combined_stats["unique_organizations"] or 0,
                "unique_entities": combined_stats["unique_entities"] or 0,
            },
        }

        # Cache the response
        response_cache.set(cache_key, response_data, end_date=end_date)

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in direct_assignment_top_organizations_global: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get overall statistics about direct assignments",
)
@cached_view(
    cache_prefix="da_stats",
    cache_params=None,  # No params - cache all requests the same
    ttl=60 * 10,  # 10 minutes fixed TTL for stats
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def direct_assignment_stats(request):
    """
    Get overall statistics about direct assignment classifications.

    Provides high-level metrics for monitoring and dashboards.
    """
    # Try cache first (stats change infrequently)
    cache_key = response_cache.build_key("stats")
    cached_response = response_cache.get(cache_key)
    if cached_response is not None:
        return Response(cached_response)

    try:
        from django.db.models import Count, Q

        # Get classification counts
        total_decisions = DecisionClassification.objects.count()

        classification_stats = DecisionClassification.objects.aggregate(
            direct_assignments=Count("decision", filter=Q(is_direct_assignment=True)),
            non_direct_assignments=Count(
                "decision", filter=Q(is_direct_assignment=False)
            ),
            total_classified=Count("decision"),
        )

        direct_assignments = classification_stats["direct_assignments"] or 0
        non_direct_assignments = classification_stats["non_direct_assignments"] or 0
        classified_decisions = classification_stats["total_classified"] or 0

        classification_rate = (
            (classified_decisions / total_decisions * 100) if total_decisions > 0 else 0
        )

        # Get entity relationship stats
        direct_with_entities = (
            DecisionClassification.objects.filter(
                is_direct_assignment=True, decision__entity_relationships__isnull=False
            )
            .distinct()
            .count()
        )

        entity_linking_rate = (
            (direct_with_entities / direct_assignments * 100)
            if direct_assignments > 0
            else 0
        )

        response_data = {
            "total_decisions": total_decisions,
            "classified_decisions": classified_decisions,
            "direct_assignments": direct_assignments,
            "non_direct_assignments": non_direct_assignments,
            "classification_rate": round(classification_rate, 2),
            "direct_assignments_with_entities": direct_with_entities,
            "entity_linking_rate": round(entity_linking_rate, 2),
            "threshold_eur": "37200.00",
            "decision_type": "Δ.1",
        }

        # Cache stats for 10 minutes (they change slowly)
        response_cache.set(
            cache_key, response_data, timeout=response_cache.EXPIRE_STATS
        )

        return Response(response_data)

    except Exception as e:
        logger.error(f"Error in direct_assignment_stats: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
