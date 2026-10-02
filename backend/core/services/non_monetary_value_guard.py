"""
Non-monetary-value-as-amount guard.

A class of data-entry errors: the ``expenseAmount`` field holds a value that
actually belongs to a **different, non-monetary numeric field** of the same
Diavgeia API response.  The value exists once, in the wrong field — it is
*not* duplicated; it is misplaced.  It passes for an amount because it is
digit-shaped and therefore looks like a plausible 8-figure euro amount.

Three variants are currently detected:

1. **AFM-as-amount** — the counterpart's VAT number (ΑΦΜ). Canonical case:
   decision ``Ψ0Α74690Β9-52Ρ`` where sponsor AFM ``099370337`` (VIOLAK
   INTERNATIONAL) was recorded as amount ``9.9370337E7`` = €99,370,337.

2. **KAE-as-amount** — the budget classification code (ΚΑΕ, e.g.
   ``70.6273.001``) recorded as the amount, e.g. ``706273001``
   = €706,273,001.  The KAE lives as a *sibling* key of the amount inside the
   same object (``sponsor[i].kae`` next to ``sponsor[i].expenseAmount``).

3. **Self-as-counterpart** — the issuing organization's VAT number appears
    among the decision's counterpart AFMs.  Here the amount itself may be
    perfectly well-formed — what is broken is the *relationship*: the intended
    counterpart is unknown.  So this variant is **decision-level**, never an
    amount marker: the amounts stay trusted, and the counterpart issue is
    reported through :func:`collect_self_counterparts` (detail API, audit
    notes).  Finding the real counterpart is future work.

AFM and KAE are 8-9 digit numbers, so they look like plausible euro amounts
and — since the document text literally contains the value formatted as an
amount (``99.370.337,00``) — the "exact match wins" policy of the amount
verification pipeline **confirms** the bogus value instead of flagging it.

The scope is deliberately open: other non-monetary numeric metadata (e.g. a
protocol number) can be covered by adding a collector plus a
:data:`KIND_*` — see ``collect_non_monetary_values``.  Coverage is currently
limited to the two amount-level variants above.

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


def _digits_only(value: object) -> str:
    """Strip every non-digit character (dots, slashes, spaces) from *value*."""
    return "".join(ch for ch in str(value) if ch.isdigit())


# Top-level keys of ``extra_field_values_json`` that hold a *counterpart*
# (never the issuing org).  Diavgeia has no validation: a counterpart AFM can
# appear under any of these, mislabelled (a company marked ``person``, a
# hospital marked ``unknown`` …), so we harvest AFMs from every known
# counterpart container rather than trusting one shape.  The ``org`` block is
# deliberately excluded — that is the issuer, not a counterpart.
_COUNTERPART_CONTAINER_KEYS = frozenset(
    {
        "sponsor",
        "person",
        "grantee",
        "grantor",
        "contractor",
        "awardedPerson",
        "donationGiver",
        "donationReceiver",
        "employerOrg",
        "primaryOfficer",
        "secondaryOfficer",
        "co_competent",
    }
)


def _harvest_afms(node, out: set[str]) -> None:
    """Recursively collect every ``afm`` value found under *node*."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("afm", "AFM", "afmNumber"):
                afm = str(value or "").strip()
                if afm.isdigit():
                    out.add(afm)
            elif isinstance(value, (dict, list)):
                _harvest_afms(value, out)
    elif isinstance(node, list):
        for item in node:
            _harvest_afms(item, out)


def collect_counterpart_afms(decision) -> set[str]:
    """
    Collect the counterpart (sponsor / supplier / grantee / …) AFMs for a
    decision.

    Sources (union):
      1. ``DecisionEntityRelationship`` rows linked to the decision (any role
         that denotes a counterparty — sponsors, contractors, grantees).
      2. The raw Diavgeia metadata already stored on the decision: every
         ``afm`` under any known counterpart container of
         ``extra_field_values_json`` (see ``_COUNTERPART_CONTAINER_KEYS``).

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

    # ── 2. Raw Diavgeia counterpart metadata ───────────────────────────
    # Harvest AFMs from every known counterpart container.  This mirrors what
    # the extractor persists as DecisionEntityRelationship rows, so the guard
    # also works on decisions whose extraction did not link a relationship —
    # and it does not trust the container's *type* label (a company may be
    # marked ``person``), only that the container is a counterpart.
    extra = getattr(decision, "extra_field_values_json", None)
    if isinstance(extra, dict):
        for key in _COUNTERPART_CONTAINER_KEYS:
            value = extra.get(key)
            if isinstance(value, (dict, list)):
                _harvest_afms(value, afms)

    return afms


def _is_plausible_org_vat(afm: str) -> bool:
    """
    Whether a digit string is a plausible real org VAT (not a placeholder).

    Rejects all-same-digit values (``00000000``, ``999999999`` …): Diavgeia has
    no validation, and these are filler, never a real AFM.  Org ``54566``'s
    ``00000000`` would otherwise prefix-match every ``00000000X`` counterpart.
    """
    return bool(afm) and len(set(afm)) > 1


def collect_org_afm(decision) -> str | None:
    """
    Return the issuing organization's digit-only VAT number, if present and
    plausible.  Placeholder VATs (all-same-digit) are treated as absent.
    """
    organization = getattr(decision, "organization", None)
    afm = _digits_only(getattr(organization, "vat_number", "") or "")
    if not _is_plausible_org_vat(afm):
        return None
    return afm


# Minimum length for an org VAT to be considered a *truncated* AFM worth a
# prefix match.  Shorter values (junk like ``011``, ``-``) are too ambiguous —
# an N-digit prefix matches up to 10^(9-N) distinct 9-digit AFMs.
MIN_PREFIX_ORG_VAT_DIGITS = 8


def _is_self_counterpart(org_afm: str, counterpart_afm: str) -> bool:
    """
    Whether *counterpart_afm* is the issuing org's own AFM.

    Two modes:
      - **exact** — the common case (9-digit VAT == 9-digit counterpart AFM).
      - **truncated prefix** — the org VAT was recorded short (e.g. the
        8-digit ``09000980`` for Παίδων, whose real AFM is ``090009802``).
        The counterpart is a self-reference when it *starts with* the org VAT.
        Gated to org VATs of ≥ :data:`MIN_PREFIX_ORG_VAT_DIGITS` digits so a
        junk short VAT can never prefix-match a real counterpart.

    Placeholder org VATs (all-same-digit, e.g. ``00000000``) never match —
    they are filtered upstream by :func:`collect_org_afm`.
    """
    if not org_afm or not counterpart_afm:
        return False
    if counterpart_afm == org_afm:
        return True
    return (
        len(org_afm) >= MIN_PREFIX_ORG_VAT_DIGITS
        and len(counterpart_afm) > len(org_afm)
        and counterpart_afm.startswith(org_afm)
    )


def collect_self_counterparts(decision) -> set[str]:
    """
    Return counterpart AFMs that improperly equal the issuing org's AFM.

    The returned set holds the **full counterpart AFM** (e.g. ``090009802``),
    not the possibly-truncated org VAT — so the audit trail records the real
    counterpart value.
    """
    org_afm = collect_org_afm(decision)
    if org_afm is None:
        return set()
    return {
        afm
        for afm in collect_counterpart_afms(decision)
        if _is_self_counterpart(org_afm, afm)
    }


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
    Return every amount field of *decision* whose recorded amount is a
    non-monetary value (AFM / KAE).

    This is the DB-only detector (no document text), so it also finds
    historical rows that never ran through the verification pipeline.

    Self-as-counterpart is deliberately **not** an amount anomaly: there the
    amount is believed and only the counterpart is unknown, so it is
    decision-level state — see :func:`collect_self_counterparts`.

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
            sibling = kae_code_in_raw_context(getattr(field, "raw_context", None))
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
    note = (
        build_afm_note(matched_value, amount)
        if kind == KIND_AFM
        else build_kae_note(matched_value, amount)
    )
    return NonMonetaryValue(
        field_id=field.id,
        source_field=getattr(field, "source_field_name", "") or "",
        parent_key_path=getattr(field, "parent_key_path", "") or "",
        amount=amount,
        kind=kind,
        matched_value=matched_value,
        reason=reason,
        note=note,
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
        for value in collect_non_monetary_values(decision, amount_fields=fields)
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


def build_self_counterpart_note(afm: str) -> str:
    """Human-readable audit note for an issuing org as its own counterpart."""
    return (
        f"[SELF-AS-COUNTERPART] Counterpart VAT number (ΑΦΜ) {afm} equals "
        "the issuing organization's VAT number; the intended counterpart and "
        "real amount require human review."
    )
