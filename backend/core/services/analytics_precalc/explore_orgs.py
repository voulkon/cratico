"""
Pre-calculation for explore/organizations/ endpoint.

Two-layer design:
  compute_explore_orgs(…)    → pure DB query
  warm_explore_orgs_window(…) → calls compute + caches under exact Redis keys
"""

from datetime import date

from django.db import models
from loguru import logger

from ._helpers import _make_aware_start, _make_aware_end, parse_date, response_cache

__all__ = [
    "compute_explore_orgs",
    "warm_explore_orgs_window",
]


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
