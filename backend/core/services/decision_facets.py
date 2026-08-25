"""
Shared decision-facet layer.

A "facet" is a filter or sort that can be applied uniformly to any Decision
queryset regardless of its source (entity, relationship, temporal, batch, etc.).

Every facet function:
  - accepts a queryset and the request (or explicit parameters)
  - returns the potentially filtered/sorted queryset
  - is a pure queryset transformation — it does NOT evaluate the queryset

Usage:
    from core.services.decision_facets import apply_decision_facets

    qs = apply_decision_facets(source_qs, request)
    # qs is now filtered by date, search, type, amount, direct-only, viewed,
    # and sorted — regardless of how source_qs was built.
"""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Optional, Tuple

from django.db import models
from django.db.models import Avg, Max, Min, Q, QuerySet, Sum
from django.db.models.functions import Coalesce
from django.utils.dateparse import parse_date
from rest_framework.response import Response


# ---------------------------------------------------------------------------
# Shared annotation: sum of DecisionAmountField.amount excluding KAE rows
# ---------------------------------------------------------------------------
# amountWithKae rows duplicate the amountWithVAT total (or contain budget
# numbers, not actual expenditures).  Every Sum("amount_fields__amount")
# should use this expression instead to avoid double-counting.
# Confirmed by analysis: 190K decisions have KAE=non-KAE, 7.6K have KAE as
# unrelated budget figures.

def amount_sum_excluding_kae():
    """Return a Sum expression that excludes amountWithKae* rows.

    Uses ``COALESCE(verified_amount, amount)`` so corrected values take
    precedence, consistent with :func:`effective_amount_sum`.
    """
    return Sum(
        Coalesce("amount_fields__verified_amount", "amount_fields__amount"),
        filter=~Q(amount_fields__parent_key_path__startswith="amountWithKae"),
    )


def effective_amount_sum_excluding_kae():
    """Verified-aware sum excluding KAE rows (combines both helpers)."""
    return effective_amount_sum(
        filter=~Q(amount_fields__parent_key_path__startswith="amountWithKae")
    )


def effective_amount_max(filter=None):
    """Max of ``COALESCE(verified_amount, amount)`` — verified-aware."""
    return models.Max(
        Coalesce("amount_fields__verified_amount", "amount_fields__amount"),
        filter=filter,
    )


def effective_amount_sum(filter=None):
    """
    Return a Sum expression that uses the verified amount when available.

    Each ``DecisionAmountField`` may have a ``verified_amount`` set by the
    cents-based detector.  This expression sums ``COALESCE(verified_amount,
    amount)`` so corrected values automatically take precedence in every
    aggregation — no Decision-model bloat needed.

    Usage in pre-calc modules (replaces every raw ``Sum("amount_fields__amount")``)::

        .annotate(
            calculated_amount=effective_amount_sum(
                filter=Q(amount_fields__associated_relationship__isnull=False)
            )
        )

    Or without a filter::

        .annotate(total=effective_amount_sum())
    """
    return Sum(
        Coalesce("amount_fields__verified_amount", "amount_fields__amount"),
        filter=filter,
    )


def effective_linked_amount_sum(filter=None):
    """
    Verified-aware sum over ``DecisionEntityRelationship.linked_amounts``.

    ``linked_amounts`` points at ``DecisionAmountField`` rows, each of which
    may carry a ``verified_amount``.  Use ``COALESCE(verified_amount, amount)``
    so corrected values take precedence — the relationship-level equivalent of
    :func:`effective_amount_sum`.
    """
    return Sum(
        Coalesce(
            "linked_amounts__verified_amount", "linked_amounts__amount"
        ),
        filter=filter,
    )


def effective_linked_amount_avg(filter=None):
    """Verified-aware avg over ``DecisionEntityRelationship.linked_amounts``."""
    return Avg(
        Coalesce(
            "linked_amounts__verified_amount", "linked_amounts__amount"
        ),
        filter=filter,
    )


def effective_linked_amount_max(filter=None):
    """Verified-aware max over ``DecisionEntityRelationship.linked_amounts``."""
    return Max(
        Coalesce(
            "linked_amounts__verified_amount", "linked_amounts__amount"
        ),
        filter=filter,
    )


def effective_linked_amount_min(filter=None):
    """Verified-aware min over ``DecisionEntityRelationship.linked_amounts``."""
    return Min(
        Coalesce(
            "linked_amounts__verified_amount", "linked_amounts__amount"
        ),
        filter=filter,
    )


# ---------------------------------------------------------------------------
# Date-range facet
# ---------------------------------------------------------------------------

def apply_date_range(
    qs: QuerySet,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
) -> QuerySet:
    """
    Apply date-range filtering to a Decision queryset.

    Supports partial ranges: a lone start_date filters >= start, a lone
    end_date filters <= end.  This is the uniform rule — every source
    uses the same behaviour.

    Uses the optimised ``filter_by_date_range`` custom queryset method
    when available; falls back to direct filtering otherwise.
    """
    if hasattr(qs, "filter_by_date_range"):
        return qs.filter_by_date_range(start_dt, end_dt)

    if start_dt is not None:
        qs = qs.filter(issue_date_day__gte=start_dt)
    if end_dt is not None:
        qs = qs.filter(issue_date_day__lte=end_dt)
    return qs


def parse_date_range_from_request(
    request,
) -> Tuple[Optional[datetime], Optional[datetime], Optional[Response]]:
    """
    Parse ``start_date`` and ``end_date`` from request.GET.

    Returns ``(start_dt, end_dt, error_response)``.  ``error_response`` is
    non-None only when a date string is present but invalid — missing dates
    are silently treated as ``None``.

    Dates are converted to timezone-aware datetimes (start of day / end of
    day respectively) for consistent queryset filtering.
    """
    from django.utils import timezone as tz

    start_date_str = (request.GET.get("start_date") or "").strip()
    end_date_str = (request.GET.get("end_date") or "").strip()

    start_dt = None
    end_dt = None

    if start_date_str:
        parsed = parse_date(start_date_str)
        if not parsed:
            return None, None, Response(
                {"error": "Invalid start_date format. Use YYYY-MM-DD."},
                status=400,
            )
        start_dt = tz.make_aware(datetime.combine(parsed, datetime.min.time()))

    if end_date_str:
        parsed = parse_date(end_date_str)
        if not parsed:
            return None, None, Response(
                {"error": "Invalid end_date format. Use YYYY-MM-DD."},
                status=400,
            )
        end_dt = tz.make_aware(datetime.combine(parsed, datetime.max.time()))

    return start_dt, end_dt, None


# ---------------------------------------------------------------------------
# Full-text search facet
# ---------------------------------------------------------------------------

def apply_search(qs: QuerySet, search_query: str) -> QuerySet:
    """
    Apply full-text / substring search to a Decision queryset.

    Always searches ``subject`` and ``ada`` (decision metadata).  If the
    PostgreSQL indexing feature flag is enabled, also searches the
    ``text_extraction.search_vector`` tsvector field.
    """
    if not search_query:
        return qs

    q_filter = models.Q(subject__icontains=search_query) | models.Q(
        ada__icontains=search_query
    )

    from core.services.feature_flag_service import feature_flags

    if feature_flags.is_enabled("INDEX_THE_POSTGRES"):
        from django.contrib.postgres.search import SearchQuery

        search_query_obj = SearchQuery(search_query)
        q_filter |= models.Q(text_extraction__search_vector=search_query_obj)

    return qs.filter(q_filter).distinct()


# ---------------------------------------------------------------------------
# Decision-type filter facet
# ---------------------------------------------------------------------------

def apply_decision_type_filter(
    qs: QuerySet,
    decision_type_uids: list[str],
) -> QuerySet:
    """Filter decisions to those whose ``decision_type.uid`` is in *uids*."""
    if not decision_type_uids:
        return qs
    return qs.filter(decision_type__uid__in=decision_type_uids)


def parse_decision_type_uids(request) -> list[str]:
    """Parse comma-separated ``decision_types`` query param into a list of UIDs."""
    raw = (request.GET.get("decision_types") or "").strip()
    return [t.strip() for t in raw.split(",") if t.strip()]


# ---------------------------------------------------------------------------
# Amount-range facet
# ---------------------------------------------------------------------------

def apply_amount_range(
    qs: QuerySet,
    min_amount: Optional[float],
    max_amount: Optional[float],
    amount_field: str = "calculated_amount",
) -> QuerySet:
    """Filter decisions by inclusive amount range.

    Defaults to filtering on ``calculated_amount`` (the sum of all
    linked ``DecisionAmountField.amount`` rows) rather than the
    denormalised ``Decision.amount`` field which may be NULL.
    """
    if min_amount is not None:
        qs = qs.filter(**{f"{amount_field}__gte": min_amount})
    if max_amount is not None:
        qs = qs.filter(**{f"{amount_field}__lte": max_amount})
    return qs


def parse_amount_range(request):
    """
    Parse ``min_amount`` and ``max_amount`` from request.GET.

    Returns ``(min_amount, max_amount, error_response)``.  ``error_response``
    is non-None only when a value is present but invalid.
    """
    min_str = (request.GET.get("min_amount") or "").strip()
    max_str = (request.GET.get("max_amount") or "").strip()

    min_amount = None
    max_amount = None
    try:
        if min_str:
            min_amount = float(min_str)
        if max_str:
            max_amount = float(max_str)
    except ValueError:
        return None, None, Response(
            {"error": "Invalid amount format"}, status=400
        )

    return min_amount, max_amount, None


# ---------------------------------------------------------------------------
# Organization filter facet
# ---------------------------------------------------------------------------

def apply_organization_filter(
    qs: QuerySet,
    organization_ids: Optional[list[str]],
) -> QuerySet:
    """Filter decisions to those belonging to specific organizations."""
    if not organization_ids:
        return qs
    return qs.filter(organization__uid__in=organization_ids)


def parse_organization_ids(request) -> list[str]:
    """Parse comma-separated ``organization_ids`` query param into a list of UIDs."""
    raw = (request.GET.get("organization_ids") or "").strip()
    return [o.strip() for o in raw.split(",") if o.strip()]


# ---------------------------------------------------------------------------
# Direct-assignments-only facet
# ---------------------------------------------------------------------------

def apply_direct_assignments_only(qs: QuerySet, direct_only: bool) -> QuerySet:
    """If *direct_only* is True, keep only direct-assignment decisions.

    Filters via the ``classification`` OneToOneField on Decision.
    Decisions without a ``DecisionClassification`` record are implicitly
    excluded when ``direct_only=True`` (the join returns NULL for them).
    """
    if not direct_only:
        return qs
    return qs.filter(classification__is_direct_assignment=True)


def parse_direct_assignments_only(request) -> bool:
    """Parse ``direct_assignments_only`` query param as a boolean."""
    return (request.GET.get("direct_assignments_only") or "").lower() in {
        "true", "1", "yes",
    }


# ---------------------------------------------------------------------------
# Viewed facet (batch / subscription only)
# ---------------------------------------------------------------------------

def apply_viewed(qs: QuerySet, viewed: Optional[str]) -> QuerySet:
    """
    Filter by viewed status via the ``notification_batches`` through-model.

    For batch/subscription sources the decisions are already scoped to a
    specific batch/subscription, so this correctly filters within that
    scope.  For non-batch sources the frontend does not send this param.

    *viewed* should be one of ``"true"``, ``"false"``, or ``None``/``"all"``.
    """
    if viewed is None or viewed.lower() == "all":
        return qs

    is_viewed = viewed.lower() == "true"
    # Filter through the NotificationBatchDecision through-model.
    # Decision.notification_batches is the reverse relation from the
    # NotificationBatchDecision.decision FK (related_name='notification_batches').
    return qs.filter(notification_batches__is_viewed=is_viewed)


def parse_viewed(request) -> Optional[str]:
    """Parse ``viewed`` query param (``"true"`` / ``"false"`` / ``"all"``)."""
    raw = (request.GET.get("viewed") or "").strip().lower()
    if raw in ("true", "false"):
        return raw
    return None  # "all" or absent


# ---------------------------------------------------------------------------
# Sort facet
# ---------------------------------------------------------------------------

def apply_sort(qs: QuerySet, sort_by: str, amount_field: str = "calculated_amount", date_field: str = "issue_date_day") -> QuerySet:
    """
    Apply sorting via the shared ``apply_decision_sorting`` utility.

    When sorting by amount, uses ``calculated_amount`` — the sum of all
    linked ``DecisionAmountField.amount`` rows — for both the sort
    order and the response (``paginate_decisions`` automatically picks
    this up).  This is more accurate than the denormalised ``amount``
    field which may be NULL.

    If ``calculated_amount`` has not yet been annotated on the queryset
    (e.g. when called outside of ``apply_decision_facets``), it is
    annotated here.

    Wraps ``api.utils.sorting.apply_decision_sorting`` with reasonable
    defaults for the date field so callers don't need to remember which
    field name each source uses.
    """
    from api.utils.sorting import apply_decision_sorting

    # When sorting by amount, ensure calculated_amount is annotated.
    # apply_decision_facets already does this before amount filtering;
    # this is a fallback for direct callers.
    if sort_by in ("amount_desc", "amount_asc"):
        if "calculated_amount" not in qs.query.annotations:
            qs = qs.annotate(
                calculated_amount=amount_sum_excluding_kae()
            )
        amount_field = "calculated_amount"

    return apply_decision_sorting(
        qs,
        sort_by,
        amount_field=amount_field,
        date_field=date_field,
    )


def parse_sort_by(request, default: str = "recent") -> str:
    """
    Parse ``sort_by`` query param, falling back to *default*.

    Normalises legacy sort aliases:
      - ``entity_amount_desc`` → ``amount_desc``
      - ``entity_amount_asc``  → ``amount_asc``

    The ``entity_amount_*`` sorts (which aggregate across all entity
    relationships) produce a different ordering than the plain ``amount``
    field, but are accepted as a compatibility alias so that frontend
    callers migrating from the old explore endpoints don't break.
    """
    sort_by = (
        request.GET.get("sort_by") or request.GET.get("sort") or default
    ).strip()
    # Normalise legacy entity-amount sort aliases
    if sort_by == "entity_amount_desc":
        return "amount_desc"
    if sort_by == "entity_amount_asc":
        return "amount_asc"
    return sort_by


# ---------------------------------------------------------------------------
# Composite: apply *all* facets at once
# ---------------------------------------------------------------------------

def apply_decision_facets(
    qs: QuerySet,
    request=None,
    *,
    start_dt: Optional[datetime] = None,
    end_dt: Optional[datetime] = None,
    search_query: str = "",
    decision_type_uids: Optional[list[str]] = None,
    organization_ids: Optional[list[str]] = None,
    min_amount: Optional[float] = None,
    max_amount: Optional[float] = None,
    direct_assignments_only: bool = False,
    viewed: Optional[str] = None,
    sort_by: str = "recent",
    status_filter: str = "",
    amount_field: str = "calculated_amount",
    date_field: str = "issue_date_day",
) -> QuerySet:
    """
    Apply the complete set of standard facets to a Decision queryset.

    Can be called with explicit keyword arguments OR by passing *request*
    (in which case all params are parsed from request.GET).

    Always annotates ``calculated_amount`` (the sum of all linked
    ``DecisionAmountField.amount`` rows) so that filtering, sorting and
    display all use the same accurate value.  The denormalised
    ``Decision.amount`` field is deliberately NOT used — it may be NULL
    even when linked amount fields contain real data.

    Returns the filtered + sorted queryset.
    """
    # If a request is provided, parse params from it (overriding explicit kwargs)
    if request is not None:
        if start_dt is None and end_dt is None:
            start_dt, end_dt, _err = parse_date_range_from_request(request)
        if not search_query:
            search_query = (request.GET.get("q") or "").strip()
        if decision_type_uids is None:
            decision_type_uids = parse_decision_type_uids(request)
        if organization_ids is None:
            organization_ids = parse_organization_ids(request)
        if min_amount is None and max_amount is None:
            min_amount, max_amount, _err = parse_amount_range(request)
        if not direct_assignments_only:
            direct_assignments_only = parse_direct_assignments_only(request)
        if viewed is None:
            viewed = parse_viewed(request)
        if sort_by == "recent":
            sort_by = parse_sort_by(request)
        if not status_filter:
            status_filter = (request.GET.get("status") or "").strip()

    decision_type_uids = decision_type_uids or []
    organization_ids = organization_ids or []

    # 1. Date range
    qs = apply_date_range(qs, start_dt, end_dt)

    # 2. Full-text search
    qs = apply_search(qs, search_query)

    # 3. Status
    if status_filter:
        qs = qs.filter(status=status_filter)

    # 4. Decision types
    qs = apply_decision_type_filter(qs, decision_type_uids)

    # 5. Organization IDs
    qs = apply_organization_filter(qs, organization_ids)

    # ── Annotate calculated_amount *before* amount-range filtering ──
    # Always annotate calculated_amount (sum of ALL linked
    # DecisionAmountField.amount rows) so that filtering, sorting and
    # display all use the same accurate value.  The denormalised
    # Decision.amount field is deliberately ignored — it may be NULL
    # even when linked amount fields contain real data.
    if "calculated_amount" not in qs.query.annotations:
        qs = qs.annotate(
            calculated_amount=amount_sum_excluding_kae()
        )
    amount_field = "calculated_amount"

    # 6. Amount range
    qs = apply_amount_range(qs, min_amount, max_amount, amount_field=amount_field)

    # 7. Direct assignments only
    qs = apply_direct_assignments_only(qs, direct_assignments_only)

    # 8. Viewed (no-op for non-batch sources)
    qs = apply_viewed(qs, viewed)

    # 9. Sort
    qs = apply_sort(qs, sort_by, amount_field=amount_field, date_field=date_field)

    return qs
