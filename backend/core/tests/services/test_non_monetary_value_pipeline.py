"""
End-to-end tests for the non-monetary-value-as-amount guard using **real
Diavgeia API payloads**.

Unlike the synthetic factory-based tests in ``test_non_monetary_value_guard.py``,
these cases take the ``extraFieldValues`` object straight from the Diavgeia API
response and push it through the *real* pipeline:

    raw API JSON
      → Decision(extra_field_values_json=...)
      → EntityAmountExtractionService.extract_from_decision()   (real)
      → DecisionAmountField / DecisionEntityRelationship rows
      → AmountVerificationService.verify_decision()             (guard)
      → AmountCorrectionService.correct_decision()              (guard)
      → collect_non_monetary_values() / find_amount_anomalies

## Adding a new case (no code changes needed)

Drop the raw API response as ``core/tests/data/non_monetary_value_cases/<name>.json``.
That's it.  The payloads are auto-discovered and the expected anomalies are
re-derived independently from the raw JSON by :func:`expected_anomalies`
(see its docstring) — so every new payload automatically gets coverage across
extraction, verification, correction and discovery.

Discovery is intentionally broad: any ``expenseAmount`` in the payload whose
value equals a sibling ``sponsorAFMName.afm`` or ``kae`` is expected to be
flagged.  Values with cents, and KAEs shorter than 6 digits, are not.

Real cases currently committed:

- ``afm_as_amount_raw.json`` — ADA ``Ψ0Α74690Β9-52Ρ``. Sponsor AFM
  ``099370337`` (VIOLAK INTERNATIONAL) recorded as ``expenseAmount``
  ``9.9370337E7`` = €99,370,337.00.
- ``afm_petridis_raw.json`` — ADA ``ΨΛΘΒΟΡΡ2-ΖΤΞ``. Sponsor AFM
  ``801380053`` (ΠΕΤΡΙΔΗΣ Θ ΣΠΥΡΙΔΩΝ ΚΑΙ ΣΙΑ Ε Ε) recorded as
  ``expenseAmount`` ``8.01380053E8`` = €801,380,053.00.
- ``kae_as_amount_raw.json`` — ADA ``Ψ0ΩΣΟΡΓΠ-Ε45``. Sponsor ``sponsor[0]``
  has KAE ``26.01.00.0000`` recorded as ``expenseAmount`` ``2.601E9``
  = €2,601,000,000.00.
- ``kae_deh_raw.json`` — ADA ``ΨΡΙ0Ω12-0ΙΘ``. Sponsor ``sponsor[6]`` has
  KAE ``70.6273.001`` recorded as ``expenseAmount`` ``7.06273001E8``
  = €706,273,001.00; the other six sponsors are correct.

The document text supplied to the verification stage is *derived from the
value* (e.g. ``99.370.337,00``) — it reproduces the "the amount field holds the
code, and the document shows that code as an amount" situation that fools the
exact-match policy.  The PDF text itself is not captured by the API.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from core.services.non_monetary_value_guard import (
    DISCREPANCY_REASON_AFM,
    DISCREPANCY_REASON_KAE,
    KIND_AFM,
    KIND_KAE,
    collect_non_monetary_values,
)
from core.services.amount_correction_service import AmountCorrectionService
from core.services.amount_verification_service import AmountVerificationService
from core.services.entity_amount_extraction_service import (
    EntityAmountExtractionService,
)

pytestmark = pytest.mark.django_db

DATA_DIR = Path(__file__).parent.parent / "data" / "non_monetary_value_cases"

# Independent ground-truth constants (deliberately NOT imported from the guard,
# so this stays a genuine cross-check rather than a tautology).
MIN_KAE_DIGITS = 6


def _payload_files() -> list[Path]:
    return sorted(DATA_DIR.glob("*.json"))


def _load(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _efv(payload: dict) -> dict:
    """Return the extra-field-values object, whatever the payload shape."""
    return (
        payload.get("extraFieldValues")
        or payload.get("extra_field_values_json")
        or {}
    )


def _digits(value) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def expected_anomalies(payload: dict) -> set[tuple[str, str, str]]:
    """
    Independently derive the expected anomalies from a raw API payload.

    Walks ``extraFieldValues.sponsor[*]`` and flags every ``expenseAmount``
    whose whole-euro value equals either the sibling ``sponsorAFMName.afm`` or
    the sibling ``kae`` (≥ :data:`MIN_KAE_DIGITS` digits).

    Returns a set of ``(kind, parent_key_path, matched_value)`` tuples:
      - ``kind`` is ``"afm"`` or ``"kae"``
      - ``parent_key_path`` is ``sponsor[i]``
      - ``matched_value`` is the AFM or the digit-only KAE

    This is a *deliberately naive* reimplementation of the spec: it reads the
    raw JSON directly and never touches ``Decision`` rows or guard helpers.
    """
    expected: set[tuple[str, str, str]] = set()
    for i, sponsor in enumerate(_efv(payload).get("sponsor") or []):
        if not isinstance(sponsor, dict):
            continue
        amount = (sponsor.get("expenseAmount") or {}).get("amount")
        if amount is None or float(amount) != int(amount):
            continue  # missing, or has cents → cannot be a non-monetary value
        int_value = int(amount)

        afm = str((sponsor.get("sponsorAFMName") or {}).get("afm") or "").strip()
        if afm.isdigit() and int_value == int(afm):
            expected.add((KIND_AFM, f"sponsor[{i}]", afm))
            continue

        kae_digits = _digits(sponsor.get("kae") or "")
        if len(kae_digits) >= MIN_KAE_DIGITS and int_value == int(kae_digits):
            expected.add((KIND_KAE, f"sponsor[{i}]", kae_digits))
    return expected


def greek_amount_format(int_value: int) -> str:
    """``99370337`` → ``99.370.337,00`` (the way it appears in document text)."""
    return f"{int_value:,}".replace(",", ".") + ",00"


# ── Parametrisation over every committed payload ─────────────────────────────

CASES = [
    pytest.param(path, id=path.stem) for path in _payload_files()
]


def _build_decision(payload: dict):
    """Create a Decision from a raw payload and run the real extraction."""
    from conftest import DecisionFactory

    ada = payload.get("ada") or payload.get("decision_id") or "TEST-ADA"
    decision = DecisionFactory(ada=ada, extra_field_values_json=_efv(payload))
    EntityAmountExtractionService().extract_from_decision(decision)
    return decision


def _add_text(decision, text: str):
    from conftest import DocumentExtractionFactory

    DocumentExtractionFactory(decision=decision, raw_text=text)
    return decision


@pytest.fixture
def guard_text_and_reason(request):
    """
    For the selected payload: build the Decision, attach derived text, and
    return ``(decision, expected_reason)``.

    The text quotes the (first) matched value formatted as an amount, which is
    what makes the bogus value look "confirmed" to the exact-match policy.
    """
    payload = _load(request.param)
    decision = _build_decision(payload)
    expected = expected_anomalies(payload)
    assert expected, f"{request.param.name} has no expected anomalies"

    kind, _path, value = sorted(expected)[0]
    text = (
        "Εγκρίνεται δαπάνη ποσού "
        f"{greek_amount_format(int(_digits(value)))} €."
    )
    _add_text(decision, text)

    reason = (
        DISCREPANCY_REASON_AFM if kind == KIND_AFM else DISCREPANCY_REASON_KAE
    )
    return decision, reason


# ── Extraction matches the independently derived expectation ─────────────────


@pytest.mark.parametrize("path", CASES, indirect=False)
def test_payload_is_well_formed(path):
    payload = _load(path)
    assert payload.get("ada")
    assert _efv(payload).get("sponsor") is not None


@pytest.mark.parametrize("path", CASES)
def test_extraction_preserves_amounts(path):
    payload = _load(path)
    decision = _build_decision(payload)

    payload_amounts = [
        Decimal(str((sp["expenseAmount"] or {}).get("amount")))
        for sp in _efv(payload).get("sponsor") or []
        if isinstance(sp, dict) and (sp.get("expenseAmount") or {}).get("amount")
    ]
    extracted = {f.amount for f in decision.amount_fields.all()}
    for amount in payload_amounts:
        assert amount in extracted, f"{path.stem}: {amount} not extracted"


@pytest.mark.parametrize("path", CASES)
def test_guard_matches_independent_derivation(path):
    """The guard's DB-only detector must agree with the naive spec."""
    payload = _load(path)
    decision = _build_decision(payload)

    got = {
        (v.kind, v.parent_key_path, v.matched_value)
        for v in collect_non_monetary_values(
            decision, use_raw_context=True
        )
    }
    assert got == expected_anomalies(payload)


# ── Full pipeline: flagged, never confirmed, never written ───────────────────


@pytest.mark.parametrize("guard_text_and_reason", CASES, indirect=True)
def test_verification_flags_not_confirms(guard_text_and_reason):
    decision, expected_reason = guard_text_and_reason
    result = AmountVerificationService().verify_decision(decision, method="regex")

    assert result["status"] == "completed"
    assert result["has_discrepancy"] is True
    assert result["discrepancy_reason"] == expected_reason

    from core.models.document_analysis import (
        TextProcessResolution,
        TextProcessRun,
    )

    run = TextProcessRun.objects.get(
        extraction=decision.text_extraction, process="amount"
    )
    assert run.meta["discrepancy_reason"] == expected_reason
    assert "[AFM-AS-AMOUNT]" in run.meta["discrepancy_note"] or (
        "[KAE-AS-AMOUNT]" in run.meta["discrepancy_note"]
    )

    resolution = TextProcessResolution.objects.get(
        decision=decision, process="amount"
    )
    assert resolution.has_discrepancy is True


@pytest.mark.parametrize("guard_text_and_reason", CASES, indirect=True)
def test_correction_never_writes_value(guard_text_and_reason):
    decision, expected_reason = guard_text_and_reason
    result = AmountCorrectionService(threshold=Decimal("1")).correct_decision(
        decision
    )

    assert result["status"] == expected_reason
    assert result["discrepancy_reason"] == expected_reason
    assert result["matched_values"]

    decision.refresh_from_db()
    for field in decision.amount_fields.all():
        assert field.verified_amount is None
        assert field.amount_verified_at is None


@pytest.mark.parametrize("guard_text_and_reason", CASES, indirect=True)
def test_grouped_path_flags_too(guard_text_and_reason):
    decision, expected_reason = guard_text_and_reason
    result = AmountVerificationService().verify_with_grouped(decision)
    assert result["status"] == "completed"
    assert result["discrepancy_reason"] == expected_reason


# ── Discovery command over every payload ─────────────────────────────────────


@pytest.mark.parametrize("path", CASES)
def test_discovery_command_finds_every_case(path):
    import io

    from django.core.management import call_command

    payload = _load(path)
    decision = _build_decision(payload)
    expected = expected_anomalies(payload)

    out = io.StringIO()
    call_command(
        "find_amount_anomalies", "--ada", decision.ada, stdout=out
    )
    output = out.getvalue()

    assert decision.ada in output
    for _kind, _parent, value in expected:
        assert value in output
