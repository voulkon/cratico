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

from typing import Any, Dict, Optional

from django.core.paginator import Paginator
from django.db import models
from django.db.models import Exists, OuterRef, Prefetch, QuerySet
from django.utils.functional import cached_property

from core.services.decision_facets import (
    amount_sum_excluding_kae,
    daf_effective_sum_excluding_kae,
    effective_amount_max,
    effective_linked_amount_sum,
)

# Columns the default card serializer reads; ``.only()`` keeps the wide
# DocumentExtraction columns off the list query.
DEFAULT_LIST_ONLY_FIELDS = (
    "id",
    "ada",
    "subject",
    "issue_date_day",
    "amount",
    "status",
    "document_url",
    "decision_type__uid",
    "decision_type__label",
    "organization__uid",
    "organization__label",
)


# ---------------------------------------------------------------------------
# Shared decision totals — no to-many fan-out, no double aggregation
# ---------------------------------------------------------------------------

def _amount_fields_for(qs: QuerySet):
    """``DecisionAmountField`` rows belonging to the decisions in ``qs``.

    Rooting the amount query at the child table keeps the parent queryset
    free of the to-many join, so neither a count nor a sum fans out.
    """
    from core.models.entities import DecisionAmountField

    return DecisionAmountField.objects.filter(
        decision_id__in=qs.order_by().values("pk")
    )


def decision_totals(qs: QuerySet) -> Dict[str, Any]:
    """Return ``total_decisions`` and ``total_amount`` for a decision qs."""
    total_decisions = qs.aggregate(n=models.Count("id", distinct=True))["n"] or 0
    total_amount = (
        _amount_fields_for(qs).aggregate(
            total=daf_effective_sum_excluding_kae()
        )["total"]
        or 0
    )
    return {
        "total_decisions": total_decisions,
        "total_amount": float(total_amount),
    }


def decision_amount_summary(qs: QuerySet) -> Dict[str, Any]:
    """Count decisions and describe their per-decision amount spread.

    The amount pass groups the child table by decision first, so
    ``AVG``/``MIN``/``MAX`` are computed over decision totals instead of
    individual amount rows.
    """
    total_decisions = qs.aggregate(n=models.Count("id", distinct=True))["n"] or 0
    per_decision = (
        _amount_fields_for(qs)
        .values("decision_id")
        .annotate(decision_total=daf_effective_sum_excluding_kae())
    )
    stats = per_decision.aggregate(
        total_amount=models.Sum("decision_total"),
        avg_amount=models.Avg("decision_total"),
        min_amount=models.Min("decision_total"),
        max_amount=models.Max("decision_total"),
        decisions_with_amounts=models.Count("decision_id"),
    )
    return {
        "total_decisions": total_decisions,
        "total_amount": float(stats["total_amount"] or 0),
        "avg_amount": float(stats["avg_amount"] or 0),
        "min_amount": float(stats["min_amount"] or 0),
        "max_amount": float(stats["max_amount"] or 0),
        "decisions_with_amounts": stats["decisions_with_amounts"] or 0,
    }


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


def build_one_liners_by_decision(decision_ids, prompt_kinds=None):
    """
    Bulk-fetch the default per-decision one-liner (the latest-COMPLETED
    ``DecisionOneLiner`` attempt, mirroring ``default_for_decision``) for a
    list of decision IDs, keyed by decision id.  ONE query — list endpoints
    render the one-liner under the card title with no N+1.

    ``prompt_kinds`` restricts the result to those ``OneLinerConfig`` prompt
    kinds; the budget inventory passes the same shareable allowlist as the
    runtime cache so a free cache hit is never counted as new work.

    Decisions without a completed attempt are simply absent (the frontend
    renders nothing).
    """
    from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus

    decision_ids = list(decision_ids)
    if not decision_ids:
        return {}

    rows = DecisionOneLiner.objects.filter(
        decision_id__in=decision_ids,
        status=OneLinerStatus.COMPLETED,
        one_liner__isnull=False,
    )
    if prompt_kinds is not None:
        rows = rows.filter(config__prompt_kind__in=prompt_kinds)
    rows = (
        rows.exclude(one_liner__exact="")
        .select_related("config", "extraction")
        .order_by("decision_id", "-completed_at", "-attempt", "-id")
    )

    one_liners_by_decision: dict = {}
    for row in rows:
        if row.decision_id in one_liners_by_decision:
            continue  # first row per decision = latest completed
        one_liners_by_decision[row.decision_id] = {
            "one_liner": row.one_liner,
            "model": row.config.model,
            "prompt_kind": row.config.prompt_kind,
            "extraction_provider": (
                row.extraction.extraction_provider if row.extraction else None
            ),
            "attempt": row.attempt,
            "completed_at": row.completed_at,
        }
    return one_liners_by_decision


def build_shareable_one_liners_by_decision(decision_ids):
    """``build_one_liners_by_decision`` restricted to cross-user shareable kinds."""
    from core.services.pipeline_steps.ai_call import SHAREABLE_ONE_LINER_KINDS

    return build_one_liners_by_decision(
        decision_ids, prompt_kinds=SHAREABLE_ONE_LINER_KINDS
    )


# ---------------------------------------------------------------------------
# paginate_decisions  (view=decisions)
# ---------------------------------------------------------------------------

def annotate_has_document_content(qs: QuerySet) -> QuerySet:
    """
    Annotate ``has_document_content`` without joining the extraction row.

    The serializer only needs ``bool(raw_text)``.  An ``Exists`` subquery
    returns the same value without pulling the wide ``raw_text`` /
    ``search_vector`` columns for every list row.
    """
    from core.models.document_analysis import DocumentExtraction, ProcessingStatus

    if "has_document_content" in qs.query.annotations:
        return qs

    has_content = (
        DocumentExtraction.objects.filter(
            decision=OuterRef("pk"),
            extraction_status=ProcessingStatus.COMPLETED,
        )
        .exclude(raw_text__isnull=True)
        .exclude(raw_text="")
    )
    return qs.annotate(has_document_content=Exists(has_content))


class _PrecountedPaginator(Paginator):
    """Paginator that uses a precomputed total.

    Counting the optimized list queryset would evaluate the
    ``has_document_content`` ``Exists`` subquery for every row, which cost
    about 274 ms on the organization page.  Count the unannotated queryset
    once and reuse it.
    """

    def __init__(self, object_list, per_page, total_count):
        super().__init__(object_list, per_page)
        self._total_count = total_count

    @cached_property
    def count(self):
        return self._total_count


def _prefetch_list_relations(qs: QuerySet) -> QuerySet:
    """Prefetch the per-card relations the list serializer reads.

    ``ai_analyses`` is limited to completed rows with a summary, the only
    rows the card renders, so the page costs one bounded query.  Newest
    first.
    """
    from core.models.decision_ai_analysis import (
        AnalysisStatus,
        DecisionAIAnalysis,
    )

    completed_analyses = (
        DecisionAIAnalysis.objects.filter(status=AnalysisStatus.COMPLETED)
        .exclude(summary="")
        .order_by("-created_at", "-id")
    )
    return qs.prefetch_related(
        "kae_amounts",
        "signers",
        Prefetch("ai_analyses", queryset=completed_analyses),
    )


def paginate_decisions(
    qs: QuerySet,
    page: int = 1,
    page_size: int = 20,
    *,
    serialize_fn=None,
    only_fields: Optional[tuple[str, ...]] = None,
    filters: Optional[Dict[str, Any]] = None,
    count_qs: Optional[QuerySet] = None,
    search_log_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Paginate a Decision queryset and return a standardised response dict.

    Includes batched entity-relationship, one-liner, amount-field, and
    AI-analysis fetching, so the page costs a constant number of queries
    regardless of page size.

    Args:
        qs: Filtered & sorted Decision queryset.
        page: 1-based page number.
        page_size: Items per page.
        serialize_fn: Optional callable(decision, entity_rels) → dict.
                      Defaults to ``serialize_decision_with_entities``.
        only_fields: Optional model-field paths to ``.only()`` on the page
                     query.  Defaults to ``DEFAULT_LIST_ONLY_FIELDS`` when
                     the default serializer is used; pass ``None`` with a
                     custom ``serialize_fn`` to load every column.
        filters: Optional dict of applied filters to echo back to the
                 frontend (search_query, status, dates, sort, etc.).
        count_qs: Optional queryset for the paginator total.  Pass a
                  queryset with the same filters but built with
                  ``apply_decision_facets(..., count_only=True)`` so the
                  COUNT does not join the amount table.  Defaults to ``qs``.
        search_log_id: Optional search-analytics log ID for click tracking.

    Returns a dict with ``results``, ``pagination``, ``filters``, and
    (when present) ``search_log_id`` keys.
    """
    from api.views.search.base import serialize_decision_with_entities

    if serialize_fn is None:
        serialize_fn = serialize_decision_with_entities
        if only_fields is None:
            only_fields = DEFAULT_LIST_ONLY_FIELDS

    # Count before the list annotation: the paginator's COUNT(*) would
    # otherwise evaluate has_document_content for every row.  ``count_qs``
    # additionally keeps calculated_amount (and its amount-table join) out
    # of the count.
    total_count = (count_qs if count_qs is not None else qs).count()

    # ``text_extraction`` is not joined: the page carries ``has_document_content``
    # instead, keeping the wide raw_text / search_vector columns off the SELECT.
    qs = qs.select_related("decision_type", "organization")
    qs = annotate_has_document_content(qs)
    qs = _prefetch_list_relations(qs)
    if only_fields:
        qs = qs.only(*only_fields)

    # Ensure the queryset has deterministic ordering (Django Paginator warns
    # on unordered querysets).  Callers should have already applied a sort
    # via apply_sort / apply_decision_facets; this is a safety net.
    if not qs.query.order_by:
        qs = qs.order_by("-issue_date_day")

    paginator = _PrecountedPaginator(qs, page_size, total_count)
    page_obj = paginator.get_page(page)

    # ── Batch-fetch entity relationships (eliminates N+1) ──────────
    decision_ids = [d.id for d in page_obj]
    relationships_by_decision = build_entity_relationships_by_decision(decision_ids)

    # ── Batch-fetch per-decision one-liners (eliminates N+1) ───────
    # One bounded query per page; rendered at the top level of each item
    # dict so DecisionCard shows it without an extra fetch.
    one_liners_by_decision = build_one_liners_by_decision(decision_ids)

    # ── Batch-fetch decisions whose amount is not money ────────────
    # Their recorded amount is a counterpart AFM (ΑΦΜ) or a budget KAE,
    # excluded from every aggregation by the facet layer.  One bounded query
    # per page (page_size ids) so list endpoints never render the bogus
    # 9-figure value as a monetary amount.
    from core.models.entities import DecisionAmountField

    invalid_amount_decision_ids = set(
        DecisionAmountField.objects
        .filter(
            decision_id__in=decision_ids,
            invalid_amount_reason__isnull=False,
        )
        .values_list("decision_id", flat=True)
    )

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

        # The recorded amount is a non-monetary value → report no amount.
        if decision.id in invalid_amount_decision_ids:
            decision_data["amount"] = None
            decision_data["has_invalid_amount"] = True

        if decision.organization:
            decision_data["organization"] = {
                "uid": decision.organization.uid,
                "label": decision.organization.label,
            }
        decision_data["one_liner"] = (
            one_liners_by_decision.get(decision.id, {}) or {}
        ).get("one_liner")
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
            count=models.Count("id", distinct=True),
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
    # Counting decisions needs no amount join; only the money total does.
    # ``distinct`` keeps the count correct even if a caller hands us a
    # queryset that still carries an aggregate annotation (which fans the
    # amount join out one row per amount field).
    total_decisions = qs.aggregate(
        total_decisions=models.Count("id", distinct=True)
    )["total_decisions"] or 0
    total_amount = float(
        qs.aggregate(total_amount=amount_sum_excluding_kae())["total_amount"] or 0
    )

    organizations_count = qs.values("organization").distinct().count()

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

    # Only the date bounds are needed here, and they live in the
    # ``(organization, issue_date_day)`` index.  Keeping the aggregate to
    # MIN/MAX lets Postgres answer it with an index-only scan instead of
    # fetching the decision heap (which ``COUNT(id)`` forces).
    date_bounds = qs.aggregate(
        earliest_date=dj_models.Min("issue_date_day"),
        latest_date=dj_models.Max("issue_date_day"),
    )

    if not date_bounds["earliest_date"]:
        return {
            "has_data": False,
            "message": "No decisions found.",
            "date_range": None,
            "activity_chart": [],
        }

    earliest = date_bounds["earliest_date"]
    latest = date_bounds["latest_date"]
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

    # Activity data.  This is the only projection that needs the amount
    # table.  ``Count("id", distinct=True)`` keeps the decision count
    # correct despite the amount join fanning out one row per amount field.
    #
    # The summary totals are derived from the chart instead of running a
    # second amount-table aggregate: every decision falls in exactly one
    # period, so summing the per-period counts/amounts equals the overall
    # total.  That halves the number of cold scans over
    # ``core_decisionamountfield``.
    activity_data = (
        qs.annotate(period=dj_models.F(period_column))
        .values("period")
        .annotate(
            count=dj_models.Count("id", distinct=True),
            total_amount=amount_sum_excluding_kae(),
        )
        .order_by("period")
    )

    chart_data = []
    total_amount_decimal = 0
    total_decisions = 0
    for item in activity_data:
        period_val = item["period"]
        period_str = (
            str(period_val)
            if granularity == "year"
            else (period_val.isoformat() if period_val else None)
        )
        amount_val = item["total_amount"] or 0
        total_amount_decimal += amount_val
        total_decisions += item["count"] or 0
        chart_data.append(
            {
                "period": period_str,
                "count": item["count"],
                "amount": float(amount_val),
            }
        )
    total_amount = float(total_amount_decimal)

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
            "total_decisions": total_decisions,
            "total_amount": total_amount,
            "avg_daily_decisions": round(
                total_decisions / max(span_days, 1), 2
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
