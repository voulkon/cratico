"""
Pre-calculation for the "banded direct assignment" leaderboards.

Two symmetric endpoints over the SAME population:

  decisions/top-banded-da-receivers/
    Entities that RECEIVED the most direct assignments whose total linked
    money-received amount falls in the €30k–€38k band, ranked by how many
    such assignments they received (most frequent first).

  decisions/top-banded-da-givers/
    Organizations that ISSUED the most of those same banded direct
    assignments, ranked by how many they issued (most frequent first).

Why this band
─────────────
€30k–€38k sits just below the EU direct-award threshold regime and is a
classic "split-to-avoid-tender" fingerprint: a lot of near-identical,
just-under-threshold assignments to the same recipient is a signal worth
surfacing.  These leaderboards make that pattern visible from both sides
(who receives repeatedly, who issues repeatedly).

Band semantics
──────────────
The band is evaluated **per decision**: the sum of a decision's linked,
money-received amount fields (``COALESCE(verified_amount, amount)``, KAE /
non-monetary rows excluded, same facet layer as ``da_top_entities``) must
fall in ``[BAND_MIN, BAND_MAX]``.  A decision either qualifies as a whole
or not at all — individual amount fields are never banded on their own.

Two-layer design (same as every other pre-calc module):
  compute_top_banded_da_receivers(…) / compute_top_banded_da_givers(…)  → pure DB query
  warm_top_banded_da_receivers_window(…) / warm_top_banded_da_givers_window(…) → compute + cache
"""

from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from django.db import models
from django.db.models import Count

from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship
from core.services.decision_facets import (
    effective_amount_sum,
    effective_linked_amount_avg,
    effective_linked_amount_max,
    effective_linked_amount_min,
    effective_linked_amount_sum,
)
from core.services.financial_calculation_service import financial_service

from ._helpers import _make_aware_end, _make_aware_start, _validate_dates, parse_date

__all__ = [
    "BAND_MIN",
    "BAND_MAX",
    "in_band",
    "compute_top_banded_da_receivers",
    "compute_top_banded_da_givers",
    "warm_top_banded_da_receivers_window",
    "warm_top_banded_da_givers_window",
]

# ---------------------------------------------------------------------------
# Band definition
# ---------------------------------------------------------------------------
# Inclusive bounds, in euros.  Kept as Decimal so every comparison and cache
# payload stays exact (no float rounding at the 30 000 / 38 000 boundaries).
BAND_MIN = Decimal("30000")
BAND_MAX = Decimal("38000")

_CENT = Decimal("0.01")


def _to_decimal(value) -> Decimal | None:
    """Coerce a DB/JSON numeric into an exact 2-dp Decimal (or None)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value.quantize(_CENT, rounding=ROUND_HALF_UP)
    try:
        return Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    except (ArithmeticError, TypeError, ValueError):
        return None


def in_band(value) -> bool:
    """
    True when ``value`` (a per-decision linked, money-received amount sum)
    falls inside the inclusive €30k–€38k band.

    Kept as a plain Python predicate for readability/tests; the SQL path uses
    the equivalent ``_band_total__gte/__lte`` range filter.
    """
    amount = _to_decimal(value)
    if amount is None:
        return False
    return BAND_MIN <= amount <= BAND_MAX


# ---------------------------------------------------------------------------
# Shared query builder — the banded-decision population
# ---------------------------------------------------------------------------

def _banded_decisions(start_dt: datetime, end_dt: datetime):
    """
    Return a ``Decision`` queryset of every direct assignment in the date
    range whose *total* linked money-received amount lands in the band.

    The band total is computed with the same facet expression used by every
    other direct-assignment aggregation (verified-aware, non-monetary rows
    excluded), restricted to money-received relationship roles.
    """
    roles = financial_service.MONEY_RECEIVED_ROLES

    band_filter = models.Q(amount_fields__associated_relationship__isnull=False) & models.Q(
        amount_fields__associated_relationship__role__in=roles
    )

    return (
        Decision.objects
        .filter(
            issue_date_day__gte=start_dt,
            issue_date_day__lte=end_dt,
            classification__is_direct_assignment=True,
        )
        .annotate(band_total=effective_amount_sum(filter=band_filter))
        .filter(band_total__gte=BAND_MIN, band_total__lte=BAND_MAX)
        .values("pk")
    )


def _band_meta() -> dict:
    """Serialisable description of the band, echoed in every response."""
    return {
        "min": str(BAND_MIN),
        "max": str(BAND_MAX),
        "currency": "EUR",
    }


# ---------------------------------------------------------------------------
# Metric 1 — receivers (entities), ranked by frequency
# ---------------------------------------------------------------------------

def compute_top_banded_da_receivers(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """
    Entities that received the most €30k–€38k direct assignments.

    Single source of truth shared by:
      - top_banded_da_receivers_api            (view delegates here on cache miss)
      - warm_top_banded_da_receivers_window    (warmup pre-populates cache)

    Ranked by ``decision_count`` desc, then ``banded_amount_sum`` desc.
    """
    roles = financial_service.MONEY_RECEIVED_ROLES
    banded = _banded_decisions(start_dt, end_dt)

    base_filter = dict(decision__in=banded, role__in=roles)

    results = list(
        DecisionEntityRelationship.objects.filter(**base_filter)
        .values("entity__afm", "entity__name", "entity__entity_type")
        .annotate(
            decision_count=Count("decision", distinct=True),
            organization_count=Count("decision__organization", distinct=True),
            banded_amount_sum=effective_linked_amount_sum(),
            avg_amount=effective_linked_amount_avg(),
            max_amount=effective_linked_amount_max(),
            min_amount=effective_linked_amount_min(),
        )
        .filter(banded_amount_sum__gt=0)
        .order_by("-decision_count", "-banded_amount_sum", "entity__afm")[offset : offset + limit]
    )

    combined_stats = DecisionEntityRelationship.objects.filter(**base_filter).aggregate(
        unique_entities=Count("entity", distinct=True),
        unique_organizations=Count("decision__organization", distinct=True),
        total_decisions=Count("decision", distinct=True),
        total_amount=effective_linked_amount_sum(),
    )
    total_count = combined_stats["unique_entities"] or 0

    formatted_results = [
        {
            "rank": offset + i + 1,
            "entity_afm": r["entity__afm"],
            "entity_name": r["entity__name"],
            "entity_type": r["entity__entity_type"],
            "decision_count": r["decision_count"],
            "organization_count": r["organization_count"],
            "banded_amount_sum": str(r["banded_amount_sum"]) if r["banded_amount_sum"] else "0",
            "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
            "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
            "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
        }
        for i, r in enumerate(results)
    ]

    return {
        "metric": "Most €30k–€38k Direct Assignments Received",
        "band": _band_meta(),
        "date_range": {"start": start_date_str, "end": end_date_str},
        "results": formatted_results,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "summary": {
            "total_banded_amount": str(combined_stats["total_amount"] or 0),
            "total_banded_assignments": combined_stats["total_decisions"] or 0,
            "unique_entities": combined_stats["unique_entities"] or 0,
            "unique_organizations": combined_stats["unique_organizations"] or 0,
        },
    }


# ---------------------------------------------------------------------------
# Metric 2 — givers (organizations), ranked by frequency (the mirror)
# ---------------------------------------------------------------------------

def compute_top_banded_da_givers(
    start_dt: datetime,
    end_dt: datetime,
    start_date_str: str,
    end_date_str: str,
    limit: int = 20,
    offset: int = 0,
) -> dict:
    """
    Organizations that issued the most €30k–€38k direct assignments.

    Mirror of :func:`compute_top_banded_da_receivers` — same population, same
    band, but grouped by the issuing organization instead of the recipient
    entity.  Ranked by ``decision_count`` desc, then ``banded_amount_sum`` desc.

    Single source of truth shared by:
      - top_banded_da_givers_api            (view delegates here on cache miss)
      - warm_top_banded_da_givers_window    (warmup pre-populates cache)
    """
    roles = financial_service.MONEY_RECEIVED_ROLES
    banded = _banded_decisions(start_dt, end_dt)

    base_filter = dict(decision__in=banded, role__in=roles)

    results = list(
        DecisionEntityRelationship.objects.filter(**base_filter)
        .values("decision__organization__uid", "decision__organization__label")
        .annotate(
            decision_count=Count("decision", distinct=True),
            entity_count=Count("entity", distinct=True),
            banded_amount_sum=effective_linked_amount_sum(),
            avg_amount=effective_linked_amount_avg(),
            max_amount=effective_linked_amount_max(),
            min_amount=effective_linked_amount_min(),
        )
        .filter(banded_amount_sum__gt=0)
        .order_by(
            "-decision_count",
            "-banded_amount_sum",
            "decision__organization__uid",
        )[offset : offset + limit]
    )

    combined_stats = DecisionEntityRelationship.objects.filter(**base_filter).aggregate(
        unique_organizations=Count("decision__organization", distinct=True),
        unique_entities=Count("entity", distinct=True),
        total_decisions=Count("decision", distinct=True),
        total_amount=effective_linked_amount_sum(),
    )
    total_count = combined_stats["unique_organizations"] or 0

    formatted_results = [
        {
            "rank": offset + i + 1,
            "organization_uid": r["decision__organization__uid"],
            "organization_label": r["decision__organization__label"],
            "decision_count": r["decision_count"],
            "entity_count": r["entity_count"],
            "banded_amount_sum": str(r["banded_amount_sum"]) if r["banded_amount_sum"] else "0",
            "avg_amount": str(r["avg_amount"]) if r["avg_amount"] else "0",
            "max_amount": str(r["max_amount"]) if r["max_amount"] else "0",
            "min_amount": str(r["min_amount"]) if r["min_amount"] else "0",
        }
        for i, r in enumerate(results)
    ]

    return {
        "metric": "Most €30k–€38k Direct Assignments Issued",
        "band": _band_meta(),
        "date_range": {"start": start_date_str, "end": end_date_str},
        "results": formatted_results,
        "pagination": {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + limit < total_count,
        },
        "summary": {
            "total_banded_amount": str(combined_stats["total_amount"] or 0),
            "total_banded_assignments": combined_stats["total_decisions"] or 0,
            "unique_organizations": combined_stats["unique_organizations"] or 0,
            "unique_entities": combined_stats["unique_entities"] or 0,
        },
    }


# ---------------------------------------------------------------------------
# Cache warmup
# ---------------------------------------------------------------------------

def _warm_banded_window(
    *,
    cache_prefix: str,
    compute_fn,
    label: str,
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 5,
) -> None:
    """
    Shared body for both banded warmups: compute ONCE with a large limit,
    then slice into page_size batches cached under the exact keys the
    frontend will request (offset + limit).

    Mirrors ``warm_da_top_entities_window`` — same slicing helper, same
    historical TTL (these are date-windowed, non-real-time views).
    """
    from ._warmup import cache_paginated_offset

    _validate_dates(start_date_str, end_date_str, label)

    compute_kwargs = dict(
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        limit=max_limit,
        offset=0,
    )

    result = compute_fn(
        start_dt=_make_aware_start(parse_date(start_date_str)),
        end_dt=_make_aware_end(parse_date(end_date_str)),
        **compute_kwargs,
    )
    total_count = result["pagination"]["total_count"]

    def build_page_data(results, offset, page, total_pages):
        return {
            "metric": result["metric"],
            "band": result["band"],
            "date_range": result["date_range"],
            "results": results,
            "pagination": {
                "limit": page_size,
                "offset": offset,
                "total_count": total_count,
                "has_more": (offset + page_size) < total_count,
            },
            "summary": result["summary"],
        }

    def build_empty_data(ps):
        return {
            "metric": result["metric"],
            "band": result["band"],
            "date_range": result["date_range"],
            "results": [],
            "pagination": {
                "limit": ps,
                "offset": 0,
                "total_count": 0,
                "has_more": False,
            },
            "summary": result["summary"],
        }

    cache_paginated_offset(
        cache_prefix=cache_prefix,
        full_results=result["results"],
        total_count=total_count,
        page_size=page_size,
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        max_limit=max_limit,
        use_historical_ttl=True,
        log_label=label,
        build_page_data=build_page_data,
        build_empty_data=build_empty_data,
    )


def warm_top_banded_da_receivers_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 5,
) -> None:
    """Warm cached pages for ``top_banded_da_receivers``."""
    _warm_banded_window(
        cache_prefix="top_banded_da_receivers",
        compute_fn=compute_top_banded_da_receivers,
        label="top_banded_da_receivers",
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        max_limit=max_limit,
        page_size=page_size,
    )


def warm_top_banded_da_givers_window(
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    max_limit: int = 100,
    page_size: int = 5,
) -> None:
    """Warm cached pages for ``top_banded_da_givers``."""
    _warm_banded_window(
        cache_prefix="top_banded_da_givers",
        compute_fn=compute_top_banded_da_givers,
        label="top_banded_da_givers",
        start_date_str=start_date_str,
        end_date_str=end_date_str,
        end_date=end_date,
        max_limit=max_limit,
        page_size=page_size,
    )
