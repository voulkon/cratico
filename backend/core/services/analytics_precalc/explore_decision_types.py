"""
Pre-calculation for explore/decision-types/ endpoint.

Two-layer design:
  compute_explore_decision_types(…)    → pure DB query
  warm_explore_decision_types_window(…) → calls compute + caches
"""

from datetime import date, datetime
from typing import Optional

from django.db import models

from core.models.decisions import Decision

from ._helpers import _make_aware_start, _make_aware_end, _validate_dates, parse_date

__all__ = [
    "compute_explore_decision_types",
    "warm_explore_decision_types_window",
]


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
    from ._warmup import cache_single_key

    _validate_dates(start_date_str, end_date_str, "warm_explore_decision_types_window")

    data = compute_explore_decision_types(
        start_dt=_make_aware_start(parse_date(start_date_str)),
        end_dt=_make_aware_end(parse_date(end_date_str)),
    )

    cache_single_key(
        cache_prefix="explore_decision_types",
        data=data,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        log_label="explore_decision_types",
        log_detail=f"types={data['total_types']}",
    )
