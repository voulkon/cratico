"""
Tests for the banded direct-assignment leaderboards
(``analytics_precalc/banded_direct_assignments.py``).

These cover the €30k–€38k band semantics (per-decision linked money-received
total), the frequency ranking, the receiver/giver mirror, and the exact
band-boundary behaviour.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from conftest import (
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
)
from core.models.decision_classification import DecisionClassification
from core.models.entities import DecisionEntityRelationship
from core.services.analytics_precalc.banded_direct_assignments import (
    BAND_MAX,
    BAND_MIN,
    compute_top_banded_da_givers,
    compute_top_banded_da_receivers,
    in_band,
)

# A role that counts as "money received" by an entity.
RECEIVED_ROLE = "grantee"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _window():
    """Return a (start_dt, end_dt, start_str, end_str) window covering today."""
    today = timezone.now().date()
    start_d = today - timedelta(days=30)
    start_dt = timezone.make_aware(
        timezone.datetime.combine(start_d, timezone.datetime.min.time())
    )
    end_dt = timezone.make_aware(
        timezone.datetime.combine(today, timezone.datetime.max.time())
    )
    return start_dt, end_dt, start_d.isoformat(), today.isoformat()


def _banded_decision(
    *,
    ada,
    entity,
    organization,
    decision_type,
    amount,
    role=RECEIVED_ROLE,
    direct=True,
    verified_amount=None,
):
    """Create a decision with one linked amount field of ``amount``."""
    decision = DecisionFactory(
        ada=ada, organization=organization, decision_type=decision_type
    )
    DecisionClassification.objects.create(
        decision=decision, is_direct_assignment=direct
    )
    relationship = DecisionEntityRelationshipFactory(
        decision=decision, entity=entity, role=role
    )
    DecisionAmountFieldFactory(
        decision=decision,
        amount=amount,
        verified_amount=verified_amount,
        associated_relationship=relationship,
    )
    return decision, relationship


def _call_receivers():
    return compute_top_banded_da_receivers(**_window_kwargs())


def _call_givers():
    return compute_top_banded_da_givers(**_window_kwargs())


def _window_kwargs():
    start_dt, end_dt, start_str, end_str = _window()
    return dict(
        start_dt=start_dt,
        end_dt=end_dt,
        start_date_str=start_str,
        end_date_str=end_str,
        limit=50,
        offset=0,
    )


# ---------------------------------------------------------------------------
# in_band predicate
# ---------------------------------------------------------------------------

class TestInBand:
    @pytest.mark.parametrize(
        "value,expected",
        [
            (Decimal("30000"), True),
            (Decimal("38000"), True),
            (Decimal("34000"), True),
            (Decimal("29999.99"), False),
            (Decimal("38000.01"), False),
            ("33000", True),
            (33000, True),
            (None, False),
            ("not-a-number", False),
        ],
    )
    def test_in_band(self, value, expected):
        assert in_band(value) is expected


# ---------------------------------------------------------------------------
# Receivers leaderboard
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTopBandedDaReceivers:
    def test_ranks_entities_by_frequency(self, decision_type, organization):
        from conftest import AFMEntityFactory

        frequent = AFMEntityFactory(afm="111111111", name="FREQUENT")
        rare = AFMEntityFactory(afm="222222222", name="RARE")

        for i in range(3):
            _banded_decision(
                ada=f"FREQ{i}",
                entity=frequent,
                organization=organization,
                decision_type=decision_type,
                amount=Decimal("33000"),
            )
        _banded_decision(
            ada="RARE0",
            entity=rare,
            organization=organization,
            decision_type=decision_type,
            amount=Decimal("35000"),
        )

        data = _call_receivers()
        results = data["results"]

        assert data["metric"].startswith("Most")
        assert data["band"]["min"] == "30000"
        assert data["band"]["max"] == "38000"
        assert [r["entity_afm"] for r in results] == ["111111111", "222222222"]
        assert results[0]["decision_count"] == 3
        assert results[0]["rank"] == 1
        assert results[1]["decision_count"] == 1
        assert data["pagination"]["total_count"] == 2
        assert data["summary"]["unique_entities"] == 2
        assert data["summary"]["total_banded_assignments"] == 4

    def test_excludes_decisions_outside_band(self, decision_type, organization, afm_entity):
        afm_entity.afm = "333333333"
        afm_entity.save()

        _banded_decision(
            ada="BELOW", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal("29999.99"),
        )
        _banded_decision(
            ada="ABOVE", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal("38000.01"),
        )

        data = _call_receivers()
        assert data["results"] == []
        assert data["pagination"]["total_count"] == 0

    @pytest.mark.parametrize("amount", ["30000", "38000"])
    def test_band_boundaries_are_inclusive(self, decision_type, organization, afm_entity, amount):
        afm_entity.afm = "444444444"
        afm_entity.save()
        _banded_decision(
            ada=f"EDGE{amount}", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal(amount),
        )
        data = _call_receivers()
        assert len(data["results"]) == 1

    def test_excludes_non_direct_assignments(self, decision_type, organization, afm_entity):
        afm_entity.afm = "555555555"
        afm_entity.save()
        _banded_decision(
            ada="NOTDIRECT", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal("33000"), direct=False,
        )
        data = _call_receivers()
        assert data["results"] == []

    def test_excludes_money_paid_roles(self, decision_type, organization, afm_entity):
        """A grantor (money PAID) must not count as a receiver."""
        afm_entity.afm = "666666666"
        afm_entity.save()
        _banded_decision(
            ada="GRANTOR", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal("33000"), role="grantor",
        )
        data = _call_receivers()
        assert data["results"] == []

    def test_uses_verified_amount_for_band(self, decision_type, organization, afm_entity):
        """A raw amount below the band but a verified amount inside it counts."""
        afm_entity.afm = "777777777"
        afm_entity.save()
        _banded_decision(
            ada="VERIFIED", entity=afm_entity, organization=organization,
            decision_type=decision_type, amount=Decimal("25000"),
            verified_amount=Decimal("33000"),
        )
        data = _call_receivers()
        assert len(data["results"]) == 1
        assert data["results"][0]["banded_amount_sum"] == "33000.00"


# ---------------------------------------------------------------------------
# Givers leaderboard (the mirror)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTopBandedDaGivers:
    def test_ranks_organizations_by_frequency(self, decision_type, afm_entity):
        from conftest import OrganizationFactory

        busy = OrganizationFactory(uid="900000001", label="BUSY ORG")
        quiet = OrganizationFactory(uid="900000002", label="QUIET ORG")

        for i in range(4):
            _banded_decision(
                ada=f"BUSY{i}", entity=afm_entity, organization=busy,
                decision_type=decision_type, amount=Decimal("32000"),
            )
        _banded_decision(
            ada="QUIET0", entity=afm_entity, organization=quiet,
            decision_type=decision_type, amount=Decimal("36000"),
        )

        data = _call_givers()
        results = data["results"]

        assert data["metric"].startswith("Most")
        assert [r["organization_uid"] for r in results] == [
            "900000001",
            "900000002",
        ]
        assert results[0]["decision_count"] == 4
        assert results[1]["decision_count"] == 1
        assert data["pagination"]["total_count"] == 2
        assert data["summary"]["unique_organizations"] == 2
        assert data["summary"]["total_banded_assignments"] == 5

    def test_ignores_out_of_band_and_non_direct(self, decision_type, afm_entity):
        from conftest import OrganizationFactory

        org = OrganizationFactory(uid="900000003", label="ORG")
        _banded_decision(
            ada="OUT", entity=afm_entity, organization=org,
            decision_type=decision_type, amount=Decimal("1000"),
        )
        _banded_decision(
            ada="NONDIRECT", entity=afm_entity, organization=org,
            decision_type=decision_type, amount=Decimal("33000"), direct=False,
        )
        data = _call_givers()
        assert data["results"] == []


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPagination:
    def test_offset_and_has_more(self, decision_type, organization):
        from conftest import AFMEntityFactory

        for i in range(3):
            entity = AFMEntityFactory(afm=f"88800000{i}", name=f"E{i}")
            _banded_decision(
                ada=f"PAG{i}", entity=entity, organization=organization,
                decision_type=decision_type,
                amount=Decimal(str(31000 + i)),
            )

        kwargs = _window_kwargs()
        kwargs.update(limit=1, offset=0)
        first = compute_top_banded_da_receivers(**kwargs)
        assert len(first["results"]) == 1
        assert first["results"][0]["rank"] == 1
        assert first["pagination"]["has_more"] is True

        kwargs.update(limit=1, offset=2)
        third = compute_top_banded_da_receivers(**kwargs)
        assert len(third["results"]) == 1
        assert third["results"][0]["rank"] == 3
        assert third["pagination"]["has_more"] is False
