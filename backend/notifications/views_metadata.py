"""
Metadata endpoints for notification subscription system.

These endpoints provide schema information and available values
needed by the frontend to build the subscription UI.
"""

from core.models.types import ActType
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@swagger_auto_schema(
    method="get",
    operation_description="""
    Get metadata about the notification subscription system.

    Returns:
    - Available subscription types (targets)
    - Available filter parameters
    - Valid values for each field
    - Field descriptions and constraints

    Use this to dynamically build your subscription creation UI.
    """,
    responses={
        200: openapi.Response(
            description="Subscription system metadata",
            examples={
                "application/json": {
                    "subscription_types": [
                        {
                            "type": "organization",
                            "label": "Organization",
                            "description": "Watch all decisions from a specific organization",
                            "required_fields": ["organization_uid"],
                            "example": {"organization_uid": "99221718"},
                        }
                    ],
                    "filter_parameters": {
                        "keywords": {
                            "type": "array",
                            "description": "List of keywords to match in decision subject/content",
                            "example": ["procurement", "contract"],
                        }
                    },
                    "check_frequency_options": [
                        {"value": "daily", "label": "Daily"},
                        {"value": "weekly", "label": "Weekly"},
                    ],
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def subscription_metadata(request):
    """
    Get comprehensive metadata about the notification subscription system.
    """

    metadata = {
        "subscription_types": [
            {
                "type": "organization",
                "label": "Organization",
                "description": "Watch all decisions from a specific organization",
                "icon": "building",
                "required_fields": ["organization_uid"],
                "optional_filters": [
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {
                    "organization_uid": "99221718",
                    "keywords": ["contract"],
                    "check_frequency": "daily",
                },
            },
            {
                "type": "entity",
                "label": "AFM Entity",
                "description": "Watch decisions involving a specific AFM entity (company/person)",
                "icon": "company",
                "required_fields": ["entity_afm"],
                "optional_filters": [
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {"entity_afm": "123456789", "amount_min": "10000.00"},
            },
            {
                "type": "relationship",
                "label": "Organization-Entity Relationship",
                "description": "Watch decisions involving a specific organization and entity together",
                "icon": "link",
                "required_fields": ["relationship_org_uid", "relationship_entity_afm"],
                "optional_filters": [
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {
                    "relationship_org_uid": "99221718",
                    "relationship_entity_afm": "123456789",
                },
            },
            {
                "type": "person",
                "label": "Company Person",
                "description": "Watch companies where a specific person is associated (director, representative, etc.)",
                "icon": "user-tie",
                "required_fields": ["person_name"],
                "optional_filters": [
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {"person_name": "Γεώργιος Παπαδόπουλος"},
            },
            {
                "type": "signer",
                "label": "Decision Signer",
                "description": "Watch decisions signed by a specific person",
                "icon": "user-check",
                "required_fields": ["signer_name"],
                "optional_filters": [
                    "organization_uid",
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {
                    "signer_name": "Γεώργιος Παπαδόπουλος",
                    "organization_uid": "99221718",
                },
            },
            {
                "type": "filter",
                "label": "Filter Only",
                "description": "Watch decisions matching specific criteria without targeting a specific organization/entity",
                "icon": "filter",
                "required_fields": [],
                "required_filters": "At least one of: keywords, amount_min, amount_max, decision_types",
                "optional_filters": [
                    "keywords",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ],
                "example": {
                    "keywords": ["urgent", "procurement"],
                    "amount_min": "50000.00",
                    "decision_types": ["Β.1.1", "Β.1.2"],
                },
            },
        ],
        "filter_parameters": {
            "keywords": {
                "type": "array",
                "item_type": "string",
                "description": "List of keywords to match in decision subject or content (case-insensitive, OR logic)",
                "validation": {
                    "min_items": 1,
                    "max_items": 20,
                    "max_length_per_item": 100,
                },
                "example": ["procurement", "contract", "urgent"],
            },
            "amount_min": {
                "type": "decimal",
                "description": "Minimum decision amount (inclusive)",
                "validation": {"min_value": 0, "max_digits": 15, "decimal_places": 2},
                "example": "10000.00",
            },
            "amount_max": {
                "type": "decimal",
                "description": "Maximum decision amount (inclusive)",
                "validation": {"min_value": 0, "max_digits": 15, "decimal_places": 2},
                "example": "50000.00",
            },
            "decision_types": {
                "type": "array",
                "item_type": "string",
                "description": "List of decision type UIDs to filter by (OR logic). Use /api/notifications/metadata/decision-types/ to get available types.",
                "validation": {"min_items": 1, "max_items": 50},
                "example": ["Β.1.1", "Β.1.2", "Α.1.1"],
            },
        },
        "check_frequency_options": [
            {
                "value": "daily",
                "label": "Daily",
                "description": "Check for new matching decisions once per day",
            },
            {
                "value": "weekly",
                "label": "Weekly",
                "description": "Check for new matching decisions once per week",
            },
            {
                "value": "manual",
                "label": "Manual Only",
                "description": "Only check when manually triggered via the UI or API",
            },
        ],
        "validation_rules": {
            "target_or_filter_required": "At least one target (organization, entity, relationship, person, signer) OR at least one filter must be set",
            "relationship_requires_both": "Relationship subscriptions require both organization and entity",
            "amount_range_validation": "If both amount_min and amount_max are set, amount_min must be <= amount_max",
        },
        "endpoints": {
            "search_organizations": "/api/search/entities-fast/?q={query}&types=organization",
            "search_entities": "/api/search/entities-fast/?q={query}&types=company",
            "search_signers": "/api/search/entities-fast/?q={query}&types=signer",
            "search_company_persons": "/api/search/entities-fast/?q={query}&types=company_person",
            "decision_types": "/api/notifications/metadata/decision-types/",
            "create_subscription": "/api/notifications/subscriptions/",
            "list_subscriptions": "/api/notifications/subscriptions/",
            "check_organization_subscription": "/api/notifications/subscriptions/check-organization/{org_uid}/",
            "check_entity_subscription": "/api/notifications/subscriptions/check-entity/{afm}/",
        },
    }

    return Response(metadata)


@swagger_auto_schema(
    method="get",
    operation_description="""
    Get list of all available decision types.

    Decision types represent different categories of government decisions
    (e.g., procurement contracts, appointments, financial approvals).

    Use these UIDs when creating subscriptions with decision_types filter.
    """,
    manual_parameters=[
        openapi.Parameter(
            "search",
            openapi.IN_QUERY,
            description="Optional search term to filter decision types by label",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "allowed_only",
            openapi.IN_QUERY,
            description="Only return types allowed in decisions (default: true)",
            type=openapi.TYPE_BOOLEAN,
            required=False,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of results (default: 100, max: 500)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
    responses={
        200: openapi.Response(
            description="List of decision types",
            examples={
                "application/json": {
                    "count": 150,
                    "decision_types": [
                        {
                            "uid": "Β.1.1",
                            "label": "Προμήθειες - Υπηρεσίες",
                            "allowed_in_decisions": True,
                            "has_children": False,
                        }
                    ],
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def decision_types_list(request):
    """
    Get list of all available decision types.
    """
    search_term = request.query_params.get("search", "").strip()
    allowed_only = request.query_params.get("allowed_only", "true").lower() == "true"
    limit = min(int(request.query_params.get("limit", 100)), 500)

    # Build queryset
    queryset = ActType.objects.all()

    if allowed_only:
        queryset = queryset.filter(allowed_in_decisions=True)

    if search_term:
        queryset = queryset.filter(label__icontains=search_term)

    # Order by UID for consistent results
    queryset = queryset.order_by("uid")[:limit]

    # Serialize
    decision_types = [
        {
            "uid": dt.uid,
            "label": dt.label,
            "allowed_in_decisions": dt.allowed_in_decisions,
            "has_children": dt.child_types.exists(),
            "parent_uid": dt.parent_id if dt.parent_id else None,
        }
        for dt in queryset
    ]

    return Response(
        {
            "count": len(decision_types),
            "total_count": (
                ActType.objects.filter(allowed_in_decisions=True).count()
                if allowed_only
                else ActType.objects.count()
            ),
            "decision_types": decision_types,
        }
    )


@swagger_auto_schema(
    method="get",
    operation_description="""
    Get popular/frequently used decision types.

    Returns decision types that are most commonly used in decisions,
    useful for showing common options first in the UI.
    """,
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Number of top types to return (default: 20)",
            type=openapi.TYPE_INTEGER,
            required=False,
        )
    ],
    responses={
        200: openapi.Response(
            description="Popular decision types with usage counts",
            examples={
                "application/json": {
                    "popular_types": [
                        {
                            "uid": "Β.1.1",
                            "label": "Προμήθειες - Υπηρεσίες",
                            "decision_count": 15420,
                            "percentage": 12.5,
                        }
                    ]
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def popular_decision_types(request):
    """
    Get popular/frequently used decision types based on actual usage.
    """
    from core.models.decisions import Decision
    from django.db.models import Count

    limit = min(int(request.query_params.get("limit", 20)), 100)

    # Get decision types with counts
    popular = (
        ActType.objects.filter(allowed_in_decisions=True)
        .annotate(decision_count=Count("decisions"))
        .filter(decision_count__gt=0)
        .order_by("-decision_count")[:limit]
    )

    total_decisions = Decision.objects.count()

    result = {
        "popular_types": [
            {
                "uid": dt.uid,
                "label": dt.label,
                "decision_count": dt.decision_count,
                "percentage": (
                    round((dt.decision_count / total_decisions * 100), 2)
                    if total_decisions > 0
                    else 0
                ),
            }
            for dt in popular
        ],
        "total_decisions": total_decisions,
    }

    return Response(result)
