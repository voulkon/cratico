"""
Resolve the "decision reference" used in API URLs.

Decision endpoints historically took the integer PK (``/api/decisions/128820/``).
They now also accept the ΑΔΑ (ADA) — ``/api/decisions/ΨΦ4Μ4653ΠΓ-ΜΜΥ/`` — which is
what users see on Diavgeia and what other services (notifications, subscriptions)
carry around.

Both forms are resolved here so every view shares one implementation:

    from api.utils.decision_refs import resolve_decision

    decision = resolve_decision(
        decision_ref,
        Decision.objects.select_related("organization"),
    )
    # A missing reference raises ``Decision.DoesNotExist`` (views → 404).
"""

from urllib.parse import unquote

from core.models.decisions import Decision


def resolve_decision(decision_ref, queryset=None) -> Decision:
    """
    Look up a :class:`~core.models.decisions.Decision` by PK **or** ADA.

    Args:
        decision_ref: URL path segment — either an integer PK (``"128820"``,
            or an ``int`` when called programmatically) or an ADA
            (``"ΨΦ4Μ4653ΠΓ-ΜΜΥ"``, possibly percent-encoded).
        queryset: Optional pre-configured queryset (``select_related`` /
            ``prefetch_related`` / ``only``) to run the lookup on.  Defaults to
            ``Decision.objects.all()``.

    Returns:
        The matching ``Decision``.

    Raises:
        Decision.DoesNotExist: no decision matches the reference.
    """
    qs = queryset if queryset is not None else Decision.objects.all()

    # Percent-encoded segments are not guaranteed to be decoded by every WSGI
    # server / test client, so normalise here (a no-op for already-decoded
    # values — ADAs never contain "%").
    ref = unquote(str(decision_ref)).strip()

    if ref.isdecimal():
        # `isdecimal()` (not `isdigit()`) so exotic superscripts cannot reach
        # int() and blow up with a ValueError → 500.
        return qs.get(id=int(ref))

    try:
        return qs.get(ada=ref)
    except Decision.DoesNotExist:
        pass

    # Fallback for lower-cased references (copy/paste, link normalisers): the
    # stored ADA is always canonical upper-case.  `.first()` rather than
    # `.get()` because the unique index is case-sensitive — a hypothetical
    # mixed-case duplicate must not turn into a MultipleObjectsReturned → 500.
    decision = qs.filter(ada__iexact=ref).first()
    if decision is None:
        raise Decision.DoesNotExist(f"No decision with id or ADA {ref!r}")
    return decision
