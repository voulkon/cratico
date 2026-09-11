"""
Non-monetary-value-as-amount guard.

A class of data-entry errors: the ``expenseAmount`` field holds a value that
actually belongs to a **different, non-monetary numeric field** of the same
Diavgeia API response.  The value exists once, in the wrong field — it is
*not* duplicated; it is misplaced.  It passes for an amount because it is
digit-shaped and therefore looks like a plausible 8-figure euro amount.

Two variants are currently detected:

1. **AFM-as-amount** — the counterpart's VAT number (ΑΦΜ). Canonical case:
   decision ``Ψ0Α74690Β9-52Ρ`` where sponsor AFM ``099370337`` (VIOLAK
   INTERNATIONAL) was recorded as amount ``9.9370337E7`` = €99,370,337.

2. **KAE-as-amount** — the budget classification code (ΚΑΕ, e.g.
   ``70.6273.001``) recorded as the amount, e.g. ``706273001``
   = €706,273,001.  The KAE lives as a *sibling* key of the amount inside the
   same object (``sponsor[i].kae`` next to ``sponsor[i].expenseAmount``).

Both are 8-9 digit numbers, so they look like plausible euro amounts and —
since the document text literally contains the value formatted as an amount
(``99.370.337,00``) — the "exact match wins" policy of the amount verification
pipeline **confirms** the bogus value instead of flagging it.

The scope is deliberately open: other non-monetary numeric metadata (e.g. a
protocol number) can be covered by adding a collector plus a
:data:`KIND_*` — see ``collect_non_monetary_values``.  Coverage is currently
limited to the two variants above.

This module provides the guard primitives shared by:

- ``AmountVerificationService`` (never report such a value as confirmed),
- ``AmountCorrectionService`` (never write it into ``verified_amount``),
- the ``find_amount_anomalies`` management command (discovery).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from core.services.grouped_amount_detection import _CENTS_AMOUNT_RE

# Discrepancy reasons used in run.meta / resolution notes
DISCREPANCY_REASON_AFM = "afm_as_amount"
DISCREPANCY_REASON_KAE = "kae_as_amount"
# Mixed AFM + KAE (or future) cases
DISCREPANCY_REASON_NON_MONETARY = "non_monetary_value_as_amount"

# Anomaly kinds returned by collect_non_monetary_values
KIND_AFM = "afm"
KIND_KAE = "kae"

# Minimum digit length for a KAE code to be considered (shorter codes are too
# likely to collide with ordinary amounts).
MIN_KAE_DIGITS = 6

# Trailing cents on a formatted number: ",00" / ".00" / ",0" / ".0"
_CENTS_SUFFIX_RE = re.compile(r"[.,]0{1,2}$")



def collect_counterpart_afms(decision) -> set[str]:
    """
    Collect the counterpart (sponsor / supplier) AFMs for a decision.

    Sources (union):
      1. ``DecisionEntityRelationship`` rows linked to the decision (any role
         that denotes a counterparty — sponsors, contractors, grantees).
      2. The raw Diavgeia metadata already stored on the decision
         (``extra_field_values_json["sponsor"][i]["sponsorAFMName"]["afm"]``).

    Returns a set of digit-only AFM strings (e.g. ``{"099370337"}``).
    """
    afms: set[str] = set()

    # ── 1. Entity relationships ────────────────────────────────────────
    # NOTE: use .all() (not .select_related) so a prefetched
    # ``entity_relationships__entity`` cache is honoured by callers that
    # scan many decisions at once (e.g. the find_amount_anomalies command).
    try:
        for rel in decision.entity_relationships.all():
            entity = getattr(rel, "entity", None)
            afm = (getattr(entity, "afm", "") or "").strip()
            if afm.isdigit():
                afms.add(afm)
    except Exception:
        # related manager may not exist in some contexts — never crash the
        # verification pipeline because of the guard
        pass

    # ── 2. Raw Diavgeia sponsor metadata ───────────────────────────────
    extra = getattr(decision, "extra_field_values_json", None)
    if isinstance(extra, dict):
        for sponsor in extra.get("sponsor") or []:
            if not isinstance(sponsor, dict):
                continue
            afm_name = sponsor.get("sponsorAFMName") or {}
            if not isinstance(afm_name, dict):
                continue
            afm = str(afm_name.get("afm", "") or "").strip()
            if afm.isdigit():
                afms.add(afm)

    return afms


def _digits_only(value: object) -> str:
    """Strip every non-digit character (dots, slashes, spaces) from *value*."""
    return "".join(ch for ch in str(value) if ch.isdigit())


def _span_digits_equal_value(raw_span: str, value: str) -> bool:
    """
    Check whether a raw text span (e.g. ``99.370.337,00``) is a non-monetary
    value (AFM/KAE) formatted as an amount, ignoring thousands separators,
    with or without a leading zero, and only when the trailing cents are
    ``00``.

    *value* may contain separators itself (e.g. KAE ``70.6273.001``) — they
    are stripped before comparison.
    """
    s = raw_span.strip()
    # Only strip a clean cents suffix ("00" or "0") — an AFM/KAE can never
    # have non-zero cents, so "99.370.337,50" is NOT a match.
    stripped = _CENTS_SUFFIX_RE.sub("", s)
    digits = _digits_only(stripped).lstrip("0")
    value_digits = _digits_only(value).lstrip("0")
    return bool(digits) and bool(value_digits) and digits == value_digits


def _collect_kae_codes_from_json(data, out: set[str]) -> None:
    """Recursively collect digit-only KAE codes from a JSON structure."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "kae":
                digits = _digits_only(value) if value is not None else ""
                if len(digits) >= MIN_KAE_DIGITS:
                    out.add(digits)
            elif isinstance(value, (dict, list)):
                _collect_kae_codes_from_json(value, out)
    elif isinstance(data, list):
        for item in data:
            _collect_kae_codes_from_json(item, out)


def collect_kae_codes(decision) -> set[str]:
    """
    Collect the budget-classification codes (ΚΑΕ) for a decision.

    Reads ``extra_field_values_json`` and returns every ``kae`` value found
    (``sponsor[i].expenseAmount.kae``, ``amountWithKae[i].kae`` …) as a
    digit-only string, e.g. ``"70.6273.001"`` → ``{"706273001"}``.

    Codes shorter than :data:`MIN_KAE_DIGITS` are ignored — they are too
    likely to collide with ordinary monetary amounts.
    """
    codes: set[str] = set()
    extra = getattr(decision, "extra_field_values_json", None)
    if isinstance(extra, (dict, list)):
        _collect_kae_codes_from_json(extra, codes)
    return codes


def kae_code_in_raw_context(raw_context) -> str | None:
    """
    Return the digit-only KAE code stored next to an amount, if any.

    ``DecisionAmountField.raw_context`` holds the object the amount was
    extracted from (e.g. ``{"amount": 7.06e8, "kae": "70.6273.001"}``), so
    this gives a high-precision, same-container signal.

    NOTE: only safe for rows whose ``raw_context`` is already loaded —
    accessing a deferred JSONField triggers a per-row query.
    """
    if isinstance(raw_context, dict):
        digits = _digits_only(raw_context.get("kae") or "")
        if len(digits) >= MIN_KAE_DIGITS:
            return digits
    return None


def match_non_monetary_value(
    amount: Decimal | None,
    values: set[str],
    raw_span: str | None = None,
) -> str | None:
    """
    Return the non-monetary value that *amount* / *raw_span* corresponds to,
    or None.

    Values may be supplied with or without separators (``"099370337"``,
    ``"70.6273.001"``) — digits are compared leading-zero-insensitively.

    Matches when:
      - the integer part of *amount* equals a value, with zero cents —
        e.g. ``706273001.00`` vs KAE ``70.6273.001``; or
      - *raw_span* is the value formatted as an amount
        (``99.370.337,00``, ``99,370,337.00``, ``99370337,00``,
        ``099.370.337,00`` …).

    A legitimate amount that merely *resembles* a value (e.g. €99,370,338.00
    when the value is ``099370337``) does NOT match.
    """
    if not values:
        return None

    # ── Raw span check (formatting-agnostic) ───────────────────────────
    if raw_span:
        for value in values:
            if _span_digits_equal_value(raw_span, value):
                return value

    # ── Numeric check ──────────────────────────────────────────────────
    if amount is None:
        return None
    if isinstance(amount, str):
        try:
            amount = Decimal(amount)
        except InvalidOperation:
            return None
    if amount != amount.to_integral_value():
        return None  # cents present → cannot be a non-monetary value

    int_val = int(amount.to_integral_value())
    for value in values:
        digits = _digits_only(value)
        if not digits:
            continue
        try:
            if int_val == int(digits):
                return value
        except (ValueError, TypeError):
            continue
    return None


def match_afm_amount(
    amount: Decimal | None,
    afms: set[str],
    raw_span: str | None = None,
) -> str | None:
    """AFM-specialised wrapper around :func:`match_non_monetary_value`."""
    return match_non_monetary_value(amount, afms, raw_span)


def match_kae_amount(
    amount: Decimal | None,
    kaes: set[str],
    raw_span: str | None = None,
) -> str | None:
    """KAE-specialised wrapper around :func:`match_non_monetary_value`."""
    return match_non_monetary_value(amount, kaes, raw_span)


def is_afm_amount(
    amount: Decimal | None,
    afms: set[str],
    raw_span: str | None = None,
) -> bool:
    """Boolean convenience wrapper around :func:`match_afm_amount`."""
    return match_afm_amount(amount, afms, raw_span) is not None


def extract_non_monetary_value_spans(
    text: str, values: set[str], key: str = "value"
) -> list[dict]:
    """
    Find every occurrence of a non-monetary value formatted as an amount in
    *text*.

    Returns a list of dicts: ``{"<key>", "raw", "position"}`` for each hit.
    Handles Greek formatting (``99.370.337,00``), English
    (``99,370,337.00``), bare integer with cents (``99370337,00``) and
    leading-zero forms (``099.370.337,00`` / ``099370337,00``).
    """
    hits: list[dict] = []
    if not text or not values:
        return hits
    for m in _CENTS_AMOUNT_RE.finditer(text):
        for value in values:
            if _span_digits_equal_value(m.group("number"), value):
                hits.append(
                    {key: value, "raw": m.group("number"), "position": m.start()}
                )
                break
    return hits


def extract_afm_amount_spans(text: str, afms: set[str]) -> list[dict]:
    """AFM-specialised wrapper around :func:`extract_non_monetary_value_spans`."""
    return extract_non_monetary_value_spans(text, afms, key="afm")


@dataclass(frozen=True)
class NonMonetaryValue:
    """A recorded amount that is actually a different, non-monetary value."""

    field_id: int
    source_field: str
    parent_key_path: str
    amount: Decimal
    kind: str  # KIND_AFM | KIND_KAE
    matched_value: str  # the value found (digit-only for KAE)
    reason: str  # DISCREPANCY_REASON_AFM | DISCREPANCY_REASON_KAE
    note: str


def collect_non_monetary_values(
    decision,
    amount_fields=None,
    use_raw_context: bool = False,
) -> list[NonMonetaryValue]:
    """
    Return every amount field of *decision* whose value is really a different,
    non-monetary numeric field (currently AFM or KAE).

    This is the DB-only detector (no document text), so it also finds
    historical rows that never ran through the verification pipeline.

    Args:
        decision: The ``Decision`` instance.
        amount_fields: Optional pre-fetched ``DecisionAmountField`` iterable.
        use_raw_context: When True, also test the KAE stored *next to* each
            amount (``DecisionAmountField.raw_context["kae"]``) for a
            same-container match.  Only enable when ``raw_context`` is
            already loaded (a deferred JSONField would cause per-row queries).
    """
    afms = collect_counterpart_afms(decision)
    decision_kaes = collect_kae_codes(decision)
    if not afms and not decision_kaes and not use_raw_context:
        return []

    fields = (
        amount_fields if amount_fields is not None else decision.amount_fields.all()
    )
    anomalies: list[NonMonetaryValue] = []
    for field in fields:
        amount = getattr(field, "amount", None)
        if amount is None:
            continue

        afm = match_afm_amount(amount, afms)
        if afm is not None:
            anomalies.append(
                _make_value(field, amount, KIND_AFM, afm, DISCREPANCY_REASON_AFM)
            )
            continue

        kae = None
        if use_raw_context:
            sibling = kae_code_in_raw_context(
                getattr(field, "raw_context", None)
            )
            if sibling:
                kae = match_kae_amount(amount, {sibling})
        if kae is None and decision_kaes:
            kae = match_kae_amount(amount, decision_kaes)
        if kae is not None:
            anomalies.append(
                _make_value(field, amount, KIND_KAE, kae, DISCREPANCY_REASON_KAE)
            )
    return anomalies


def _make_value(field, amount, kind, matched_value, reason) -> NonMonetaryValue:
    return NonMonetaryValue(
        field_id=field.id,
        source_field=getattr(field, "source_field_name", "") or "",
        parent_key_path=getattr(field, "parent_key_path", "") or "",
        amount=amount,
        kind=kind,
        matched_value=matched_value,
        reason=reason,
        note=(
            build_afm_note(matched_value, amount)
            if kind == KIND_AFM
            else build_kae_note(matched_value, amount)
        ),
    )


def find_afm_amount_fields(
    decision,
    amount_fields=None,
) -> list[tuple]:
    """
    Return ``[(DecisionAmountField, afm), ...]`` for every amount field of
    *decision* whose recorded amount equals a counterpart AFM.

    AFM-only convenience wrapper around :func:`collect_non_monetary_values`;
    prefer the latter for new code (it also covers KAE and returns richer
    ``NonMonetaryValue`` rows).
    """
    fields = (
        amount_fields if amount_fields is not None else decision.amount_fields.all()
    )
    by_id = {field.id: field for field in fields}
    return [
        (by_id[value.field_id], value.matched_value)
        for value in collect_non_monetary_values(
            decision, amount_fields=fields
        )
        if value.kind == KIND_AFM and value.field_id in by_id
    ]


def build_afm_note(afm: str, amount: Decimal | None = None) -> str:
    """Human-readable audit note for an AFM-as-amount hit."""
    amount_str = f"€{amount:,.2f}" if amount is not None else "the amount"
    return (
        f"[AFM-AS-AMOUNT] {amount_str} equals counterpart VAT number (ΑΦΜ) "
        f"{afm} — the amount field holds a non-monetary value; the real "
        f"monetary amount is elsewhere."
    )


def build_kae_note(kae: str, amount: Decimal | None = None) -> str:
    """Human-readable audit note for a KAE-as-amount hit."""
    amount_str = f"€{amount:,.2f}" if amount is not None else "the amount"
    return (
        f"[KAE-AS-AMOUNT] {amount_str} equals the budget classification code "
        f"(ΚΑΕ) {kae} — the amount field holds a non-monetary value; the real "
        f"monetary amount is elsewhere."
    )
