"""
Regression test for the relationship-statistics amount fallback.

When the financial service fails, the fallback used to annotate the parent
queryset with ``Sum`` and then aggregate it again.  Django nests that in a
grouped subquery, so the fallback scanned the amount table twice.  It must
aggregate the child rows directly.
"""

from datetime import datetime, timezone

import pytest
from conftest import (
    AFMEntityFactory,
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
    OrganizationFactory,
)
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.services.financial_calculation_service import financial_service

pytestmark = pytest.mark.django_db

AFM = "933333333"
ORG_UID = "900000001"
ISSUE_DATE = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
URL = f"/api/relationship/entity/{AFM}/org/{ORG_UID}/statistics/"


def _seed():
    organization = OrganizationFactory(uid=ORG_UID)
    entity = AFMEntityFactory(afm=AFM)

    d1 = DecisionFactory(
        ada="REL-STATS-1",
        organization=organization,
        issue_date=ISSUE_DATE,
        amount=150,
    )
    d2 = DecisionFactory(
        ada="REL-STATS-2",
        organization=organization,
        issue_date=ISSUE_DATE,
        amount=25,
    )
    DecisionAmountFieldFactory(
        decision=d1, amount=100, parent_key_path="a.expenseAmount"
    )
    DecisionAmountFieldFactory(
        decision=d1, amount=50, parent_key_path="b.expenseAmount"
    )
    DecisionAmountFieldFactory(
        decision=d2, amount=25, parent_key_path="c.expenseAmount"
    )

    for decision in (d1, d2):
        DecisionEntityRelationshipFactory(
            decision=decision, entity=entity, role="grantor"
        )

    # Outside the requested window — must not contribute.
    other = DecisionFactory(
        ada="REL-STATS-OTHER",
        organization=organization,
        issue_date=datetime(2025, 6, 1, 12, tzinfo=timezone.utc),
    )
    DecisionEntityRelationshipFactory(decision=other, entity=entity, role="grantor")


def _force_financial_service_failure(monkeypatch):
    def _boom(*args, **kwargs):
        raise RuntimeError("financial service unavailable")

    monkeypatch.setattr(financial_service, "get_global_financial_summary", _boom)


def test_fallback_counts_and_sums_once(api_client, monkeypatch):
    _seed()
    _force_financial_service_failure(monkeypatch)

    response = api_client.get(
        URL, {"start_date": "2026-01-01", "end_date": "2026-01-31"}
    )

    assert response.status_code == 200
    data = response.json()
    assert data["total_decisions"] == 2
    assert data["total_amount"] == 175.0
    assert data["avg_amount"] == 87.5
    assert data["decisions_with_amounts"] == 2


def test_fallback_does_not_nest_the_amount_aggregate(api_client, monkeypatch):
    _seed()
    _force_financial_service_failure(monkeypatch)

    with CaptureQueriesContext(connection) as ctx:
        api_client.get(URL, {"start_date": "2026-01-01", "end_date": "2026-01-31"})

    amount_queries = [
        query["sql"]
        for query in ctx.captured_queries
        if "core_decisionamountfield" in query["sql"].lower()
    ]
    assert len(amount_queries) == 1, amount_queries
    sql = amount_queries[0]
    assert "FROM (SELECT" not in sql.upper()
    assert "GROUP BY" not in sql.upper()
