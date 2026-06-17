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
    """
    from core.models.decisions import Decision  # avoid circular import at module level

    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)

    decisions_qs = Decision.objects.all()
    if start_parsed:
        decisions_qs = decisions_qs.filter(issue_date_day__gte=_make_aware_start(start_parsed))
    if end_parsed:
        decisions_qs = decisions_qs.filter(issue_date_day__lte=_make_aware_end(end_parsed))

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
        .order_by("-count")[:limit]
    )

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
    }


def warm_explore_orgs_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    limit: int = 6,
) -> None:
    """
    Compute and cache explore-orgs data for one time window.

    Args:
        start_date_str: ISO date string used verbatim in the cache key
        end_date_str:   ISO date string used verbatim in the cache key
        end_date:       Python date for smart TTL selection (historical vs current)
        limit:          Must match what the frontend sends (homepage sends limit=6)
    """
    data = compute_explore_orgs(start_date_str, end_date_str, limit)
    cache_key = response_cache.build_key(
        "explore_orgs",
        start_date=start_date_str,
        end_date=end_date_str,
        limit=str(limit),
    )
    response_cache.set(cache_key, data, end_date=end_date)
    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_orgs "
        f"[{start_date_str} → {end_date_str}] key={cache_key}"
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
        response_cache.set(cache_key, page_data, end_date=end_date)
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
    max_limit: int = 100,
    page_size: int = 20,
) -> None:
    """
    Compute explore-decisions ONCE with a large page size, then cache
    page 1 under the exact key the frontend will request.

    The most common homepage request is page 1 with the default sort
    and no filters.  We warm that single page so the first real user
    request is always a cache hit.

    Args:
        start_date_str: ISO date string used verbatim in the cache key
        end_date_str:   ISO date string used verbatim in the cache key
        end_date:       Python date for smart TTL selection
        max_limit:      How many decisions to pre-compute (page_size)
        page_size:      Frontend's page size — must match the default
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_explore_decisions_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    data = compute_explore_decisions(
        start_dt=_make_aware_start(start_parsed),
        end_dt=_make_aware_end(end_parsed),
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        page=1,
        page_size=page_size,
        sort_by="entity_amount_desc",
    )

    cache_key = response_cache.build_key(
        "explore_decisions",
        start_date=start_date_str,
        end_date=end_date_str,
        page="1",
        page_size=str(page_size),
        sort_by="entity_amount_desc",
        organization_uid="",
        entity_afm="",
        direct_assignments_only="False",
    )
    response_cache.set(cache_key, data, end_date=end_date)

    logger.info(
        f"[AnalyticsPrecalc] Warmed explore_decisions "
        f"[{start_date_str} → {end_date_str}] page_size={page_size} "
        f"key={cache_key}"
    )
