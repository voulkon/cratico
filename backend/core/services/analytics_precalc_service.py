"""
Analytics Pre-Calculation Service

Two-layer design for each covered view:

  compute_*(...)  → pure DB query; returns the same response dict the view
                    would return.  Called by both the view (on cache miss) and
                    the warmup task (to pre-populate).  Single source of truth.

  warm_*_window(...)  → calls compute_* then stores the result under the EXACT
                        Redis key that cached_view would look up for that window.

Adding a new view
─────────────────
1. Add compute_<name>(...)  →  dict
2. Add warm_<name>_window(...)  →  None
3. Register in warm_analytics_cache's view loop (tasks_post_import.py)

Views covered
─────────────
  explore_organizations_api_dev          cache_prefix="explore_orgs"
  direct_assignment_top_pairs_global     cache_prefix="da_top_pairs"
  explore_decisions_optimized_api        cache_prefix="explore_decisions"
"""

from datetime import date, datetime
from typing import Optional, List

from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date

from core.services.response_cache_service import response_cache
from loguru import logger


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_aware_start(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _make_aware_end(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.max.time()))


# ---------------------------------------------------------------------------
# explore_orgs  (explore/organizations/)
# ---------------------------------------------------------------------------

def compute_explore_orgs(
    start_date_str: str,
    end_date_str: str,
    limit: int = 6,
    offset: int = 0,
) -> dict:
    """
    Run the explore-organizations DB query and return the response dict.

    Single source of truth shared by:
      - explore_organizations_api_dev (view delegates here on cache miss)
      - warm_explore_orgs_window      (warmup pre-populates cache)

    Args:
        start_date_str: ISO date string "YYYY-MM-DD"
        end_date_str:   ISO date string "YYYY-MM-DD"
        limit:          Max number of orgs to return
        offset:         Number of orgs to skip (for infinite-scroll pagination)
    """
    from core.models.decisions import Decision  # avoid circular import at module level

    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)

    decisions_qs = Decision.objects.all()
    if start_parsed:
        decisions_qs = decisions_qs.filter(issue_date_day__gte=_make_aware_start(start_parsed))
    if end_parsed:
        decisions_qs = decisions_qs.filter(issue_date_day__lte=_make_aware_end(end_parsed))

    # Fetch limit+1 to detect has_more for infinite scroll
    organizations = (
        decisions_qs.values("organization__uid", "organization__label")
        .annotate(
            count=models.Count("id", distinct=True),
            total_amount=models.Sum(
                "amount_fields__amount",
                filter=models.Q(amount_fields__associated_relationship__isnull=False),
            ),
            max_amount=models.Max("amount"),
        )
        .filter(organization__uid__isnull=False)
        .order_by("-count")[offset : offset + limit + 1]
    )

    has_more = len(organizations) > limit
    if has_more:
        organizations = organizations[:limit]

    formatted = []
    for org in organizations:
        count = org["count"]
        total = float(org["total_amount"] or 0)
        formatted.append(
            {
                "uid": org["organization__uid"],
                "label": org["organization__label"],
                "count": count,
                "total_amount": total,
                "avg_amount": total / count if count > 0 else 0,
                "max_amount": float(org["max_amount"] or 0),
            }
        )

    return {
        "organizations": formatted,
        "total_organizations": len(formatted),
        "has_more": has_more,
        "offset": offset,
        "limit": limit,
    }


def warm_explore_orgs_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 200,
    page_size: int = 6,
) -> None:
    """
    Compute explore-orgs ONCE with a large limit, then slice into
    page_size batches and cache each one under the exact key the
    frontend will request (matching offset + limit).

    Why: the cache key includes both ``limit`` and ``offset``, so a
    single ``limit=200`` cache entry would never satisfy a frontend
    request for ``limit=6&offset=12``.  By pre-slicing we cover every
    paginated request the frontend makes while infinite-scrolling —
    without re-running the heavy DB query.

    Args:
        start_date_str: ISO date string used verbatim in the cache key
        end_date_str:   ISO date string used verbatim in the cache key
        end_date:       Python date for smart TTL selection (historical vs current)
        max_limit:      How many orgs to pre-compute in one query
        page_size:      Frontend's page size — must match what the
                        OrganizationsSection sends (homepage sends limit=6)
    """
    # ── compute ONCE with the large limit ──────────────────────────
    data = compute_explore_orgs(start_date_str, end_date_str, limit=max_limit)

    full_results: list[dict] = data["organizations"]
    original_has_more: bool = data["has_more"]

    # ── slice into pages and cache each one ────────────────────────
    cached = 0
    for offset in range(0, len(full_results), page_size):
        page_results = full_results[offset : offset + page_size]
        if not page_results:
            break

        # has_more: more items in cache, OR more items in DB beyond max_limit
        has_more = (offset + page_size < len(full_results)) or original_has_more

        page_data = {
            "organizations": page_results,
            "total_organizations": len(page_results),
            "has_more": has_more,
            "offset": offset,
            "limit": page_size,
        }

        cache_key = response_cache.build_key(
            "explore_orgs",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset=str(offset),
        )
        response_cache.set(cache_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

    # ── always cache at least page 1 (even if empty) so subsequent
    #     requests get cache hits instead of triggering defer_on_miss ─
    if cached == 0:
        empty_data = {
            "organizations": [],
            "total_organizations": 0,
            "has_more": False,
            "offset": 0,
            "limit": page_size,
        }
        empty_key = response_cache.build_key(
            "explore_orgs",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset="0",
        )
        response_cache.set(empty_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_orgs "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, "
        f"orgs_cached={len(full_results)})"
    )


# ---------------------------------------------------------------------------
# da_top_pairs  (direct-assignments/top-pairs/)
# ---------------------------------------------------------------------------

def compute_da_top_pairs(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """
    Run the direct-assignment top org-entity pairs DB query and return the
    response dict.

    Single source of truth shared by:
      - direct_assignment_top_pairs_global  (view delegates here on cache miss)
      - warm_da_top_pairs_window            (warmup pre-populates cache)

    Args:
        start_dt:       Timezone-aware datetime for the DB filter
        end_dt:         Timezone-aware datetime for the DB filter
        start_date_str: Original string form — stored verbatim in the response
                        and used as part of the cache key
        end_date_str:   Original string form — same as above
        limit:          Page size
        offset:         Page offset
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    from core.models.entities import DecisionEntityRelationship
    from core.services.financial_calculation_service import financial_service

    roles = financial_service.MONEY_RECEIVED_ROLES

    base_filter = dict(
        decision__issue_date_day__gte=start_dt,
        decision__issue_date_day__lte=end_dt,
        decision__classification__is_direct_assignment=True,
        role__in=roles,
    )

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

    combined_stats = DecisionEntityRelationship.objects.filter(**base_filter).aggregate(
        unique_org_entity_pairs=Count("id", distinct=True),
        total_amount=Sum("linked_amounts__amount"),
        total_decisions=Count("decision", distinct=True),
        unique_organizations=Count("decision__organization", distinct=True),
        unique_entities=Count("entity", distinct=True),
    )
    total_count = combined_stats["unique_org_entity_pairs"] or 0

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

    return {
        "date_range": {"start": start_date_str, "end": end_date_str},
        "results": formatted_results,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "summary": {
            "total_direct_assignment_amount": str(combined_stats["total_amount"] or 0),
            "total_direct_assignments": combined_stats["total_decisions"] or 0,
            "unique_organizations": combined_stats["unique_organizations"] or 0,
            "unique_entities": combined_stats["unique_entities"] or 0,
        },
    }


def warm_da_top_pairs_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 50,
    page_size: int = 6,
) -> None:
    """
    Compute da-top-pairs ONCE with a large limit, then slice into
    page_size batches and cache each one under the exact key the
    frontend will request (matching offset + limit).

    Why: the cache key includes both ``limit`` and ``offset``, so a
    single ``limit=50`` cache entry would never satisfy a frontend
    request for ``limit=6&offset=12``.  By pre-slicing we cover every
    paginated request the frontend makes while scrolling — without
    re-running the heavy DB query.

    Note: the view uses parse_datetime() which rejects "YYYY-MM-DD" strings,
    but the frontend sends exactly that format.  By pre-populating with the
    "YYYY-MM-DD" key, the cache decorator serves the warmed data before the
    view's date-validation logic ever runs.

    Args:
        start_date_str: ISO date string used verbatim in the cache key
        end_date_str:   ISO date string used verbatim in the cache key
        end_date:       Python date for smart TTL selection
        max_limit:      How many top pairs to pre-compute (default 50)
        page_size:      Frontend's page size — must match TopRelationshipPairs.limit
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_da_top_pairs_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    # ── compute ONCE with the large limit ──────────────────────────
    data = compute_da_top_pairs(
        start_dt=_make_aware_start(start_parsed),
        end_dt=_make_aware_end(end_parsed),
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        limit=max_limit,
        offset=0,
    )

    full_results: list[dict] = data["results"]
    total_count: int = data["pagination"]["total_count"]
    summary: dict = data["summary"]

    # ── slice into pages and cache each one ────────────────────────
    cached = 0
    for offset in range(0, len(full_results), page_size):
        page_results = full_results[offset : offset + page_size]

        page_data = {
            "date_range": data["date_range"],
            "results": page_results,
            "pagination": {
                "limit": page_size,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + page_size) < total_count,
            },
            "summary": summary,
        }

        cache_key = response_cache.build_key(
            "da_top_pairs",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset=str(offset),
        )
        response_cache.set(cache_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

    # ── always cache at least page 1 (even if empty) so subsequent
    #     requests get cache hits instead of triggering defer_on_miss ─
    if cached == 0:
        empty_data = {
            "date_range": data["date_range"],
            "results": [],
            "pagination": {
                "limit": page_size,
                "offset": 0,
                "total_count": 0,
                "has_more": False,
            },
            "summary": summary,
        }
        empty_key = response_cache.build_key(
            "da_top_pairs",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset="0",
        )
        response_cache.set(empty_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed da_top_pairs "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, total_count={total_count})"
    )


# ---------------------------------------------------------------------------
# explore_decisions  (explore/decisions/)
# ---------------------------------------------------------------------------

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
    from django.core.paginator import Paginator
    from django.db.models import (
        Case, Count, DecimalField, OuterRef, Q, Subquery, Sum, When, F,
    )

    from core.models.decisions import Decision
    from core.models.entities import DecisionEntityRelationship
    from core.services.feature_flag_service import feature_flags
    from api.views.search.base import serialize_decision_with_entities

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
        .annotate(total=Sum("linked_amounts__amount"))
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
        .annotate(total_amount=Sum("linked_amounts__amount"))
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
    import math

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
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_decisions "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, total_count={total_count})"
    )


# ---------------------------------------------------------------------------
# da_top_entities  (direct-assignments/top-entities/)
# ---------------------------------------------------------------------------

def compute_da_top_entities(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "amount",
) -> dict:
    """
    Run the direct-assignment top entities DB query and return the response dict.

    Single source of truth shared by:
      - direct_assignment_top_entities_global  (view delegates here on cache miss)
      - warm_da_top_entities_window            (warmup pre-populates cache)

    Args:
        start_dt, end_dt: Timezone-aware datetimes for the DB filter.
        start_date_str, end_date_str: Original string form for response + cache key.
        limit: Page size.
        offset: Page offset.
        sort_by: "amount" or "frequency".
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    from core.models.entities import DecisionEntityRelationship
    from core.services.financial_calculation_service import financial_service

    roles = financial_service.MONEY_RECEIVED_ROLES

    base_filter = dict(
        decision__issue_date_day__gte=start_dt,
        decision__issue_date_day__lte=end_dt,
        decision__classification__is_direct_assignment=True,
        role__in=roles,
    )

    if sort_by == "frequency":
        order_by = "-decision_count"
        metric_label = "Most Direct Assignments Received"
    else:
        order_by = "-total_amount"
        metric_label = "Highest Direct Assignment Revenue"

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

    combined_stats = DecisionEntityRelationship.objects.filter(**base_filter).aggregate(
        unique_entities=Count("entity", distinct=True),
        total_amount=Sum("linked_amounts__amount"),
        total_decisions=Count("decision", distinct=True),
        unique_organizations=Count("decision__organization", distinct=True),
    )
    total_count = combined_stats["unique_entities"] or 0

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

    return {
        "metric": metric_label,
        "sort_by": sort_by,
        "date_range": {"start": start_date_str, "end": end_date_str},
        "results": formatted_results,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "summary": {
            "total_direct_assignment_amount": str(combined_stats["total_amount"] or 0),
            "total_direct_assignments": combined_stats["total_decisions"] or 0,
            "unique_entities": combined_stats["unique_entities"] or 0,
            "unique_organizations": combined_stats["unique_organizations"] or 0,
        },
    }


def warm_da_top_entities_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 20,
) -> None:
    """
    Compute da-top-entities ONCE with a large limit, then slice into
    page_size batches and cache each one under the exact key the
    frontend will request.

    Uses the SAME key format as @cached_view(cache_prefix="da_top_entities",
    cache_params=["start_date", "end_date", "limit", "offset", "sort_by"]).
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_da_top_entities_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    for sort_by in ("amount", "frequency"):
        data = compute_da_top_entities(
            start_dt=_make_aware_start(start_parsed),
            end_dt=_make_aware_end(end_parsed),
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            limit=max_limit,
            offset=0,
            sort_by=sort_by,
        )

        full_results: list[dict] = data["results"]
        total_count: int = data["pagination"]["total_count"]
        summary: dict = data["summary"]

        cached = 0
        for offset in range(0, len(full_results), page_size):
            page_results = full_results[offset : offset + page_size]

            page_data = {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": page_results,
                "pagination": {
                    "limit": page_size,
                    "offset": offset,
                    "total_count": total_count,
                    "has_more": (offset + page_size) < total_count,
                },
                "summary": summary,
            }

            cache_key = response_cache.build_key(
                "da_top_entities",
                end_date=end_date_str,
                limit=str(page_size),
                offset=str(offset),
                sort_by=sort_by,
                start_date=start_date_str,
            )
            response_cache.set(cache_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
            cached += 1

        # ── always cache at least page 1 (even if empty) so subsequent
        #     requests get cache hits instead of triggering defer_on_miss ─
        if cached == 0:
            empty_data = {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": [],
                "pagination": {
                    "limit": page_size,
                    "offset": 0,
                    "total_count": 0,
                    "has_more": False,
                },
                "summary": summary,
            }
            empty_key = response_cache.build_key(
                "da_top_entities",
                end_date=end_date_str,
                limit=str(page_size),
                offset="0",
                sort_by=sort_by,
                start_date=start_date_str,
            )
            response_cache.set(empty_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
            cached += 1

        logger.info(
            f"[AnalyticsPrecalc] Warmed da_top_entities "
            f"[{start_date_str} → {end_date_str}] sort_by={sort_by} "
            f"{cached} pages (max_limit={max_limit}, page_size={page_size}, "
            f"total_count={total_count})"
        )


# ---------------------------------------------------------------------------
# da_top_orgs  (direct-assignments/top-organizations/)
# ---------------------------------------------------------------------------

def compute_da_top_orgs(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "amount",
) -> dict:
    """
    Run the direct-assignment top organizations DB query and return the response dict.

    Single source of truth shared by:
      - direct_assignment_top_organizations_global  (view delegates here on cache miss)
      - warm_da_top_orgs_window                     (warmup pre-populates cache)

    Args:
        start_dt, end_dt: Timezone-aware datetimes for the DB filter.
        start_date_str, end_date_str: Original string form for response + cache key.
        limit: Page size.
        offset: Page offset.
        sort_by: "amount" or "frequency".
    """
    from django.db.models import Avg, Count, Max, Min, Sum

    from core.models.entities import DecisionEntityRelationship
    from core.services.financial_calculation_service import financial_service

    roles = financial_service.MONEY_RECEIVED_ROLES

    base_filter = dict(
        decision__issue_date_day__gte=start_dt,
        decision__issue_date_day__lte=end_dt,
        decision__classification__is_direct_assignment=True,
        role__in=roles,
    )

    if sort_by == "frequency":
        order_by = "-decision_count"
        metric_label = "Most Direct Assignments Issued"
    else:
        order_by = "-total_amount"
        metric_label = "Highest Direct Assignment Spending"

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

    combined_stats = DecisionEntityRelationship.objects.filter(**base_filter).aggregate(
        unique_organizations=Count("decision__organization", distinct=True),
        total_amount=Sum("linked_amounts__amount"),
        total_decisions=Count("decision", distinct=True),
        unique_entities=Count("entity", distinct=True),
    )
    total_count = combined_stats["unique_organizations"] or 0

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

    return {
        "metric": metric_label,
        "sort_by": sort_by,
        "date_range": {"start": start_date_str, "end": end_date_str},
        "results": formatted_results,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "summary": {
            "total_direct_assignment_amount": str(combined_stats["total_amount"] or 0),
            "total_direct_assignments": combined_stats["total_decisions"] or 0,
            "unique_organizations": combined_stats["unique_organizations"] or 0,
            "unique_entities": combined_stats["unique_entities"] or 0,
        },
    }


def warm_da_top_orgs_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 20,
) -> None:
    """
    Compute da-top-orgs ONCE with a large limit, then slice into
    page_size batches and cache each one under the exact key the
    frontend will request.

    Uses the SAME key format as @cached_view(cache_prefix="da_top_orgs",
    cache_params=["start_date", "end_date", "limit", "offset", "sort_by"]).
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_da_top_orgs_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    for sort_by in ("amount", "frequency"):
        data = compute_da_top_orgs(
            start_dt=_make_aware_start(start_parsed),
            end_dt=_make_aware_end(end_parsed),
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            limit=max_limit,
            offset=0,
            sort_by=sort_by,
        )

        full_results: list[dict] = data["results"]
        total_count: int = data["pagination"]["total_count"]
        summary: dict = data["summary"]

        cached = 0
        for offset in range(0, len(full_results), page_size):
            page_results = full_results[offset : offset + page_size]

            page_data = {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": page_results,
                "pagination": {
                    "limit": page_size,
                    "offset": offset,
                    "total_count": total_count,
                    "has_more": (offset + page_size) < total_count,
                },
                "summary": summary,
            }

            cache_key = response_cache.build_key(
                "da_top_orgs",
                end_date=end_date_str,
                limit=str(page_size),
                offset=str(offset),
                sort_by=sort_by,
                start_date=start_date_str,
            )
            response_cache.set(cache_key, page_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
            cached += 1

        # ── always cache at least page 1 (even if empty) so subsequent
        #     requests get cache hits instead of triggering defer_on_miss ─
        if cached == 0:
            empty_data = {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": [],
                "pagination": {
                    "limit": page_size,
                    "offset": 0,
                    "total_count": 0,
                    "has_more": False,
                },
                "summary": summary,
            }
            empty_key = response_cache.build_key(
                "da_top_orgs",
                end_date=end_date_str,
                limit=str(page_size),
                offset="0",
                sort_by=sort_by,
                start_date=start_date_str,
            )
            response_cache.set(empty_key, empty_data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)
            cached += 1

        logger.info(
            f"[AnalyticsPrecalc] Warmed da_top_orgs "
            f"[{start_date_str} → {end_date_str}] sort_by={sort_by} "
            f"{cached} pages (max_limit={max_limit}, page_size={page_size}, "
            f"total_count={total_count})"
        )


# ---------------------------------------------------------------------------
# explore_decision_types  (explore/decision-types/)
# ---------------------------------------------------------------------------

def compute_explore_decision_types(
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> dict:
    """
    Run the explore decision-types DB query and return the response dict.

    Single source of truth shared by:
      - explore_decision_types_api_dev       (view delegates here on cache miss)
      - warm_explore_decision_types_window   (warmup pre-populates cache)

    Args:
        start_dt, end_dt: Timezone-aware datetimes (or None) for date filter.
    """
    from core.models.decisions import Decision

    decisions_qs = Decision.objects.filter_by_date_range(start_dt, end_dt)

    decision_types = (
        decisions_qs.values("decision_type__uid")
        .annotate(
            count=models.Count("id", distinct=True),
            total_amount=models.Sum(
                "amount_fields__amount",
                filter=models.Q(
                    amount_fields__associated_relationship__isnull=False
                ),
            ),
            max_amount=models.Max("amount"),
            label=models.Max("decision_type__label"),
        )
        .filter(decision_type__uid__isnull=False)
        .order_by("-count")
    )

    formatted_types = []
    for dt in decision_types:
        count = dt["count"]
        total = float(dt["total_amount"] or 0)
        formatted_types.append(
            {
                "uid": dt["decision_type__uid"],
                "label": dt["label"],
                "count": count,
                "total_amount": total,
                "avg_amount": total / count if count > 0 else 0,
                "max_amount": float(dt["max_amount"] or 0),
            }
        )

    return {
        "decision_types": formatted_types,
        "total_types": len(formatted_types),
    }


def warm_explore_decision_types_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 200,
    page_size: int = 50,
) -> None:
    """
    Compute explore decision-types ONCE and cache the result.

    This view has no pagination params, so we cache a single key.
    max_limit and page_size are unused but kept for API consistency.
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)

    data = compute_explore_decision_types(
        start_dt=_make_aware_start(start_parsed) if start_parsed else None,
        end_dt=_make_aware_end(end_parsed) if end_parsed else None,
    )

    cache_key = response_cache.build_key(
        "explore_decision_types",
        end_date=end_date_str,
        start_date=start_date_str,
    )
    response_cache.set(cache_key, data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_decision_types "
        f"[{start_date_str} → {end_date_str}] "
        f"(types={data['total_types']})"
    )


# ---------------------------------------------------------------------------
# explore_statistics  (explore/statistics/)
# ---------------------------------------------------------------------------

def compute_explore_statistics(
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    start_date_str: str,
    end_date_str: str,
) -> dict:
    """
    Run the explore statistics DB query and return the response dict.

    This is the most complex view — multiple aggregations:
    monthly breakdown, top types, top orgs, status breakdown, recent decisions,
    and accurate financial totals via DecisionAmountField.

    Single source of truth shared by:
      - explore_statistics_api_dev       (view delegates here on cache miss)
      - warm_explore_statistics_window   (warmup pre-populates cache)

    Args:
        start_dt, end_dt: Timezone-aware datetimes (or None) for date filter.
        start_date_str, end_date_str: Original string form for response.
    """
    from datetime import timedelta

    from core.models.decisions import Decision
    from core.models.entities import DecisionAmountField

    decisions_qs = Decision.objects.all()
    filtered_qs = decisions_qs.filter_by_date_range(start_dt, end_dt)

    # Accurate total via DecisionAmountField scoped to filtered decisions
    accurate_total = (
        DecisionAmountField.objects.filter(
            decision__in=filtered_qs,
            associated_relationship__isnull=False,
        ).aggregate(total=models.Sum("amount"))["total"]
        or 0
    )

    stats = filtered_qs.aggregate(
        total_decisions=models.Count("id"),
        avg_amount=models.Avg("amount"),
        max_amount=models.Max("amount"),
        min_amount=models.Min("amount"),
    )

    organizations_count = filtered_qs.values("organization").distinct().count()

    # Monthly breakdown
    try:
        monthly_stats = (
            filtered_qs.annotate(month=models.F("issue_date_month"))
            .values("month")
            .annotate(
                count=models.Count("id"),
                amount=models.Sum("amount"),
            )
            .order_by("month")
        )
    except Exception:
        monthly_stats = []

    # Top decision types
    top_types = (
        filtered_qs.values("decision_type__label")
        .annotate(
            count=models.Count("id"),
            total_amount=models.Sum("amount"),
        )
        .order_by("-count")[:10]
    )

    # Top organizations
    top_organizations = (
        filtered_qs.values("organization__label", "organization__uid")
        .annotate(
            count=models.Count("id"),
            total_amount=models.Sum("amount"),
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

    return {
        "period": {
            "start_date": start_date_str,
            "end_date": end_date_str,
            "days_count": (
                (end_dt - start_dt).days + 1
                if start_dt and end_dt
                else 0
            ),
        },
        "summary": {
            "decisions": {
                "total_count": stats["total_decisions"] or 0,
                "total_amount": float(accurate_total),
                "avg_amount": float(stats["avg_amount"] or 0),
                "max_amount": float(stats["max_amount"] or 0),
                "min_amount": float(stats["min_amount"] or 0),
            },
            "financial": {
                "primary_amount": float(accurate_total),
                "has_discrepancy": False,
                "discrepancy_percentage": 0,
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


def warm_explore_statistics_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 1,
    page_size: int = 1,
) -> None:
    """
    Compute explore statistics ONCE and cache the result.

    This view has no pagination params, so we cache a single key.
    max_limit and page_size are unused but kept for API consistency.
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)

    data = compute_explore_statistics(
        start_dt=_make_aware_start(start_parsed) if start_parsed else None,
        end_dt=_make_aware_end(end_parsed) if end_parsed else None,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )

    cache_key = response_cache.build_key(
        "explore_statistics",
        end_date=end_date_str,
        start_date=start_date_str,
    )
    response_cache.set(cache_key, data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_statistics "
        f"[{start_date_str} → {end_date_str}] "
        f"(decisions={data['summary']['decisions']['total_count']})"
    )


# ── Warmup registry: view_name → warm_function ──────────────────────────
# Used by warm_single_window for on-demand (defer_on_miss) warmup.
# Each key matches the cache_prefix used in @cached_view.

WARMUP_REGISTRY = {
    "explore_orgs": warm_explore_orgs_window,
    "da_top_pairs": warm_da_top_pairs_window,
    "explore_decisions": warm_explore_decisions_window,
    "da_top_entities": warm_da_top_entities_window,
    "da_top_orgs": warm_da_top_orgs_window,
    "explore_decision_types": warm_explore_decision_types_window,
    "explore_statistics": warm_explore_statistics_window,
}
