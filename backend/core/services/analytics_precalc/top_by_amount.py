"""
Pre-calculation for decisions/top-by-amount/ endpoint.

Two-layer design:
  compute_top_by_amount(…)    → pure DB query
  warm_top_by_amount_window(…) → calls compute + caches under exact Redis keys
"""

from datetime import date, datetime

from django.db import models
from loguru import logger

from core.models.decisions import Decision
from core.services.decision_projections import paginate_decisions

from ._helpers import _make_aware_start, _make_aware_end, parse_date, response_cache

__all__ = [
    "compute_top_by_amount",
    "warm_top_by_amount_window",
]


def compute_top_by_amount(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 5,
    offset: int = 0,
) -> dict:
    """
    Return the highest-amount decisions (all types) in a date range.

    Single source of truth shared by:
      - top_by_amount_api            (view delegates here on cache miss)
      - warm_top_by_amount_window    (warmup pre-populates cache)

    Returns the same shape as ``paginate_decisions`` so the frontend can
    reuse the same rendering code.
    """
    qs = (
        Decision.objects
        .filter(
            issue_date_day__gte=start_dt,
            issue_date_day__lte=end_dt,
        )
        .annotate(
            calculated_amount=models.Sum("amount_fields__amount"),
        )
        .exclude(calculated_amount__isnull=True)
        .order_by("-calculated_amount")
    )

    return paginate_decisions(
        qs,
        page=(offset // limit) + 1 if limit else 1,
        page_size=limit,
        filters={
            "start_date": start_date_str,
            "end_date": end_date_str,
            "sort_by": "amount_desc",
        },
    )


def warm_top_by_amount_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 5,
) -> None:
    """
    Compute top-by-amount decisions ONCE with a large limit, then slice into
    page_size batches and cache each one under the exact key the frontend
    will request (matching offset + limit).

    Mirrors ``warm_top_payments_window`` / ``warm_explore_orgs_window`` so
    the DecisionsSection can infinite-scroll on cache hits.
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_top_by_amount_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    start_dt = _make_aware_start(start_parsed)
    end_dt = _make_aware_end(end_parsed)

    # ── compute ONCE with the large limit ──────────────────────────
    data = compute_top_by_amount(
        start_dt=start_dt,
        end_dt=end_dt,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        limit=max_limit,
        offset=0,
    )

    full_results: list = data["results"]
    original_pagination: dict = data["pagination"]
    total_count = original_pagination["total_count"]

    # ── slice into pages and cache each one ────────────────────────
    cached = 0
    for offset in range(0, len(full_results), page_size):
        page_results = full_results[offset : offset + page_size]
        if not page_results:
            break

        page = (offset // page_size) + 1
        total_pages = (
            max(1, (total_count + page_size - 1) // page_size) if page_size else 1
        )
        # has_more: more items in cache, OR more items in DB beyond max_limit
        has_next = (
            (offset + page_size < len(full_results))
            or original_pagination["has_next"]
        )

        page_data = {
            "results": page_results,
            "pagination": {
                "current_page": page,
                "total_pages": total_pages,
                "total_count": total_count,
                "has_next": has_next,
                "has_previous": page > 1,
                "page_size": page_size,
            },
            "filters": {
                "start_date": start_date_str,
                "end_date": end_date_str,
                "sort_by": "amount_desc",
            },
        }

        cache_key = response_cache.build_key(
            "top_by_amount",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset=str(offset),
        )
        response_cache.set(cache_key, page_data, end_date=end_date)
        cached += 1

    # ── always cache at least page 1 (even if empty) ───────────────
    if cached == 0:
        empty_data = {
            "results": [],
            "pagination": {
                "current_page": 1,
                "total_pages": 0,
                "total_count": 0,
                "has_next": False,
                "has_previous": False,
                "page_size": page_size,
            },
            "filters": {
                "start_date": start_date_str,
                "end_date": end_date_str,
                "sort_by": "amount_desc",
            },
        }
        empty_key = response_cache.build_key(
            "top_by_amount",
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset="0",
        )
        response_cache.set(empty_key, empty_data, end_date=end_date)
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed top_by_amount "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, total={total_count})"
    )
