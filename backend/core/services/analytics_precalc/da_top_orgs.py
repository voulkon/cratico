"""
Pre-calculation for direct-assignments/top-organizations/ endpoint.

Two-layer design:
  compute_da_top_orgs(…)    → pure DB query
  warm_da_top_orgs_window(…) → calls compute + caches under exact Redis keys
"""

from datetime import date, datetime

from django.db.models import Avg, Count, Max, Min, Sum

from core.models.entities import DecisionEntityRelationship
from core.services.financial_calculation_service import financial_service

from ._helpers import _make_aware_start, _make_aware_end, _validate_dates, parse_date

__all__ = [
    "compute_da_top_orgs",
    "warm_da_top_orgs_window",
]


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
    from ._warmup import cache_paginated_offset

    _validate_dates(start_date_str, end_date_str, "warm_da_top_orgs_window")

    for sort_by in ("amount", "frequency"):
        data = compute_da_top_orgs(
            start_dt=_make_aware_start(parse_date(start_date_str)),
            end_dt=_make_aware_end(parse_date(end_date_str)),
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            limit=max_limit,
            offset=0,
            sort_by=sort_by,
        )

        cache_paginated_offset(
            cache_prefix="da_top_orgs",
            full_results=data["results"],
            total_count=data["pagination"]["total_count"],
            page_size=page_size,
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            end_date=end_date,
            max_limit=max_limit,
            use_historical_ttl=True,
            log_label=f"da_top_orgs sort_by={sort_by}",
            extra_cache_kwargs={"sort_by": sort_by},
            build_page_data=lambda results, offset, page, total_pages: {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": results,
                "pagination": {
                    "limit": page_size,
                    "offset": offset,
                    "total_count": data["pagination"]["total_count"],
                    "has_more": (offset + page_size) < data["pagination"]["total_count"],
                },
                "summary": data["summary"],
            },
            build_empty_data=lambda ps: {
                "metric": data["metric"],
                "sort_by": data["sort_by"],
                "date_range": data["date_range"],
                "results": [],
                "pagination": {
                    "limit": ps,
                    "offset": 0,
                    "total_count": 0,
                    "has_more": False,
                },
                "summary": data["summary"],
            },
        )
