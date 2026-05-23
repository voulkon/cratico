from datetime import datetime

from core.decorators.cache_decorator import cached_view
from core.models.decisions import Decision
from core.services.feature_flag_service import feature_flags
from django.conf import settings
from django.core.paginator import Paginator
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response

from .base import serialize_decision_with_entities


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
    ),
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
        from core.models.entities import DecisionEntityRelationship

        # Get all decisions
        decisions_qs = Decision.objects.all()

        # Apply date filters with timezone awareness
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

        # Apply filters
        if status_filter:
            decisions_qs = decisions_qs.filter(status=status_filter)
        if decision_type_uids:
            decisions_qs = decisions_qs.filter(
                decision_type__uid__in=decision_type_uids
            )
        if organization_uid:
            decisions_qs = decisions_qs.filter(organization__uid=organization_uid)
        if organization_ids:
            decisions_qs = decisions_qs.filter(organization__uid__in=organization_ids)
        if entity_afm:
            # Filter decisions that have a relationship with this entity
            decisions_qs = decisions_qs.filter(
                id__in=DecisionEntityRelationship.objects.filter(
                    entity__afm=entity_afm
                ).values_list("decision_id", flat=True)
            )
        if min_amount is not None:
            decisions_qs = decisions_qs.filter(amount__gte=min_amount)
        if max_amount is not None:
            decisions_qs = decisions_qs.filter(amount__lte=max_amount)
        if direct_assignments_only:
            # Filter to show only direct assignment decisions
            decisions_qs = decisions_qs.filter(
                classification__is_direct_assignment=True
            )

        # Annotate with entity amounts for sorting
        from django.db.models import DecimalField, OuterRef, Subquery, Sum

        # Subquery to get total entity amount per decision (excluding 'org' role)
        entity_amounts = (
            DecisionEntityRelationship.objects.filter(decision_id=OuterRef("pk"))
            .exclude(role__iexact="org")
            .values("decision_id")
            .annotate(total=Sum("linked_amounts__amount"))
            .values("total")
        )

        decisions_qs = decisions_qs.annotate(
            entity_total_amount=Subquery(entity_amounts, output_field=DecimalField())
        )

        # Apply sorting
        if sort_by == "entity_amount_desc":
            # Sort by entity amount (highest first), then by decision amount, then by date
            decisions_qs = decisions_qs.annotate(
                sort_amount=models.Case(
                    models.When(
                        entity_total_amount__isnull=False,
                        then=models.F("entity_total_amount"),
                    ),
                    models.When(amount__isnull=False, then=models.F("amount")),
                    default=models.Value(-999999999),
                    output_field=models.DecimalField(),
                )
            ).order_by("-sort_amount", "-issue_date")
        elif sort_by == "entity_amount_asc":
            decisions_qs = decisions_qs.annotate(
                sort_amount=models.Case(
                    models.When(
                        entity_total_amount__isnull=False,
                        then=models.F("entity_total_amount"),
                    ),
                    models.When(amount__isnull=False, then=models.F("amount")),
                    default=models.Value(999999999),
                    output_field=models.DecimalField(),
                )
            ).order_by("sort_amount", "-issue_date")
        elif sort_by == "recent":
            decisions_qs = decisions_qs.order_by("-issue_date")
        else:
            # Default to entity amount desc
            decisions_qs = decisions_qs.annotate(
                sort_amount=models.Case(
                    models.When(
                        entity_total_amount__isnull=False,
                        then=models.F("entity_total_amount"),
                    ),
                    models.When(amount__isnull=False, then=models.F("amount")),
                    default=models.Value(-999999999),
                    output_field=models.DecimalField(),
                )
            ).order_by("-sort_amount", "-issue_date")

        # Optimize with select_related and prefetch_related
        decisions_qs = decisions_qs.select_related(
            "decision_type", "organization", "text_extraction"
        ).prefetch_related("kae_amounts", "signers")

        # Pagination
        paginator = Paginator(decisions_qs, page_size)
        page_obj = paginator.get_page(page)

        # Get decision IDs for this page
        decision_ids = [d.id for d in page_obj]

        # Fetch all entity relationships for these decisions in one query
        entity_relationships_qs = (
            DecisionEntityRelationship.objects.filter(decision_id__in=decision_ids)
            .select_related("entity")
            .annotate(total_amount=Sum("linked_amounts__amount"))
        )

        # Group entity relationships by decision_id
        relationships_by_decision = {}
        for rel in entity_relationships_qs:
            if rel.decision_id not in relationships_by_decision:
                relationships_by_decision[rel.decision_id] = []

            relationships_by_decision[rel.decision_id].append(
                {
                    "role": rel.role,
                    "entity": {
                        "afm": rel.entity.afm,
                        "name": rel.entity.name,
                        "entity_type": rel.entity.entity_type,
                    },
                    "total_amount": float(rel.total_amount) if rel.total_amount else 0,
                }
            )

        # Serialize results with entity data
        results = []
        for decision in page_obj:
            entity_rels = relationships_by_decision.get(decision.id, [])
            decision_data = serialize_decision_with_entities(decision, entity_rels)

            # Add organization for temporal exploration
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
                "organization_uid": organization_uid,
                "entity_afm": entity_afm,
                "decision_types": decision_types_str,
                "organization_ids": organization_ids_str,
                "min_amount": min_amount,
                "max_amount": max_amount,
                "direct_assignments_only": direct_assignments_only,
            },
            "optimization_info": {
                "entity_data_included": True,
                "eliminates_n_plus_1": True,
                "default_sort": "entity_amount_desc",
            },
        }

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
