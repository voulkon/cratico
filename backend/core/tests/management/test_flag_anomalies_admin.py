"""
Admin integration tests for the non-monetary (AFM/KAE) marker workflow:

  - ``NonMonetaryAnomalyForm`` / ``batch_flag_anomalies_view`` (runs the
    ``fix_amount_anomalies`` management command verbatim),
  - ``flagged_amounts_pool_view`` + ``clear_flagged_amount_view``,
  - ``DecisionAdmin.flag_non_monetary_amounts`` / ``clear_non_monetary_amounts``
    list actions.

The marker never touches ``verified_amount`` — the real amount is unknown.
"""

from decimal import Decimal

import pytest
from django.urls import reverse

from conftest import DecisionAmountFieldFactory, DecisionFactory

pytestmark = pytest.mark.django_db

SPONSOR_AFM = "099370337"
MISPLACED_AMOUNT = Decimal("99370337.00")

BATCH_URL = "admin:decision_batch_flag_anomalies"
POOL_URL = "admin:decision_flagged_amounts_pool"


def _flagged_case():
    """A decision whose amount equals its sponsor's AFM (the Ψ0Α74690Β9-52Ρ shape)."""
    decision = DecisionFactory(
        extra_field_values_json={
            "sponsor": [{"sponsorAFMName": {"afm": SPONSOR_AFM}}]
        }
    )
    field = DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="sponsor[0].expenseAmount",
        source_field_name="expenseAmount",
        amount=MISPLACED_AMOUNT,
    )
    return decision, field


def _pre_flag(field):
    """Write the marker directly, as the guard would."""
    field.invalid_amount_reason = "afm_as_amount"
    field.invalid_amount_value = SPONSOR_AFM
    field.save(
        update_fields=["invalid_amount_reason", "invalid_amount_value"]
    )


@pytest.fixture
def staff_client(client, admin_user):
    client.force_login(admin_user)
    return client


def _form_data(**overrides):
    data = {
        "kind": "all",
        "min_amount": "100000",
        "max_amount": "100000000000",
        "limit": "100",
        "clear": "",
    }
    data.update(overrides)
    return data


# ── Batch find & flag ────────────────────────────────────────────────────────


class TestBatchFlagView:
    def test_get_renders(self, staff_client):
        resp = staff_client.get(reverse(BATCH_URL))
        assert resp.status_code == 200

    def test_dry_run_writes_nothing(self, staff_client):
        _, field = _flagged_case()

        resp = staff_client.post(reverse(BATCH_URL), _form_data(dry_run="on"))

        assert resp.status_code == 200
        field.refresh_from_db()
        assert field.invalid_amount_reason is None
        assert field.invalid_amount_value is None

    def test_apply_writes_marker(self, staff_client):
        _, field = _flagged_case()

        resp = staff_client.post(reverse(BATCH_URL), _form_data())

        assert resp.status_code == 200
        field.refresh_from_db()
        assert field.invalid_amount_reason == "afm_as_amount"
        assert field.invalid_amount_value == SPONSOR_AFM
        assert field.invalid_amount_flagged_at is not None
        # The real amount is unknown — never persisted as money.
        assert field.verified_amount is None

    def test_kind_filter_excludes_other_kinds(self, staff_client):
        _, field = _flagged_case()

        staff_client.post(reverse(BATCH_URL), _form_data(kind="kae"))

        field.refresh_from_db()
        assert field.invalid_amount_reason is None

    def test_clear_apply_removes_marker(self, staff_client):
        _, field = _flagged_case()
        _pre_flag(field)

        staff_client.post(reverse(BATCH_URL), _form_data(clear="on"))

        field.refresh_from_db()
        assert field.invalid_amount_reason is None
        assert field.invalid_amount_value is None


# ── Flagged pool ─────────────────────────────────────────────────────────────


class TestFlaggedPool:
    def test_lists_flagged_decision(self, staff_client):
        decision, field = _flagged_case()
        _pre_flag(field)

        resp = staff_client.get(reverse(POOL_URL))

        assert resp.status_code == 200
        assert decision.ada.encode() in resp.content

    def test_clear_view_clears_marker(self, staff_client):
        decision, field = _flagged_case()
        _pre_flag(field)

        resp = staff_client.post(
            reverse("admin:decision_flagged_amounts_clear", args=[decision.id])
        )

        assert resp.status_code == 302
        field.refresh_from_db()
        assert field.invalid_amount_reason is None


# ── List actions ─────────────────────────────────────────────────────────────


class TestAdminActions:
    def _run_action(self, staff_client, action, decision):
        return staff_client.post(
            reverse("admin:core_decision_changelist"),
            {
                "action": action,
                "_selected_action": [str(decision.pk)],
                "select_across": "0",
                "index": "0",
            },
            follow=True,
        )

    def test_flag_action_writes_marker(self, staff_client):
        decision, field = _flagged_case()

        self._run_action(staff_client, "flag_non_monetary_amounts", decision)

        field.refresh_from_db()
        assert field.invalid_amount_reason == "afm_as_amount"
        assert field.invalid_amount_value == SPONSOR_AFM

    def test_clear_action_removes_marker(self, staff_client):
        decision, field = _flagged_case()
        _pre_flag(field)

        self._run_action(staff_client, "clear_non_monetary_amounts", decision)

        field.refresh_from_db()
        assert field.invalid_amount_reason is None
