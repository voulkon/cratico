"""
Pre-calculation for explore/organizations/ endpoint.

Two-layer design:
  compute_explore_orgs(…)    → pure DB query
  warm_explore_orgs_window(…) → calls compute + caches under exact Redis keys
"""

from datetime import date

from django.db import models

from core.services.decision_facets import effective_amount_max, effective_amount_sum

from ._helpers import _make_aware_start, _make_aware_end, _validate_dates, parse_date

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
            total_amount=effective_amount_sum(
                filter=models.Q(amount_fields__associated_relationship__isnull=False),
            ),
            max_amount=effective_amount_max(),
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
    from ._warmup import cache_paginated_offset

    data = compute_explore_orgs(start_date_str, end_date_str, limit=max_limit)

    cache_paginated_offset(
        cache_prefix="explore_orgs",
        full_results=data["organizations"],
        total_count=len(data["organizations"]),
        page_size=page_size,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        max_limit=max_limit,
        use_historical_ttl=True,
        log_label="explore_orgs",
        # explore_orgs uses "organizations" not "results" and has no pagination section.
        build_page_data=lambda results, offset, page, total_pages: {
            "organizations": results,
            "total_organizations": len(results),
            "has_more": (offset + page_size < len(data["organizations"]))
            or data["has_more"],
            "offset": offset,
            "limit": page_size,
        },
        build_empty_data=lambda ps: {
            "organizations": [],
            "total_organizations": 0,
            "has_more": False,
            "offset": 0,
            "limit": ps,
        },
    )
