"""
Pre-calculation for explore/decisions/ endpoint.

Two-layer design:
  compute_explore_decisions(…)    → pure DB query (full filter/sort/paginate)
  warm_explore_decisions_window(…) → calls compute + caches under exact Redis keys
"""

import math
from datetime import date, datetime
from typing import List, Optional

from django.core.paginator import Paginator
from django.db.models import (
    Case, Count, DecimalField, F, OuterRef, Q, Subquery, When,
)
from loguru import logger

from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship
from core.services.decision_facets import effective_linked_amount_sum
from core.services.feature_flag_service import feature_flags
from api.views.search.base import serialize_decision_with_entities

from ._helpers import _make_aware_start, _make_aware_end, parse_date, response_cache

__all__ = [
    "compute_explore_decisions",
    "warm_explore_decisions_window",
]


def compute_explore_decisions(
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    start_date_str: str,
    end_date_str: str,
    page: int = 1,
    page_size: int = 20,
    search_query: str = "",
    status_filter: str = "",
    sort_by: str = "entity_amount_desc",
    organization_uid: str = "",
    entity_afm: str = "",
    decision_type_uids: Optional[List[str]] = None,
    organization_ids: Optional[List[str]] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    direct_assignments_only: bool = False,
) -> dict:
    """
    Run the explore-decisions DB query and return the response dict.

    Single source of truth shared by:
      - explore_decisions_optimized_api  (view delegates here on cache miss)
      - warm_explore_decisions_window    (warmup pre-populates cache)

    Covers the full filtering + sorting + pagination + entity-relationship
    serialization that the view previously did inline.

    Args:
        start_dt, end_dt: Timezone-aware datetimes (or None) for date filter.
        start_date_str, end_date_str: Original string form for the response.
        page, page_size: Pagination.
        search_query: Full-text / subject+ADA search (empty = no search).
        status_filter: Decision status filter (empty = no filter).
        sort_by: entity_amount_desc, entity_amount_asc, or recent.
        organization_uid: Filter by single org UID (empty = no filter).
        entity_afm: Filter by entity AFM (empty = no filter).
        decision_type_uids: Filter by decision type UIDs (None/empty = no filter).
        organization_ids: Filter by multiple org UIDs (None/empty = no filter).
        min_amount, max_amount: Amount range filters (None = no filter).
        direct_assignments_only: Filter to direct-assignment decisions only.
    """
    decision_type_uids = decision_type_uids or []
    organization_ids = organization_ids or []

    # ── Base queryset with date filter ──────────────────────────────
    decisions_qs = Decision.objects.filter_by_date_range(start_dt, end_dt)

    # ── Search ─────────────────────────────────────────────────────
    if search_query:
        q_filter = Q(subject__icontains=search_query) | Q(
            ada__icontains=search_query
        )
        if feature_flags.is_enabled("INDEX_THE_POSTGRES"):
            from django.contrib.postgres.search import SearchQuery

            search_query_obj = SearchQuery(search_query)
            q_filter |= Q(text_extraction__search_vector=search_query_obj)
        decisions_qs = decisions_qs.filter(q_filter).distinct()

    # ── Status ──────────────────────────────────────────────────────
    if status_filter:
        decisions_qs = decisions_qs.filter(status=status_filter)

    # ── Decision types ──────────────────────────────────────────────
    if decision_type_uids:
        decisions_qs = decisions_qs.filter(
            decision_type__uid__in=decision_type_uids
        )

    # ── Organization (single) ───────────────────────────────────────
    if organization_uid:
        decisions_qs = decisions_qs.filter(organization__uid=organization_uid)

    # ── Organizations (multiple) ────────────────────────────────────
    if organization_ids:
        decisions_qs = decisions_qs.filter(organization__uid__in=organization_ids)

    # ── Entity (by AFM) ─────────────────────────────────────────────
    if entity_afm:
        decisions_qs = decisions_qs.filter(
            id__in=DecisionEntityRelationship.objects.filter(
                entity__afm=entity_afm
            ).values_list("decision_id", flat=True)
        )

    # ── Amount range ────────────────────────────────────────────────
    if min_amount is not None:
        decisions_qs = decisions_qs.filter(amount__gte=min_amount)
    if max_amount is not None:
        decisions_qs = decisions_qs.filter(amount__lte=max_amount)

    # ── Direct assignments only ─────────────────────────────────────
    if direct_assignments_only:
        decisions_qs = decisions_qs.filter(
            classification__is_direct_assignment=True
        )

    # ── Annotate with entity total amount ───────────────────────────
    entity_amounts = (
        DecisionEntityRelationship.objects.filter(decision_id=OuterRef("pk"))
        .exclude(role__iexact="org")
        .values("decision_id")
        .annotate(total=effective_linked_amount_sum())
        .values("total")
    )
    decisions_qs = decisions_qs.annotate(
        entity_total_amount=Subquery(entity_amounts, output_field=DecimalField())
    )

    # ── Sorting ─────────────────────────────────────────────────────
    sort_amount_null_default = -999999999 if "desc" in sort_by else 999999999
    decisions_qs = decisions_qs.annotate(
        sort_amount=Case(
            When(
                entity_total_amount__isnull=False,
                then=F("entity_total_amount"),
            ),
            When(amount__isnull=False, then=F("amount")),
            default=sort_amount_null_default,
            output_field=DecimalField(),
        )
    )

    if sort_by == "entity_amount_desc":
        decisions_qs = decisions_qs.order_by("-sort_amount", "-issue_date_day")
    elif sort_by == "entity_amount_asc":
        decisions_qs = decisions_qs.order_by("sort_amount", "-issue_date_day")
    elif sort_by == "recent":
        decisions_qs = decisions_qs.order_by("-issue_date_day")
    else:
        decisions_qs = decisions_qs.order_by("-sort_amount", "-issue_date_day")

    # ── Optimize ────────────────────────────────────────────────────
    decisions_qs = decisions_qs.select_related(
        "decision_type", "organization", "text_extraction"
    ).prefetch_related("kae_amounts", "signers")

    # ── Pagination ──────────────────────────────────────────────────
    paginator = Paginator(decisions_qs, page_size)
    page_obj = paginator.get_page(page)

    # ── Batch-fetch entity relationships (eliminates N+1) ───────────
    decision_ids = [d.id for d in page_obj]
    entity_relationships_qs = (
        DecisionEntityRelationship.objects.filter(decision_id__in=decision_ids)
        .select_related("entity")
        .annotate(total_amount=effective_linked_amount_sum())
    )

    relationships_by_decision: dict = {}
    for rel in entity_relationships_qs:
        relationships_by_decision.setdefault(rel.decision_id, []).append(
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

    # ── Serialize ───────────────────────────────────────────────────
    results = []
    for decision in page_obj:
        entity_rels = relationships_by_decision.get(decision.id, [])
        decision_data = serialize_decision_with_entities(decision, entity_rels)

        if (
            hasattr(decision, "calculated_amount")
            and decision.calculated_amount is not None
        ):
            decision_data["amount"] = float(decision.calculated_amount)

        if decision.organization:
            decision_data["organization"] = {
                "uid": decision.organization.uid,
                "label": decision.organization.label,
            }
        results.append(decision_data)

    return {
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
            "decision_types": ",".join(decision_type_uids) if decision_type_uids else "",
            "organization_ids": ",".join(organization_ids) if organization_ids else "",
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


def warm_explore_decisions_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 200,
    page_size: int = 5,
) -> None:
    """
    Compute explore-decisions ONCE with a large page size, then slice
    into page_size batches and cache each one under the exact key the
    frontend will request (matching page + page_size).

    Why: the cache key includes both ``page`` and ``page_size``, so a
    single ``page_size=100`` cache entry would never satisfy a frontend
    request for ``page_size=20&page=2``.  By pre-slicing we cover every
    paginated request the frontend makes while infinite-scrolling —
    without re-running the heavy DB query.

    Args:
        start_date_str: ISO date string used verbatim in the cache key
        end_date_str:   ISO date string used verbatim in the cache key
        end_date:       Python date for smart TTL selection
        max_limit:      How many decisions to pre-compute in one query
        page_size:      Frontend's page size — must match what the
                        DecisionsSection sends (homepage sends page_size=5)
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_explore_decisions_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    # ── compute ONCE with the large page size ──────────────────────
    data = compute_explore_decisions(
        start_dt=_make_aware_start(start_parsed),
        end_dt=_make_aware_end(end_parsed),
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        page=1,
        page_size=max_limit,
        sort_by="entity_amount_desc",
    )

    full_results: list[dict] = data["results"]
    total_count: int = data["pagination"]["total_count"]

    # ── slice into pages and cache each one ────────────────────────
    cached = 0
    for page_num in range(1, math.ceil(len(full_results) / page_size) + 1):
        start_idx = (page_num - 1) * page_size
        page_results = full_results[start_idx : start_idx + page_size]

        page_data = {
            **{k: v for k, v in data.items() if k not in ("results", "pagination")},
            "results": page_results,
            "pagination": {
                "current_page": page_num,
                "total_pages": math.ceil(total_count / page_size) if total_count else 0,
                "total_count": total_count,
                "has_next": (page_num * page_size) < total_count,
                "has_previous": page_num > 1,
                "page_size": page_size,
            },
        }

        cache_key = response_cache.build_key(
            "explore_decisions",
            start_date=start_date_str,
            end_date=end_date_str,
            page=str(page_num),
            page_size=str(page_size),
            sort_by="entity_amount_desc",
            organization_uid="",
            entity_afm="",
            direct_assignments_only="",
        )
        response_cache.set(cache_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

        # ── also cache under the "amount_desc" alias ───────────────
        # The frontend (EntityDetailPage) sends sort_by=amount_desc while
        # the warmup computes with entity_amount_desc.  Both produce
        # identical results (compute_explore_decisions treats any unknown
        # sort_by as entity_amount_desc), so we cache under both keys to
        # avoid a defer_on_miss 202 loop on the frontend's alias.
        alias_key = response_cache.build_key(
            "explore_decisions",
            start_date=start_date_str,
            end_date=end_date_str,
            page=str(page_num),
            page_size=str(page_size),
            sort_by="amount_desc",
            organization_uid="",
            entity_afm="",
            direct_assignments_only="",
        )
        response_cache.set(alias_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)

    # ── always cache at least page 1 (even if empty) so subsequent
    #     requests get cache hits instead of triggering defer_on_miss ─
    if cached == 0:
        empty_data = {
            **{k: v for k, v in data.items() if k not in ("results", "pagination")},
            "results": [],
            "pagination": {
                "current_page": 1,
                "total_pages": 0,
                "total_count": 0,
                "has_next": False,
                "has_previous": False,
                "page_size": page_size,
            },
        }
        empty_key = response_cache.build_key(
            "explore_decisions",
            start_date=start_date_str,
            end_date=end_date_str,
            page="1",
            page_size=str(page_size),
            sort_by="entity_amount_desc",
            organization_uid="",
            entity_afm="",
            direct_assignments_only="",
        )
        response_cache.set(empty_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)

        # Also cache the empty result under the amount_desc alias.
        empty_alias_key = response_cache.build_key(
            "explore_decisions",
            start_date=start_date_str,
            end_date=end_date_str,
            page="1",
            page_size=str(page_size),
            sort_by="amount_desc",
            organization_uid="",
            entity_afm="",
            direct_assignments_only="",
        )
        response_cache.set(empty_alias_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_decisions "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, total_count={total_count})"
    )
