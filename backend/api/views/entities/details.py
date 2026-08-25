import hashlib
from datetime import date

from api.utils.common import get_client_ip
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.services.decision_facets import effective_linked_amount_sum
from core.services.feature_flag_service import feature_flags
from core.services.search_service import SearchService
from core.utils.performance_monitoring import monitor_query_performance
from django.conf import settings
from django.db.models import Count, F
from django.utils.dateparse import parse_date
from django_redis import get_redis_connection
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from api.permissions import AuthenticatedOrDebug
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
@monitor_query_performance(include_context=True)
def afm_entity_detail(request, afm):
    """Get AFM entity metadata with optional company info."""
    try:
        entity = AFMEntity.objects.get(afm=afm)

        entity_data = {
            "afm": entity.afm,
            "name": entity.name,
            "entity_type": entity.entity_type,
            "total_appearances": entity.total_appearances,
            "first_seen": entity.first_seen,
            "last_seen": entity.last_seen,
            "gemi_lookup_attempted": entity.gemi_lookup_attempted,
            "gemi_lookup_success": entity.gemi_lookup_success,
            "gemi_companies_count": entity.gemi_companies_count,
        }

        # Add company information if available — always show if it's in the DB
        company_data = None
        if entity.gemi_lookup_success:
            from core.models.companies import Company

            companies = Company.objects.filter(afm=entity.afm)
            if companies.exists():
                company = companies.first()
                company_data = {
                    "id": company.id,
                    "ar_gemi": company.ar_gemi,
                    "co_name_el": company.co_name_el,
                    "legal_type_name": company.legal_type_name,
                    "status_name": company.status_name,
                    "municipality_name": company.municipality_name,
                }

        entity_data["company"] = company_data

        # Check if this AFM is currently in the fetch queue (pending or being processed).
        # This lets the frontend show "in queue" / "processing" across page reloads.
        queue_status = None
        try:
            redis_client = get_redis_connection("default")
            from api.redis_keys import AFM_FETCH_QUEUE_ACTIVE, AFM_FETCH_QUEUE_PENDING

            if redis_client.sismember(AFM_FETCH_QUEUE_ACTIVE, afm):
                queue_status = "processing"
            elif redis_client.zscore(AFM_FETCH_QUEUE_PENDING, afm) is not None:
                queue_status = "pending"
        except Exception:
            # Redis may be temporarily unavailable; degrade gracefully
            pass

        entity_data["queue_status"] = queue_status

        return Response({"entity": entity_data})

    except AFMEntity.DoesNotExist:
        return Response({"error": "AFM entity not found"}, status=404)


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
@monitor_query_performance(include_context=True)
def afm_entity_decisions(request, afm):
    """Get decisions related to an AFM entity."""
    try:
        entity = AFMEntity.objects.get(afm=afm)

        # Get query parameters
        page = int(request.GET.get("page", 1))
        page_size = int(request.GET.get("page_size", 20))
        sort_by = request.GET.get("sort", "recent")
        roles_filter = (
            request.GET.get("roles", "").split(",") if request.GET.get("roles") else []
        )
        direct_assignments_only = request.GET.get(
            "direct_assignments_only", ""
        ).lower() in ["true", "1", "yes"]

        # Base query with optimized joins
        relationships = (
            DecisionEntityRelationship.objects.filter(entity=entity)
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
            .prefetch_related("linked_amounts")
        )

        # Apply role filter
        if roles_filter and roles_filter != [""]:
            relationships = relationships.filter(role__in=roles_filter)

        # Apply direct assignments filter
        if direct_assignments_only:
            relationships = relationships.filter(
                decision__classification__is_direct_assignment=True
            )

        # Apply date range filter (uses indexed issue_date_day for performance)
        start_date_str = request.GET.get("start_date")
        end_date_str = request.GET.get("end_date")

        if start_date_str:
            parsed = parse_date(start_date_str)
            if parsed:
                relationships = relationships.filter(
                    decision__issue_date_day__gte=parsed
                )

        if end_date_str:
            parsed = parse_date(end_date_str)
            if parsed:
                relationships = relationships.filter(
                    decision__issue_date_day__lte=parsed
                )

        # Apply full-text search filter (delegates to SearchService for tiered search)
        search_query = request.GET.get("q", "").strip()
        if search_query:
            relationships = relationships.filter(
                SearchService().build_decision_search_q(search_query, prefix="decision")
            )

        # Apply sorting with proper NULL handling
        from api.utils.sorting import apply_aggregated_amount_sorting

        # For amount sorting, annotate with total linked amount first
        if sort_by in ("amount_desc", "amount_asc"):
            relationships = relationships.annotate(
                total_linked_amount=effective_linked_amount_sum()
            )
            relationships = apply_aggregated_amount_sorting(
                relationships,
                sort_by,
                aggregation_annotation="total_linked_amount",
                date_field="decision__issue_date_day",
            )
        elif sort_by == "recent":
            relationships = relationships.order_by("-decision__issue_date_day")
        elif sort_by == "oldest":
            relationships = relationships.order_by("decision__issue_date_day")
        else:
            # Default to recent
            relationships = relationships.order_by("-decision__issue_date_day")

        # Pagination
        total_items = relationships.count()
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size

        paginated_relationships = relationships[start_idx:end_idx]

        # Collect decision IDs for batch entity-relationship query
        decision_ids = [rel.decision_id for rel in paginated_relationships]

        # Batch-fetch ALL entity relationships for these decisions (eliminates N+1)
        all_entity_rels_qs = (
            DecisionEntityRelationship.objects
            .filter(decision_id__in=decision_ids)
            .select_related("entity")
            .annotate(total_amount=effective_linked_amount_sum())
        )

        # Group by decision_id: {decision_id: [rel_dict, ...]}
        entity_rels_by_decision = {}
        for rel in all_entity_rels_qs:
            rel_dict = {
                "role": rel.role,
                "entity": {
                    "afm": rel.entity.afm,
                    "name": rel.entity.name,
                    "entity_type": rel.entity.entity_type,
                    "total_appearances": rel.entity.total_appearances,
                    "first_seen": rel.entity.first_seen,
                    "last_seen": rel.entity.last_seen,
                    "gemi_lookup_success": rel.entity.gemi_lookup_success,
                    "gemi_companies_count": rel.entity.gemi_companies_count,
                },
                "parent_key_paths": [rel.parent_key_path],
                "total_amount": float(rel.total_amount) if rel.total_amount else 0.0,
                "currency": "EUR",
            }
            key = (rel.role, rel.entity_id)
            existing = next(
                (r for r in entity_rels_by_decision.setdefault(rel.decision_id, [])
                 if r["role"] == rel.role and r["entity"]["afm"] == rel.entity.afm),
                None,
            )
            if existing:
                existing["parent_key_paths"].append(rel.parent_key_path)
                existing["total_amount"] += rel_dict["total_amount"]
                existing["occurrences"] += 1
            else:
                rel_dict["occurrences"] = 1
                entity_rels_by_decision.setdefault(rel.decision_id, []).append(rel_dict)

        # Serialize decisions with linked amounts and entity data
        decisions = []
        for rel in paginated_relationships:
            decision = rel.decision

            # Calculate total amount from linked amounts (for this entity's relationship)
            total_amount = sum(
                amount.amount
                for amount in rel.linked_amounts.all()
                if amount.amount is not None
            )

            # Get all entity relationships for this decision (pre-fetched batch)
            all_entities = entity_rels_by_decision.get(decision.id, [])

            # Compute entity_amount (sum of non-org entity amounts)
            entity_amount = sum(
                e["total_amount"] for e in all_entities
                if e.get("role", "").lower() != "org" and e["total_amount"]
            )

            # Find main recipient (sponsor/creditor with amount, excluding the queried AFM context)
            main_recipient = None
            for e in all_entities:
                if e.get("role", "").lower() == "org":
                    continue
                if e["total_amount"] and (
                    not main_recipient
                    or e.get("role", "").lower() in ("sponsorafmname", "creditor", "sponsor")
                ):
                    main_recipient = {
                        "afm": e["entity"]["afm"],
                        "name": e["entity"]["name"],
                        "amount": e["total_amount"],
                        "role": e["role"],
                    }

            decisions.append(
                {
                    "id": decision.id,
                    "ada": decision.ada,
                    "subject": decision.subject,
                    "amount": float(total_amount) if total_amount > 0 else None,
                    "legacy_amount": (
                        float(decision.amount) if decision.amount else None
                    ),  # Keep for comparison
                    "issue_date": decision.issue_date_day,
                    "status": decision.status,
                    "document_url": decision.document_url,
                    "has_document_content": hasattr(decision, "document_extraction"),
                    "organization": (
                        {
                            "uid": decision.organization.uid,
                            "label": decision.organization.label,
                        }
                        if decision.organization
                        else None
                    ),
                    "decision_type": (
                        {
                            "uid": decision.decision_type.uid,
                            "label": decision.decision_type.label,
                        }
                        if decision.decision_type
                        else None
                    ),
                    "entity_role": rel.role,
                    "confidence_score": rel.confidence_score,
                    "amount_count": rel.linked_amounts.count(),
                    # Preloaded entity data (eliminates N+1 in frontend)
                    "entity_amount": float(entity_amount) if entity_amount else None,
                    "main_recipient": main_recipient,
                    "entities": all_entities,
                }
            )

        pagination_info = {
            "current_page": page,
            "page_size": page_size,
            "total_items": total_items,
            "total_pages": (total_items + page_size - 1) // page_size,
            "has_next": end_idx < total_items,
            "has_previous": page > 1,
        }

        return Response({"results": decisions, "pagination": pagination_info})

    except AFMEntity.DoesNotExist:
        return Response({"error": "AFM entity not found"}, status=404)


# ---------------------------------------------------------------------------
# AFM decision-types / statistics / date-range wrappers
#
# These thin wrappers build a Decision queryset from the AFM entity's
# relationships and delegate to the shared projection layer.  They fill the
# gap where only /entity/afm/<afm>/decisions/ existed before.
# ---------------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def afm_entity_decision_types(request, afm):
    """
    Get available decision types for an AFM entity.

    Delegates to the shared ``aggregate_decision_types`` projection.
    """
    from api.utils.date_utils import _parse_optional_date_range
    from core.models.decisions import Decision
    from core.services.decision_projections import aggregate_decision_types

    try:
        AFMEntity.objects.get(afm=afm)
    except AFMEntity.DoesNotExist:
        return Response({"error": "AFM entity not found"}, status=404)

    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    decisions_qs = Decision.objects.filter(
        entity_relationships__entity__afm=afm,
    ).distinct()

    if hasattr(decisions_qs, "filter_by_date_range"):
        decisions_qs = decisions_qs.filter_by_date_range(start_dt, end_dt)

    return Response(aggregate_decision_types(decisions_qs))


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def afm_entity_statistics(request, afm):
    """
    Get summary statistics for an AFM entity.

    Delegates to the shared ``compute_statistics`` projection.
    """
    from api.utils.date_utils import _parse_optional_date_range
    from core.models.decisions import Decision
    from core.services.decision_projections import compute_statistics

    try:
        entity = AFMEntity.objects.get(afm=afm)
    except AFMEntity.DoesNotExist:
        return Response({"error": "AFM entity not found"}, status=404)

    start_dt, end_dt, err = _parse_optional_date_range(request)
    if err:
        return err

    decisions_qs = Decision.objects.filter(
        entity_relationships__entity__afm=afm,
    ).distinct()

    if hasattr(decisions_qs, "filter_by_date_range"):
        decisions_qs = decisions_qs.filter_by_date_range(start_dt, end_dt)

    start_str = request.GET.get("start_date", "")
    end_str = request.GET.get("end_date", "")

    result = compute_statistics(decisions_qs, start_str, end_str)
    result["entity"] = {
        "id": afm,
        "name": entity.name or afm,
        "type": "afm",
    }
    return Response(result)


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def afm_entity_date_range(request, afm):
    """
    Get date range and activity overview for an AFM entity.

    Delegates to the shared ``compute_date_range`` projection.
    """
    from core.models.decisions import Decision
    from core.services.decision_projections import compute_date_range

    try:
        entity = AFMEntity.objects.get(afm=afm)
    except AFMEntity.DoesNotExist:
        return Response({"error": "AFM entity not found"}, status=404)

    decisions_qs = Decision.objects.filter(
        entity_relationships__entity__afm=afm,
    ).distinct()

    result = compute_date_range(decisions_qs)
    result["entity"] = {
        "id": afm,
        "name": entity.name or afm,
        "type": "afm",
    }
    return Response(result)


@api_view(["POST"])
@permission_classes([AllowAny])
def request_afm_fetch(request, afm):
    """
    Endpoint to request GEMI data fetching for a specific AFM.

    Access control and rate limiting are driven by feature flags:
      - GEMI_FETCH_REQUEST_PUBLIC_ACCESS  : allow unauthenticated users (default True)
      - GEMI_FETCH_REQUEST_DAILY_LIMIT    : max requests per IP per UTC day (default 10)
    """
    # --- Auth gate (driven by feature flag) ---
    if not feature_flags.is_enabled("GEMI_FETCH_REQUEST_PUBLIC_ACCESS"):
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"status": "auth_required", "message": "You must be logged in to request a company data fetch."},
                status=401,
            )

    # --- IP-based rate limiting via Redis ---
    ip = get_client_ip(request)
    # Hash the IP so we don't store PII in plain text in Redis
    ip_hash = hashlib.sha256((ip or "unknown").encode()).hexdigest()[:16]
    today = date.today().isoformat()
    rate_key = f"gemi_fetch_req:{ip_hash}:{today}"

    daily_limit = feature_flags.get_value("GEMI_FETCH_REQUEST_DAILY_LIMIT")
    if not isinstance(daily_limit, int) or daily_limit <= 0:
        daily_limit = 10  # safe fallback

    redis_client = get_redis_connection("default")
    current_count = redis_client.incr(rate_key)
    if current_count == 1:
        # First hit today — set key to expire at end of the UTC day
        from datetime import datetime, timedelta, timezone as tz

        now = datetime.now(tz.utc)
        midnight = datetime(now.year, now.month, now.day, tzinfo=tz.utc)
        seconds_until_midnight = int((midnight + timedelta(days=1) - now).total_seconds())
        redis_client.expire(rate_key, seconds_until_midnight)

    if current_count > daily_limit:
        logger.info(f"Rate limit hit for GEMI fetch request (ip_hash={ip_hash})")
        return Response(
            {
                "status": "rate_limited",
                "message": f"You have reached the daily limit of {daily_limit} fetch requests. Please try again tomorrow.",
            },
            status=429,
        )

    # --- Validate entity exists ---
    try:
        entity = AFMEntity.objects.get(afm=afm)
    except AFMEntity.DoesNotExist:
        return Response({"status": "not_found", "message": "AFM entity not found."}, status=404)

    # --- Already successfully fetched ---
    if entity.gemi_lookup_success and entity.gemi_companies_count is not None:
        return Response(
            {
                "status": "already_fetched",
                "message": "Company data for this AFM has already been retrieved.",
            }
        )

    # --- Queue the fetch ---
    from core.services.afm_fetch_queue_service import AFMFetchQueueService

    queue_service = AFMFetchQueueService()
    added = queue_service.add_single_afm(
        afm=afm,
        jump_queue=False,
        auto_trigger=True,
    )

    if added:
        logger.info(f"User-requested GEMI fetch queued for AFM {afm} (ip_hash={ip_hash})")
        return Response(
            {
                "status": "queued",
                "message": "Your request has been queued. Company data will appear on this page once fetched.",
            }
        )
    else:
        return Response(
            {
                "status": "already_queued",
                "message": "This AFM is already in the fetch queue or has been processed.",
            }
        )
