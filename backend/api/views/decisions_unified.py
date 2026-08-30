"""
Unified decisions API endpoint.

A single endpoint that serves all decision projections (paginated list,
decision types, statistics, date range) for any source (entity, AFM,
relationship, temporal, batch, subscription).

The source is selected via the ``source`` query parameter.  Facets (date
range, search, decision types, amount range, direct-assignments-only,
viewed, sort) are applied uniformly regardless of source.

Usage:
    GET /api/decisions/unified/?source=temporal&view=statistics
    GET /api/decisions/unified/?source=entity&entity_type=org&entity_id=123&view=decisions
    GET /api/decisions/unified/?source=relationship&afm=X&org_uid=Y&view=decision_types

This is the target shape described in the "Unify decision-returning endpoints"
design doc.
"""

from __future__ import annotations

import traceback

from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from loguru import logger
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response

from api.views.search.base import get_entity_info
from core.decorators.cache_decorator import cached_view
from core.services.decision_facets import (
    apply_decision_facets,
    parse_amount_range,
    parse_date_range_from_request,
    parse_sort_by,
)
from core.services.decision_projections import (
    aggregate_decision_types,
    compute_date_range,
    compute_statistics,
    paginate_decisions,
)
from core.services.decision_sources import (
    authorize_source,
    get_source_queryset,
)
from core.services.search_analytics_service import SearchAnalyticsService

# ---------------------------------------------------------------------------
# Swagger parameters (shared across all views)
# ---------------------------------------------------------------------------

_SOURCE_PARAM = openapi.Parameter(
    "source",
    openapi.IN_QUERY,
    description="Decision source: entity, afm, relationship, temporal, batch, subscription",
    type=openapi.TYPE_STRING,
    required=True,
)

_VIEW_PARAM = openapi.Parameter(
    "view",
    openapi.IN_QUERY,
    description="Projection: decisions, decision_types, statistics, date_range",
    type=openapi.TYPE_STRING,
    required=False,
)

_START_DATE_PARAM = openapi.Parameter(
    "start_date",
    openapi.IN_QUERY,
    description="Start date (YYYY-MM-DD)",
    type=openapi.TYPE_STRING,
)

_END_DATE_PARAM = openapi.Parameter(
    "end_date",
    openapi.IN_QUERY,
    description="End date (YYYY-MM-DD)",
    type=openapi.TYPE_STRING,
)

_PAGE_PARAM = openapi.Parameter(
    "page",
    openapi.IN_QUERY,
    description="Page number (for view=decisions)",
    type=openapi.TYPE_INTEGER,
)

_PAGE_SIZE_PARAM = openapi.Parameter(
    "page_size",
    openapi.IN_QUERY,
    description="Page size (for view=decisions)",
    type=openapi.TYPE_INTEGER,
)

_SORT_PARAM = openapi.Parameter(
    "sort_by",
    openapi.IN_QUERY,
    description="Sort: recent, oldest, amount_desc, amount_asc",
    type=openapi.TYPE_STRING,
)

_Q_PARAM = openapi.Parameter(
    "q",
    openapi.IN_QUERY,
    description="Full-text search query",
    type=openapi.TYPE_STRING,
)

_DECISION_TYPES_PARAM = openapi.Parameter(
    "decision_types",
    openapi.IN_QUERY,
    description="Comma-separated decision type UIDs",
    type=openapi.TYPE_STRING,
)

_MIN_AMOUNT_PARAM = openapi.Parameter(
    "min_amount",
    openapi.IN_QUERY,
    description="Minimum amount filter",
    type=openapi.TYPE_NUMBER,
)

_MAX_AMOUNT_PARAM = openapi.Parameter(
    "max_amount",
    openapi.IN_QUERY,
    description="Maximum amount filter",
    type=openapi.TYPE_NUMBER,
)

_DIRECT_ONLY_PARAM = openapi.Parameter(
    "direct_assignments_only",
    openapi.IN_QUERY,
    description="Filter to direct-assignment decisions only",
    type=openapi.TYPE_BOOLEAN,
)

_ORGANIZATION_IDS_PARAM = openapi.Parameter(
    "organization_ids",
    openapi.IN_QUERY,
    description="Comma-separated organization UIDs (for source=temporal)",
    type=openapi.TYPE_STRING,
)

_VIEWED_PARAM = openapi.Parameter(
    "viewed",
    openapi.IN_QUERY,
    description="Filter by viewed status (true/false/all). Only for batch/subscription sources.",
    type=openapi.TYPE_STRING,
)


# ---------------------------------------------------------------------------
# Caching helper
# ---------------------------------------------------------------------------

def _should_cache_unified(request) -> bool:
    """Only cache temporal-source projections that are cacheable.

    - view=date_range: global date boundaries rarely change (1h TTL)
    - view=statistics, view=decision_types: expensive aggregations that
      benefit from caching; cache key includes date range.
    - view=decisions is NOT cached (pagination + search queries vary).
    - Non-temporal sources (entity, afm, relationship, batch, subscription)
      are NOT cached (dynamic data, per-user scoping).
    """
    source = (request.GET.get("source") or "").strip().lower()
    view_name = (request.GET.get("view") or "decisions").strip().lower()
    if source != "temporal":
        return False
    return view_name in ("date_range", "statistics", "decision_types")


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        _SOURCE_PARAM,
        _VIEW_PARAM,
        _START_DATE_PARAM,
        _END_DATE_PARAM,
        _PAGE_PARAM,
        _PAGE_SIZE_PARAM,
        _SORT_PARAM,
        _Q_PARAM,
        _DECISION_TYPES_PARAM,
        _MIN_AMOUNT_PARAM,
        _MAX_AMOUNT_PARAM,
        _DIRECT_ONLY_PARAM,
        _ORGANIZATION_IDS_PARAM,
        _VIEWED_PARAM,
        # Source-specific params (documented but not validated globally)
        openapi.Parameter(
            "entity_type",
            openapi.IN_QUERY,
            description="Entity type for source=entity (org, signer, unit, afm)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "entity_id",
            openapi.IN_QUERY,
            description="Entity ID for source=entity",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "afm",
            openapi.IN_QUERY,
            description="AFM for source=afm or source=relationship",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "org_uid",
            openapi.IN_QUERY,
            description="Organization UID for source=relationship",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "batch_id",
            openapi.IN_QUERY,
            description="Batch ID for source=batch",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "subscription_id",
            openapi.IN_QUERY,
            description="Subscription ID for source=subscription",
            type=openapi.TYPE_STRING,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="unified",
    cache_params=["source", "view", "start_date", "end_date"],
    end_date_param="end_date",
    should_cache_fn=_should_cache_unified,
    log_cache_operations=True,
    defer_on_miss=True,
    defer_retry_after=30,
)
def decisions_unified_api(request):
    """
    Unified decisions endpoint.

    1. Build source queryset    (the ONLY thing that varies per source)
    2. Authorize source          (permissions co-located with source)
    3. Apply shared facets       (date, search, types, amount, direct, viewed, sort)
    4. Project                   (decisions | decision_types | statistics | date_range)
    """
    # ── 1. Build source queryset ────────────────────────────────────
    try:
        source_qs = get_source_queryset(request)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    # ── 2. Authorize ────────────────────────────────────────────────
    auth_err = authorize_source(request, source_qs)
    if auth_err is not None:
        return auth_err

    # ── 3. Apply facets ─────────────────────────────────────────────
    # Parse date range first so we can return a 400 on invalid input
    start_dt, end_dt, date_err = parse_date_range_from_request(request)
    if date_err is not None:
        return date_err

    try:
        qs = apply_decision_facets(
            source_qs,
            start_dt=start_dt,
            end_dt=end_dt,
            request=request,
        )
    except ValueError as e:
        return Response({"error": str(e)}, status=400)

    # ── 4. Project ──────────────────────────────────────────────────
    source = (request.GET.get("source") or "").strip().lower()
    view_name = (request.GET.get("view") or "decisions").strip().lower()

    try:
        if view_name == "decision_types":
            return Response(aggregate_decision_types(qs))

        elif view_name == "statistics":
            start_str = request.GET.get("start_date", "")
            end_str = request.GET.get("end_date", "")
            return Response(compute_statistics(qs, start_str, end_str))

        elif view_name == "date_range":
            result = compute_date_range(qs)

            # Embed entity metadata for source=entity so the frontend can
            # display the entity name in the page title (matches the shape
            # returned by the old entity_date_range_api_dev endpoint).
            if source == "entity":
                entity_type = (request.GET.get("entity_type") or "").strip()
                entity_id = (request.GET.get("entity_id") or "").strip()
                if entity_type and entity_id:
                    try:
                        result["entity"] = get_entity_info(entity_type, entity_id)
                    except Exception:
                        # Non-critical: page can still render with the raw ID.
                        pass

            return Response(result)

        else:  # "decisions" (default)
            page = int(request.GET.get("page", 1))
            page_size = int(request.GET.get("page_size", 20))
            search_query = (request.GET.get("q") or "").strip()

            # ── Search analytics tracking ──────────────────────────
            search_tracking = None
            search_log_id = None
            if search_query:
                source = (request.GET.get("source") or "").strip().lower()
                search_tracking = SearchAnalyticsService.log_search_start(
                    query=search_query,
                    search_types=["metadata", "content"],
                    entity_type=source,
                    entity_id=request.GET.get("entity_id", "")
                    or request.GET.get("afm", "")
                    or "all",
                    request=request,
                    filters_applied={
                        "start_date": request.GET.get("start_date", ""),
                        "end_date": request.GET.get("end_date", ""),
                        "sort_by": parse_sort_by(request),
                        "decision_types": request.GET.get("decision_types", ""),
                        "min_amount": request.GET.get("min_amount", ""),
                        "max_amount": request.GET.get("max_amount", ""),
                        "status": request.GET.get("status", ""),
                    },
                )

            # Echo applied filters back to the frontend (matches the shape
            # the old per-source endpoints returned).
            filters = {
                "search_query": search_query,
                "start_date": request.GET.get("start_date", ""),
                "end_date": request.GET.get("end_date", ""),
                "sort_by": parse_sort_by(request),
                "decision_types": request.GET.get("decision_types", ""),
                "organization_ids": request.GET.get("organization_ids", ""),
                "min_amount": request.GET.get("min_amount", ""),
                "max_amount": request.GET.get("max_amount", ""),
                "status": request.GET.get("status", ""),
            }

            result = paginate_decisions(
                qs,
                page=page,
                page_size=page_size,
                filters=filters,
            )

            # ── Log search completion ───────────────────────────────
            if search_tracking:
                search_log = SearchAnalyticsService.log_search_complete(
                    search_tracking,
                    result["pagination"]["total_count"],
                )
                search_log_id = search_log.id
                result["search_log_id"] = search_log_id

            return Response(result)

    except Exception:
        logger.exception("Error in decisions_unified_api")
        return Response(
            {
                "error": "Internal server error",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
