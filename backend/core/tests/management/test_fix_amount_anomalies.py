"""
Tests for the ``fix_amount_anomalies`` management command — the *treatment*
half of the non-monetary-value guard.

The command writes only the invalid-amount marker (never ``verified_amount``),
is dry-run by default, and is reversible with ``--clear``.
"""

import io
import json

import pytest
from django.core.management import call_command

pytestmark = pytest.mark.django_db

# Sponsor AFM recorded as the amount — the canonical Ψ0Α74690Β9-52Ρ shape.
SPONSOR_AFM = "099370337"
MISPLACED_AFM_AMOUNT = "99370337.00"

# Budget KAE (>= 6 digits) recorded as the amount — the ΨΡΙ0Ω12-0ΙΘ shape.
SPONSOR_KAE = "70.6273.001"
MISPLACED_KAE_AMOUNT = "706273001.00"


def _make_decision(*, amount: str, afm: str | None = None, kae: str | None = None):
    """Build a decision whose amount field holds a non-monetary value."""
    from decimal import Decimal

    from conftest import DecisionAmountFieldFactory, DecisionFactory

    sponsor = {
        "expenseAmount": {"amount": float(amount), "currency": "EUR"},
        "sponsorAFMName": {"afm": afm} if afm else None,
    }
    if kae is not None:
        sponsor["kae"] = kae

    decision = DecisionFactory(
        extra_field_values_json={"sponsor": [sponsor]},
    )
    field = DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="sponsor[0].expenseAmount",
        source_field_name="expenseAmount",
        amount=Decimal(amount),
    )
    return decision, field


def _run(*args):
    out = io.StringIO()
    call_command("fix_amount_anomalies", *args, stdout=out)
    return out.getvalue()


# ── Dry run ──────────────────────────────────────────────────────────────────


class TestDryRun:
    def test_dry_run_writes_nothing(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        output = _run("--ada", decision.ada)

        field.refresh_from_db()
        assert field.invalid_amount_reason is None
        assert field.invalid_amount_value is None
        assert field.invalid_amount_flagged_at is None
        assert "DRY RUN" in output
        assert "would_flag" or "· new" in output

    def test_dry_run_detects_the_anomaly(self):
        decision, _ = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        output = _run("--ada", decision.ada)

        assert SPONSOR_AFM in output
        assert "AFM" in output


# ── Apply ────────────────────────────────────────────────────────────────────


class TestApply:
    def test_apply_sets_the_marker(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        _run("--ada", decision.ada, "--apply")

        field.refresh_from_db()
        assert field.invalid_amount_reason == "afm_as_amount"
        assert field.invalid_amount_value == SPONSOR_AFM
        assert field.invalid_amount_flagged_at is not None

    def test_apply_never_writes_verified_amount(self):
        """The real amount is unknown — it must NOT be persisted as money."""
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        _run("--ada", decision.ada, "--apply")

        field.refresh_from_db()
        assert field.verified_amount is None
        assert field.amount_verified_at is None

    def test_apply_handles_kae(self):
        decision, field = _make_decision(amount=MISPLACED_KAE_AMOUNT, kae=SPONSOR_KAE)

        _run("--ada", decision.ada, "--apply")

        field.refresh_from_db()
        assert field.invalid_amount_reason == "kae_as_amount"
        assert field.invalid_amount_value == "706273001"

    def test_kind_filter_excludes_other_kinds(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        _run("--ada", decision.ada, "--kind", "kae", "--apply")

        field.refresh_from_db()
        assert field.invalid_amount_reason is None

    def test_output_written(self, tmp_path):
        decision, _ = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)
        out_file = tmp_path / "flagged.json"

        _run("--ada", decision.ada, "--apply", "--output", str(out_file))

        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["applied"] is True
        assert payload["mode"] == "flag"
        assert payload["decisions_changed"] == 1
        assert payload["fields_written"] == 1


# ── Idempotency ──────────────────────────────────────────────────────────────


class TestIdempotency:
    def test_rerun_reports_already_flagged(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)

        _run("--ada", decision.ada, "--apply")
        field.refresh_from_db()
        first_flagged_at = field.invalid_amount_flagged_at

        output = _run("--ada", decision.ada, "--apply")

        field.refresh_from_db()
        assert "✓ flagged" in output
        # Same reason/value; the timestamp is refreshed on a re-run.
        assert field.invalid_amount_reason == "afm_as_amount"
        assert field.invalid_amount_value == SPONSOR_AFM
        assert field.invalid_amount_flagged_at >= first_flagged_at

    def test_only_new_skips_fully_flagged_decisions(self):
        decision, _ = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)
        _run("--ada", decision.ada, "--apply")

        output = _run("--ada", decision.ada, "--only-new", "--apply")

        assert decision.ada not in output


# ── Clear (rollback) ─────────────────────────────────────────────────────────


class TestClear:
    def test_clear_dry_run_writes_nothing(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)
        _run("--ada", decision.ada, "--apply")

        _run("--ada", decision.ada, "--clear")

        field.refresh_from_db()
        assert field.invalid_amount_reason == "afm_as_amount"

    def test_clear_apply_removes_the_marker(self):
        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)
        _run("--ada", decision.ada, "--apply")

        _run("--ada", decision.ada, "--clear", "--apply")

        field.refresh_from_db()
        assert field.invalid_amount_reason is None
        assert field.invalid_amount_value is None
        assert field.invalid_amount_flagged_at is None

    def test_clear_does_not_touch_verified_amount(self):
        from decimal import Decimal

        decision, field = _make_decision(amount=MISPLACED_AFM_AMOUNT, afm=SPONSOR_AFM)
        field.verified_amount = Decimal("123.45")
        field.save(update_fields=["verified_amount"])

        _run("--ada", decision.ada, "--clear", "--apply")

        field.refresh_from_db()
        assert field.verified_amount == Decimal("123.45")


# ── No-ops ───────────────────────────────────────────────────────────────────


class TestNoAnomaly:
    def test_clean_decision_is_untouched(self):
        from decimal import Decimal

        from conftest import DecisionAmountFieldFactory, DecisionFactory

        # A legitimate amount that merely RESEMBLES the AFM (differ by 1 euro)
        # must not match: only exact equality counts.
        decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [
                    {
                        "expenseAmount": {"amount": 99370338.0, "currency": "EUR"},
                        "sponsorAFMName": {"afm": SPONSOR_AFM},
                    }
                ]
            }
        )
        field = DecisionAmountFieldFactory(
            decision=decision,
            parent_key_path="sponsor[0].expenseAmount",
            source_field_name="expenseAmount",
            amount=Decimal("99370338.00"),
        )

        _run("--ada", decision.ada, "--apply")

        field.refresh_from_db()
        assert field.invalid_amount_reason is None
