"""
Pre-calculation warmup for the unified endpoint (/api/decisions/unified/).

Warms the temporal-source projections (date_range, statistics, decision_types)
that the unified endpoint caches via @cached_view.
"""

from datetime import date

from loguru import logger

from core.models.decisions import Decision
from core.services.decision_projections import (
    aggregate_decision_types,
    compute_date_range,
    compute_statistics,
)

from ._helpers import _make_aware_start, _make_aware_end, parse_date, response_cache

__all__ = ["warm_unified_window"]


def warm_unified_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
) -> None:
    """
    Pre-populate unified endpoint cache keys for all cacheable views
    (``date_range``, ``statistics``, ``decision_types``) for
    ``source=temporal``.

    The unified endpoint (``/api/decisions/unified/``) caches temporal-source
    projections with ``@cached_view(cache_prefix="unified", ...)``.  This
    warmup ensures that the frontend's explore-date-range, explore-statistics,
    and explore-decision-types calls hit Redis instead of running heavy DB
    aggregations on the first user request.

    Cache keys built::

        unified:source=temporal:view=date_range:start_date=…:end_date=…
        unified:source=temporal:view=statistics:start_date=…:end_date=…
        unified:source=temporal:view=decision_types:start_date=…:end_date=…
    """
    start_parsed = parse_date(start_date_str)
    end_parsed = parse_date(end_date_str)
    if not start_parsed or not end_parsed:
        raise ValueError(
            f"warm_unified_window: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )

    start_dt = _make_aware_start(start_parsed)
    end_dt = _make_aware_end(end_parsed)

    qs = Decision.objects.filter_by_date_range(start_dt, end_dt)

    projections = [
        ("date_range", lambda: compute_date_range(qs)),
        ("statistics", lambda: compute_statistics(qs, start_date_str, end_date_str)),
        ("decision_types", lambda: aggregate_decision_types(qs)),
    ]

    for view_name, compute_fn in projections:
        data = compute_fn()
        cache_key = response_cache.build_key(
            "unified",
            source="temporal",
            view=view_name,
            start_date=start_date_str,
            end_date=end_date_str,
        )
        response_cache.set(cache_key, data, end_date=end_date)

    logger.info(
        f"[AnalyticsPrecalc] Warmed unified endpoint "
        f"[{start_date_str} → {end_date_str}] "
        f"(views: date_range, statistics, decision_types)"
    )
