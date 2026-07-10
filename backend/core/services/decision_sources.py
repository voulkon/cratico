"""
Decision-source registry.

Each "source" is a function that, given a Django request, returns a Decision
queryset (or raises an appropriate error response).  Sources are the ONLY
thing that varies across decision endpoints — facets, projections, and
response shapes are all shared.

Adding a new source:
    1. Write a ``build_<name>_source(request) -> QuerySet`` function.
    2. Register it in ``SOURCE_BUILDERS``.
    3. Optionally add an ``authorize_<name>_source`` for permissions.
       (If omitted, the default ``authorize_source`` returns None, meaning
        no special authorisation beyond DRF's permission_classes.)

Sources:
    entity       — decisions for an entity (org, signer, unit, afm)
    afm          — decisions for an AFM entity (via relationships)
    relationship — decisions for an AFM↔Organization pair
    temporal     — all decisions (global / temporal exploration)
    batch        — decisions within a notification batch
    subscription — decisions for a notification subscription
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

from django.db.models import QuerySet
from rest_framework.response import Response


# ---------------------------------------------------------------------------
# Source builder type
# ---------------------------------------------------------------------------

SourceBuilder = Callable[..., QuerySet]


# ---------------------------------------------------------------------------
# Individual source builders
# ---------------------------------------------------------------------------

def build_entity_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=entity``.

    Requires ``entity_type`` and ``entity_id`` query params.
    """
    from api.views.search.base import get_entity_decisions_queryset

    entity_type = (request.GET.get("entity_type") or "").strip()
    entity_id = (request.GET.get("entity_id") or "").strip()

    if not entity_type or not entity_id:
        raise ValueError(
            "entity_type and entity_id are required for source=entity"
        )

    return get_entity_decisions_queryset(entity_type, entity_id)


def build_afm_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=afm``.

    Requires ``afm`` query param.  Uses the same relationship-based lookup
    as ``get_entity_decisions_queryset("afm", ...)``.
    """
    from core.models.decisions import Decision

    afm = (request.GET.get("afm") or "").strip()
    if not afm:
        raise ValueError("afm is required for source=afm")

    return Decision.objects.filter(
        entity_relationships__entity__afm=afm
    ).distinct()


def build_relationship_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=relationship``.

    Requires ``afm`` and ``org_uid`` query params.
    """
    from core.models.decisions import Decision
    from core.models.entities import DecisionEntityRelationship

    afm = (request.GET.get("afm") or "").strip()
    org_uid = (request.GET.get("org_uid") or "").strip()

    if not afm or not org_uid:
        raise ValueError(
            "afm and org_uid are required for source=relationship"
        )

    return Decision.objects.filter(
        id__in=DecisionEntityRelationship.objects.filter(
            entity__afm=afm
        ).values_list("decision_id", flat=True),
        organization__uid=org_uid,
    )


def build_temporal_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=temporal``.

    Returns all decisions — no source-specific filtering.
    """
    from core.models.decisions import Decision

    return Decision.objects.all()


def build_batch_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=batch``.

    Requires ``batch_id`` query param.  Returns decisions within the
    notification batch, accessed through the NotificationBatchDecision
    through-model.

    Note: this returns a queryset of ``Decision`` objects (not
    ``NotificationBatchDecision``), so the ``viewed`` facet works via
    the ``notification_batches__is_viewed`` join.
    """
    from core.models.decisions import Decision
    from notifications.models import NotificationBatch

    batch_id = (request.GET.get("batch_id") or "").strip()
    if not batch_id:
        raise ValueError("batch_id is required for source=batch")

    try:
        batch = NotificationBatch.objects.get(id=batch_id)
    except NotificationBatch.DoesNotExist:
        raise ValueError(f"Batch with id={batch_id} not found")

    return Decision.objects.filter(
        notification_batches__batch=batch,
    ).distinct()


def build_subscription_source(request) -> QuerySet:
    """
    Build a Decision queryset for ``source=subscription``.

    Requires ``subscription_id`` query param.  Returns decisions across
    all batches for the given subscription.
    """
    from core.models.decisions import Decision
    from notifications.models import NotificationSubscription

    subscription_id = (request.GET.get("subscription_id") or "").strip()
    if not subscription_id:
        raise ValueError("subscription_id is required for source=subscription")

    try:
        subscription = NotificationSubscription.objects.get(id=subscription_id)
    except NotificationSubscription.DoesNotExist:
        raise ValueError(
            f"Subscription with id={subscription_id} not found"
        )

    return Decision.objects.filter(
        notification_batches__subscription=subscription,
    ).distinct()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

SOURCE_BUILDERS: Dict[str, SourceBuilder] = {
    "entity":       build_entity_source,
    "afm":          build_afm_source,
    "relationship": build_relationship_source,
    "temporal":     build_temporal_source,
    "batch":        build_batch_source,
    "subscription": build_subscription_source,
}


# ---------------------------------------------------------------------------
# Source authorisation hooks
# ---------------------------------------------------------------------------

def authorize_source(request, source_qs: QuerySet) -> Optional[Response]:
    """
    Check that the requesting user is authorised to access *source_qs*.

    Returns ``None`` if authorised, or a ``Response`` (e.g. 403) if not.

    Individual sources can register authorisation logic here.  By default
    all sources are public (auth is handled by DRF's ``permission_classes``).
    """
    source = (request.GET.get("source") or "").strip()

    if source == "batch":
        return _authorize_batch_source(request)

    if source == "subscription":
        return _authorize_subscription_source(request)

    # entity / afm / relationship / temporal are public
    return None


def _authorize_batch_source(request) -> Optional[Response]:
    """Ensure the requesting user owns the batch."""
    from notifications.models import NotificationBatch

    batch_id = (request.GET.get("batch_id") or "").strip()
    if not batch_id:
        return None  # builder will handle the missing-param error

    try:
        batch = NotificationBatch.objects.get(id=batch_id)
    except NotificationBatch.DoesNotExist:
        return Response(
            {"error": f"Batch with id={batch_id} not found"}, status=404
        )

    if batch.user_id != request.user.id:
        return Response(
            {"error": "You do not have access to this batch"}, status=403
        )
    return None


def _authorize_subscription_source(request) -> Optional[Response]:
    """Ensure the requesting user owns the subscription."""
    from notifications.models import NotificationSubscription

    subscription_id = (request.GET.get("subscription_id") or "").strip()
    if not subscription_id:
        return None

    try:
        subscription = NotificationSubscription.objects.get(id=subscription_id)
    except NotificationSubscription.DoesNotExist:
        return Response(
            {"error": f"Subscription with id={subscription_id} not found"},
            status=404,
        )

    if subscription.user_id != request.user.id:
        return Response(
            {"error": "You do not have access to this subscription"},
            status=403,
        )
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_source_queryset(request) -> QuerySet:
    """
    Dispatch to the correct source builder based on ``request.GET["source"]``.

    Raises ``ValueError`` for unknown/missing sources (caught by the view
    and returned as a 400).
    """
    source = (request.GET.get("source") or "").strip().lower()
    if not source:
        raise ValueError("source query parameter is required")

    builder = SOURCE_BUILDERS.get(source)
    if builder is None:
        raise ValueError(
            f"Unknown source: {source!r}. "
            f"Valid sources: {', '.join(sorted(SOURCE_BUILDERS))}"
        )

    return builder(request)
