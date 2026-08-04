"""
Pre-calculation for explore/statistics/ endpoint.

Two-layer design:
  compute_explore_statistics(…)    → pure DB query
  warm_explore_statistics_window(…) → calls compute + caches
"""

from datetime import date, datetime
from typing import Optional

from django.db import models

from core.models.decisions import Decision
from core.models.entities import DecisionAmountField

from ._helpers import _make_aware_start, _make_aware_end, _validate_dates, parse_date

__all__ = [
    "compute_explore_statistics",
    "warm_explore_statistics_window",
]


def compute_explore_statistics(
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    start_date_str: str,
    end_date_str: str,
) -> dict:
    """
    Run the explore statistics DB query and return the response dict.

    Only computes the fields actually consumed by the frontend StatisticsGrid:
    total_count, primary_amount, avg_amount, organizations_count, period.

    Single source of truth shared by:
      - explore_statistics_api_dev       (view delegates here on cache miss)
      - warm_explore_statistics_window   (warmup pre-populates cache)

    Args:
        start_dt, end_dt: Timezone-aware datetimes (or None) for date filter.
        start_date_str, end_date_str: Original string form for response.
    """
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
    )

    organizations_count = filtered_qs.values("organization").distinct().count()

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
            },
            "financial": {
                "primary_amount": float(accurate_total),
                "has_discrepancy": False,
                "discrepancy_percentage": 0,
            },
            "organizations_count": organizations_count,
            "status_breakdown": {},
        },
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
    from ._warmup import cache_single_key

    _validate_dates(start_date_str, end_date_str, "warm_explore_statistics_window")

    data = compute_explore_statistics(
        start_dt=_make_aware_start(parse_date(start_date_str)),
        end_dt=_make_aware_end(parse_date(end_date_str)),
        start_date_str=start_date_str,
        end_date_str=end_date_str,
    )

    cache_single_key(
        cache_prefix="explore_statistics",
        data=data,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        log_label="explore_statistics",
        log_detail=f"decisions={data['summary']['decisions']['total_count']}",
    )
