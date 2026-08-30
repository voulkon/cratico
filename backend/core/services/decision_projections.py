"""
Shared decision-projection layer.

A "projection" is a way to aggregate / paginate / summarise a Decision
queryset into a response dict.  Every projection function:
  - accepts a filtered, sorted queryset (+ optional extra params)
  - returns a dict suitable for wrapping in a DRF Response

Projections are source-agnostic — the caller is responsible for building
and filtering the queryset.  These functions only care about *what* to
return, not *where* the decisions came from.

Projections:
  - paginate_decisions     → paginated list with entity relationships
  - aggregate_decision_types → unique decision-type list with counts & amounts
  - compute_statistics     → summary stats (count, amount, orgs, etc.)
  - compute_date_range     → earliest/latest date + activity chart
"""

from __future__ import annotations

from datetime import date as date_type, datetime, timedelta
from typing import Any, Dict, List, Optional

from django.core.paginator import Paginator
from django.db import models
from django.db.models import QuerySet

from core.services.decision_facets import (
    amount_sum_excluding_kae,
    effective_amount_max,
    effective_linked_amount_sum,
)


# ---------------------------------------------------------------------------
# Batch helpers — entity relationships + calculated amounts
# ---------------------------------------------------------------------------

def build_entity_relationships_by_decision(decision_ids):
    """
    Bulk-fetch entity relationships for a list of decision IDs, grouped by
    decision id, in the same dict shape used by
    ``serialize_decision_with_entities``.
    """
    from core.models.entities import DecisionEntityRelationship

    decision_ids = list(decision_ids)
    if not decision_ids:
        return {}

    relationships_qs = (
        DecisionEntityRelationship.objects.filter(decision_id__in=decision_ids)
        .select_related("entity")
        .annotate(total_amount=effective_linked_amount_sum())
    )

    relationships_by_decision: dict = {}
    for rel in relationships_qs:
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
    return relationships_by_decision


def build_calculated_amounts_by_decision(decision_ids):
    """
    Bulk-compute the verified amount (sum of linked amount fields, excluding
    KAE rows) for a list of decision IDs, keyed by decision id.
    """
    from core.models.decisions import Decision

    decision_ids = list(decision_ids)
    if not decision_ids:
        return {}

    amounts_qs = (
        Decision.objects.filter(id__in=decision_ids)
        .annotate(calculated_amount=amount_sum_excluding_kae())
        .values("id", "calculated_amount")
    )
    return {
        row["id"]: (float(row["calculated_amount"]) if row["calculated_amount"] else None)
        for row in amounts_qs
    }


def build_decision_card_context(decision_ids):
    """
    Bulk-compute the data needed to embed entity + amount info into
    decision-card payloads, grouped by decision id.

    Returns a serializer context dict:
      - entity_relationships_by_decision
      - calculated_amount_by_decision
    """
    return {
        "entity_relationships_by_decision": build_entity_relationships_by_decision(
            decision_ids
        ),
        "calculated_amount_by_decision": build_calculated_amounts_by_decision(
            decision_ids
        ),
    }


# ---------------------------------------------------------------------------
# paginate_decisions  (view=decisions)
# ---------------------------------------------------------------------------

def paginate_decisions(
    qs: QuerySet,
    page: int = 1,
    page_size: int = 20,
    *,
    serialize_fn=None,
    filters: Optional[Dict[str, Any]] = None,
    search_log_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Paginate a Decision queryset and return a standardised response dict.

    Includes batched entity-relationship fetching to avoid N+1 queries.

    Args:
        qs: Filtered & sorted Decision queryset.
        page: 1-based page number.
        page_size: Items per page.
        serialize_fn: Optional callable(decision, entity_rels) → dict.
                      Defaults to ``serialize_decision_with_entities``.
        filters: Optional dict of applied filters to echo back to the
                 frontend (search_query, status, dates, sort, etc.).
        search_log_id: Optional search-analytics log ID for click tracking.

    Returns a dict with ``results``, ``pagination``, ``filters``, and
    (when present) ``search_log_id`` keys.
    """
    from api.views.search.base import serialize_decision_with_entities

    if serialize_fn is None:
        serialize_fn = serialize_decision_with_entities

    # Optimise
    qs = qs.select_related(
        "decision_type", "organization", "text_extraction"
    ).prefetch_related("kae_amounts", "signers")

    # Ensure the queryset has deterministic ordering (Django Paginator warns
    # on unordered querysets).  Callers should have already applied a sort
    # via apply_sort / apply_decision_facets; this is a safety net.
    if not qs.query.order_by:
        qs = qs.order_by("-issue_date_day")

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)

    # ── Batch-fetch entity relationships (eliminates N+1) ──────────
    decision_ids = [d.id for d in page_obj]
    relationships_by_decision = build_entity_relationships_by_decision(decision_ids)

    # Serialize
    results = []
    for decision in page_obj:
        entity_rels = relationships_by_decision.get(decision.id, [])
        decision_data = serialize_fn(decision, entity_rels)

        # Include calculated_amount when available (explore queries annotate this)
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

    result = {
        "results": results,
        "pagination": {
            "current_page": page,
            "total_pages": paginator.num_pages,
            "total_count": paginator.count,
            "has_next": page_obj.has_next(),
            "has_previous": page_obj.has_previous(),
            "page_size": page_size,
        },
        "filters": filters or {},
    }
    if search_log_id is not None:
        result["search_log_id"] = search_log_id
    return result


# ---------------------------------------------------------------------------
# aggregate_decision_types  (view=decision_types)
# ---------------------------------------------------------------------------

def aggregate_decision_types(qs: QuerySet) -> Dict[str, Any]:
    """
    Aggregate a Decision queryset into a list of unique decision types
    with counts and financial data.

    Groups by ``decision_type__uid`` only (NOT label), using
    ``Max(label)`` to avoid duplicate rows when the same uid has
    inconsistent labels.  This is the canonical fix for the "duplicate
    decision-type rows" bug.

    Returns ``{"decision_types": [...], "total_types": N}``.
    """
    decision_types = (
        qs.values("decision_type__uid")
        .annotate(
            count=models.Count("id"),
            total_amount=amount_sum_excluding_kae(),
            max_amount=effective_amount_max(),
            label=models.Max("decision_type__label"),
        )
        .filter(decision_type__uid__isnull=False)
        .order_by("-count")
    )

    formatted_types = []
    for dt in decision_types:
        count_val = dt["count"]
        total = float(dt["total_amount"] or 0)
        max_val = float(dt["max_amount"] or 0)
        formatted_types.append(
            {
                "uid": dt["decision_type__uid"],
                "label": dt["label"],
                "count": count_val,
                "total_amount": total,
                "avg_amount": round(total / count_val, 2) if count_val else 0,
                "max_amount": max_val,
            }
        )

    return {
        "decision_types": formatted_types,
        "total_types": len(formatted_types),
    }


# ---------------------------------------------------------------------------
# compute_statistics  (view=statistics)
# ---------------------------------------------------------------------------

def compute_statistics(
    qs: QuerySet,
    start_date_str: str = "",
    end_date_str: str = "",
) -> Dict[str, Any]:
    """
    Compute summary statistics for a Decision queryset.

    Returns a dict with ``period`` and ``summary`` keys matching the
    shape expected by the frontend statistics display.

    Args:
        qs: Filtered Decision queryset.
        start_date_str, end_date_str: Original date strings for the response.
    """
    stats = qs.aggregate(
        total_decisions=models.Count("id"),
        total_amount=amount_sum_excluding_kae(),
    )

    organizations_count = qs.values("organization").distinct().count()

    total_amount = float(stats["total_amount"] or 0)
    total_decisions = stats["total_decisions"] or 0

    return {
        "period": {
            "start_date": start_date_str,
            "end_date": end_date_str,
            "days_count": 0,
        },
        "summary": {
            "decisions": {
                "total_count": total_decisions,
                "total_amount": total_amount,
                "avg_amount": round(total_amount / total_decisions, 2) if total_decisions else 0,
            },
            "financial": {
                "primary_amount": total_amount,
                "has_discrepancy": False,
                "discrepancy_percentage": 0,
            },
            "organizations_count": organizations_count,
            "status_breakdown": {},
        },
    }


# ---------------------------------------------------------------------------
# compute_date_range  (view=date_range)
# ---------------------------------------------------------------------------

def compute_date_range(qs: QuerySet) -> Dict[str, Any]:
    """
    Compute date-range metadata and activity-chart data for a Decision
    queryset.

    Returns ``has_data``, ``date_range``, ``summary``, and
    ``activity_chart`` keys.
    """
    from django.db import models as dj_models

    date_stats = qs.aggregate(
        earliest_date=dj_models.Min("issue_date_day"),
        latest_date=dj_models.Max("issue_date_day"),
        total_decisions=dj_models.Count("id"),
        total_amount=amount_sum_excluding_kae(),
    )

    total_amount = float(date_stats["total_amount"] or 0)

    if not date_stats["earliest_date"]:
        return {
            "has_data": False,
            "message": "No decisions found.",
            "date_range": None,
            "activity_chart": [],
        }

    earliest = date_stats["earliest_date"]
    latest = date_stats["latest_date"]
    span_days = (latest - earliest).days

    # Choose granularity based on span
    if span_days <= 31:
        granularity = "day"
        period_column = "issue_date_day"
    elif span_days <= 1825:
        granularity = "month"
        period_column = "issue_date_month"
    else:
        granularity = "year"
        period_column = "issue_date_year"

    # Activity data
    activity_data = (
        qs.annotate(period=dj_models.F(period_column))
        .values("period")
        .annotate(
            count=dj_models.Count("id"),
            total_amount=amount_sum_excluding_kae(),
        )
        .order_by("period")
    )

    chart_data = []
    for item in activity_data:
        period_val = item["period"]
        period_str = (
            str(period_val)
            if granularity == "year"
            else (period_val.isoformat() if period_val else None)
        )
        chart_data.append(
            {
                "period": period_str,
                "count": item["count"],
                "amount": float(item["total_amount"] or 0),
            }
        )

    # Chart stats — computed once here so every caller gets the same shape
    # without copy-pasting the enrichment logic.
    amounts = [item["amount"] for item in chart_data if item["amount"] > 0]
    counts = [item["count"] for item in chart_data]
    chart_stats = {
        "max_amount": max(amounts) if amounts else 0,
        "max_count": max(counts) if counts else 0,
        "avg_amount": sum(amounts) / len(amounts) if amounts else 0,
        "avg_count": sum(counts) / len(counts) if counts else 0,
        "periods_with_activity": len([c for c in counts if c > 0]),
        "total_periods": len(chart_data),
    }

    return {
        "has_data": True,
        "date_range": {
            "earliest": earliest.isoformat() if hasattr(earliest, 'isoformat') else str(earliest),
            "latest": latest.isoformat() if hasattr(latest, 'isoformat') else str(latest),
            "span_days": span_days,
            "recommended_granularity": granularity,
        },
        "summary": {
            "total_decisions": date_stats["total_decisions"],
            "total_amount": total_amount,
            "avg_daily_decisions": round(
                date_stats["total_decisions"] / max(span_days, 1), 2
            ),
            "avg_daily_amount": round(
                total_amount / max(span_days, 1), 2
            ),
        },
        "activity_chart": {
            "data": chart_data,
            "granularity": granularity,
            "stats": chart_stats,
        },
    }
