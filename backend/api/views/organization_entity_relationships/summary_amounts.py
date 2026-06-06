"""
Organization-Entity Relationship Views

This module provides endpoints for exploring relationships between organizations
and entities (vendors, companies, AFMs). These are NOT search endpoints,
but rather analytical views for understanding financial flows.

Key use cases:
- Top counterparts for an organization by amount
- Organization-entity transaction history
- Financial breakdowns by entity
"""

from core.models.entities import AFMEntity
from core.models.organizations import Organization
from core.services.financial_calculation_service import FinancialCalculationService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
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

    Args:
        request: Django request object
        context_label: Optional label for logging context (e.g., organization UID, entity AFM)

    Returns:
        Tuple of (start_date, end_date, error_response)
        - If successful: (date, date, None)
        - If error: (None, None, Response)
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    # Validate required parameters
    if not start_date_str or not end_date_str:
        return (
            None,
            None,
            Response({"error": "start_date and end_date are required"}, status=400),
        )

    try:
        # Parse datetime strings (ISO 8601 format) and extract date component
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

        start_date = start_datetime.date()
        end_date = end_datetime.date()
    except (ValueError, AttributeError) as e:
        return (
            None,
            None,
            Response({"error": f"Invalid date format: {str(e)}"}, status=400),
        )

    # Validate date range
    if start_date > end_date:
        return (
            None,
            None,
            Response(
                {"error": "start_date must be before or equal to end_date"}, status=400
            ),
        )

    # Warn on large date ranges
    if (end_date - start_date).days > 365:
        context_info = f" for {context_label}" if context_label else ""
        logger.warning(
            f"Large date range requested{context_info}: "
            f"{start_date} to {end_date} ({(end_date - start_date).days} days)"
        )

    return start_date, end_date, None


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "organization_uid",
            openapi.IN_PATH,  # Changed from IN_QUERY to IN_PATH
            description="Organization UID",
            type=openapi.TYPE_STRING,
            required=True,
        ),
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
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="organization_top_counterparts")
def organization_top_counterparts_api(
    request, organization_uid
):  # Added organization_uid parameter
    """
    Get top entities (counterparts) by total amount for an organization in a date range.

    This endpoint is optimized for pagination and will be heavily cached since
    vendor interactions per day are typically low (data is mostly static).

    Use case: Show which vendors/entities received the most money from an organization
    in a given time period, with pagination for exploring all counterparts.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label=f"organization {organization_uid}"
    )
    if error_response:
        return error_response

    # Get pagination parameters
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 5))
    offset = int(request.GET.get("offset", 0))

    try:
        # Get organization
        try:
            organization = Organization.objects.get(uid=organization_uid)
        except Organization.DoesNotExist:
            return Response(
                {"error": f"Organization with UID '{organization_uid}' not found"},
                status=404,
            )

        # Get top counterparts using financial service
        financial_service = FinancialCalculationService()
        result = financial_service.get_top_counterparts_for_organization(
            organization=organization,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
            offset=offset,
        )

        return Response(
            {
                "organization": {
                    "uid": organization.uid,
                    "label": organization.label,
                },
                "date_range": {
                    "start": start_date_str,
                    "end": end_date_str,
                },
                "results": result["results"],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total_count": result["total_count"],
                    "has_more": result["has_more"],
                },
            }
        )

    except Exception as e:
        import traceback

        logger.error(f"Error in organization_top_counterparts_api: {e}")
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
            "afm",
            openapi.IN_PATH,
            description="Entity AFM",
            type=openapi.TYPE_STRING,
            required=True,
        ),
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
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="entity_top_organizations")
def entity_top_organizations_api(request, afm):
    """
    Get top organizations by total amount for an entity in a date range.

    This is the inverse of organization_top_counterparts - instead of finding
    which entities received money from an organization, this finds which
    organizations paid money to a specific entity.

    Use case: Show which organizations paid the most to a specific vendor/entity
    in a given time period, with pagination for exploring all organizations.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label=f"entity {afm}"
    )
    if error_response:
        return error_response

    # Get pagination parameters
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 5))
    offset = int(request.GET.get("offset", 0))

    try:
        # Get entity
        try:
            entity = AFMEntity.objects.get(afm=afm)
        except AFMEntity.DoesNotExist:
            return Response({"error": f"Entity with AFM '{afm}' not found"}, status=404)

        # Get top organizations using financial service
        financial_service = FinancialCalculationService()

        # Use existing method but aggregate by organization instead of entity
        from core.models.entities import DecisionEntityRelationship
        from django.db.models import Count, Sum

        roles = financial_service.MONEY_RECEIVED_ROLES

        # Query top organizations for this entity
        results = list(
            DecisionEntityRelationship.objects.filter(
                entity=entity,
                decision__issue_date_day__gte=start_date,
                decision__issue_date_day__lte=end_date,
                role__in=roles,
            )
            .values("decision__organization__uid", "decision__organization__label")
            .annotate(
                total_amount=Sum("linked_amounts__amount"),
                decision_count=Count("decision", distinct=True),
            )
            .filter(total_amount__gt=0)
            .order_by("-total_amount")[offset : offset + limit]
        )

        # Get total count for pagination
        total_count = (
            DecisionEntityRelationship.objects.filter(
                entity=entity,
                decision__issue_date_day__gte=start_date,
                decision__issue_date_day__lte=end_date,
                role__in=roles,
            )
            .values("decision__organization")
            .distinct()
            .count()
        )

        return Response(
            {
                "entity": {
                    "afm": entity.afm,
                    "name": entity.name,
                    "entity_type": entity.entity_type,
                },
                "date_range": {
                    "start": start_date_str,
                    "end": end_date_str,
                },
                "results": results,
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total_count": total_count,
                    "has_more": offset + limit < total_count,
                },
            }
        )

    except Exception as e:
        import traceback

        logger.error(f"Error in entity_top_organizations_api: {e}")
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
            required=True,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of results to return",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
@monitor_query_performance(operation="temporal_top_relationships")
def temporal_top_relationship_pairs_api(request):
    """
    Get top organization-entity relationship pairs by total amount across all orgs/entities.

    This endpoint is for TEMPORAL EXPLORATION - it shows which Org×Entity combinations
    had the highest transaction amounts in a given date range, regardless of which
    specific organization or entity you're looking at.

    Use case: On /explore/temporal/{dates}, show the top money flows between
    any organization and any entity, allowing users to discover the biggest
    financial relationships in that time period.
    """
    # Parse and validate date range
    start_date, end_date, error_response = _parse_and_validate_date_range(
        request, context_label="temporal exploration"
    )
    if error_response:
        return error_response

    # Get pagination parameters
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    limit = int(request.GET.get("limit", 10))
    offset = int(request.GET.get("offset", 0))

    try:
        # Get top relationship pairs using financial service
        financial_service = FinancialCalculationService()
        result = financial_service.get_top_relationship_pairs(
            start_date=start_date, end_date=end_date, limit=limit, offset=offset
        )

        return Response(
            {
                "date_range": {
                    "start": start_date_str,
                    "end": end_date_str,
                },
                "results": result["results"],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total_count": result["total_count"],
                    "has_more": result["has_more"],
                },
            }
        )

    except Exception as e:
        import traceback

        logger.error(f"Error in temporal_top_relationship_pairs_api: {e}")
        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
