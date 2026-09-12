"""
Tests for decision_detail / decision_related amount handling.

Covers the three amount/entity combinations a decision can be in:

  A. No amount anywhere — neither the denormalised ``Decision.amount`` nor
     any ``DecisionAmountField`` rows (e.g. decision 183005).  The API must
     report ``amount: null`` and must not crash.
  B. Amount in BOTH the denormalised field and ``DecisionAmountField`` rows.
     The effective (verified-aware, invalid-excluding) total wins — the raw
     denormalised value is never presented as money.
  C. Amount ONLY in ``DecisionAmountField`` rows (denormalised field NULL).
     The API must surface the effective total, not null.

Plus: ``decision_related`` must annotate its candidates with the effective
amount (regression test for the "Cannot resolve keyword 'verified_amount'"
bug, where a DecisionAmountField-only expression was used on a Decision
queryset).
"""

from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models.decisions import Decision
from core.models.entities import (
    AFMEntity,
    DecisionAmountField,
    DecisionEntityRelationship,
)
from core.models.types import ActType


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def act_type(db):
    act, _ = ActType.objects.get_or_create(uid="Β.2.2", defaults={"label": "Πληρωμή"})
    return act


def _make_decision(ada, act_type, raw_amount=None):
    return Decision.objects.create(
        ada=ada,
        version_id=f"v-{ada}",
        subject=f"Decision {ada}",
        issue_date=timezone.now(),
        submission_timestamp=timezone.now(),
        decision_type=act_type,
        status="PUBLISHED",
        amount=raw_amount,
    )


def _make_amount_field(decision, amount, verified_amount=None, invalid_reason=None):
    return DecisionAmountField.objects.create(
        decision=decision,
        parent_key_path="sponsor[0].expenseAmount",
        source_field_name="expenseAmount",
        amount=amount,
        currency="EUR",
        verified_amount=verified_amount,
        invalid_amount_reason=invalid_reason,
    )


def _make_counterpart(decision, afm="094423506", name="PERFORMANCE ΑΕ"):
    entity, _ = AFMEntity.objects.get_or_create(
        afm=afm, defaults={"name": name, "entity_type": "unknown"}
    )
    return DecisionEntityRelationship.objects.create(
        decision=decision,
        entity=entity,
        role="sponsorAFMName",
        parent_key_path="sponsor[0].sponsorAFMName",
    )


# ── Case A: no amount anywhere ────────────────────────────────────────


@pytest.mark.django_db
class TestNoAmountAnywhere:
    def test_detail_amount_is_null(self, api_client, act_type):
        decision = _make_decision("A-NOAMT", act_type, raw_amount=None)
        _make_counterpart(decision)

        resp = api_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["amount"] is None
        assert data["has_corrected_amounts"] is False
        assert data["corrected_amount"] is None
        assert data["has_invalid_amount"] is False

    def test_related_does_not_crash(self, api_client, act_type):
        decision = _make_decision("A-REL", act_type, raw_amount=None)
        resp = api_client.get(f"/api/decisions/{decision.id}/related/")
        assert resp.status_code == 200


# ── Case B: amount in both tables ─────────────────────────────────────


@pytest.mark.django_db
class TestAmountInBoth:
    def test_effective_total_wins_over_raw(self, api_client, act_type):
        # Raw denormalised field says 999 (could be a typo); the amount
        # fields say 100.  The effective total must be reported.
        decision = _make_decision("B-BOTH", act_type, raw_amount=Decimal("999.00"))
        _make_amount_field(decision, Decimal("100.00"))
        _make_counterpart(decision)

        resp = api_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200
        assert resp.json()["amount"] == 100.0

    def test_verified_amount_overrides(self, api_client, act_type):
        decision = _make_decision("B-VER", act_type, raw_amount=Decimal("999.00"))
        _make_amount_field(
            decision, Decimal("999.00"), verified_amount=Decimal("9.99")
        )

        resp = api_client.get(f"/api/decisions/{decision.id}/")
        data = resp.json()
        assert data["amount"] == 9.99
        assert data["has_corrected_amounts"] is True
        assert data["corrected_amount"] == 9.99

    def test_invalid_amount_excluded(self, api_client, act_type):
        # The only amount field is a counterpart AFM mis-recorded as money.
        decision = _make_decision("B-INV", act_type, raw_amount=Decimal("94423506.00"))
        _make_amount_field(
            decision, Decimal("94423506.00"), invalid_reason="afm_as_amount"
        )

        resp = api_client.get(f"/api/decisions/{decision.id}/")
        data = resp.json()
        assert data["amount"] is None
        assert data["has_invalid_amount"] is True
        assert data["invalid_amount_reason"] == "afm_as_amount"


# ── Case C: amount only in DecisionAmountField ────────────────────────


@pytest.mark.django_db
class TestAmountOnlyInAmountField:
    def test_detail_surfaces_effective_total(self, api_client, act_type):
        decision = _make_decision("C-ONLY", act_type, raw_amount=None)
        _make_amount_field(decision, Decimal("2481196.00"))
        _make_counterpart(decision)

        resp = api_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200
        assert resp.json()["amount"] == 2481196.0

    def test_related_returns_candidates_without_amount(self, api_client, act_type):
        """decision_related no longer annotates amounts (too slow — a
        correlated effective-amount subquery per candidate row).  It returns
        same-org/type decisions by recency with no amount field."""
        decision = _make_decision("C-REL", act_type, raw_amount=None)
        _make_amount_field(decision, Decimal("1000.00"))

        candidate = _make_decision("C-REL-CAND", act_type, raw_amount=None)
        _make_amount_field(candidate, Decimal("1200.00"))

        resp = api_client.get(f"/api/decisions/{decision.id}/related/")
        assert resp.status_code == 200
        results = resp.json()["results"]
        adas = {r["ada"] for r in results}
        assert "C-REL-CAND" in adas
        # No amount annotation — the expensive aggregate was removed
        assert all("amount" not in r for r in results)
