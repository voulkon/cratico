"""
Regression tests for the entity statistics/timeline aggregates
(``/entity/<type>/<id>/statistics/`` and ``/timeline/``).

Both endpoints used to annotate the parent queryset with a ``Sum`` over the
amount relation and then aggregate again.  Django nested that aggregate in a
subquery grouped by decision *and* every amount column, so a decision with
several amount rows was counted several times, ``AVG``/``MIN``/``MAX`` ran at
amount-row grain, and the plan materialised the fan-out.

These tests seed a multi-amount decision and pin both the numbers and the SQL
shape.
"""

import re
from datetime import datetime, timezone

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from api.views.search.entity_analytics import (
    entity_statistics_api_dev,
    entity_timeline_api_dev,
)

pytestmark = pytest.mark.django_db

ISSUE_DATE = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
START_DATE = "2026-01-01"
END_DATE = "2026-01-31"


def _seed(organization, decision_type):
    """Two decisions for the org; the first carries two amount rows."""
    from conftest import DecisionAmountFieldFactory, DecisionFactory

    d1 = DecisionFactory(
        ada="ENTITY-MULTI-1",
        organization=organization,
        decision_type=decision_type,
        issue_date=ISSUE_DATE,
    )
    d2 = DecisionFactory(
        ada="ENTITY-MULTI-2",
        organization=organization,
        decision_type=decision_type,
        issue_date=ISSUE_DATE,
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

    # Outside the entity (and outside the date range) — must not contribute.
    DecisionFactory(
        ada="ENTITY-OTHER",
        decision_type=decision_type,
        issue_date=datetime(2025, 6, 1, 12, tzinfo=timezone.utc),
    )
    return d1, d2


def _request(**extra):
    params = {"start_date": START_DATE, "end_date": END_DATE}
    params.update(extra)
    return RequestFactory().get("/", params)


def _amount_queries(ctx):
    return [
        q["sql"]
        for q in ctx.captured_queries
        if "core_decisionamountfield" in q["sql"].lower()
    ]


def _group_by_clause(sql):
    index = sql.upper().find("GROUP BY")
    return "" if index == -1 else sql[index:]


class TestEntityStatisticsAggregate:
    def test_counts_and_amounts_are_per_decision(self, organization, decision_type):
        _seed(organization, decision_type)

        response = entity_statistics_api_dev(
            _request(), entity_type="organization", entity_id=organization.uid
        )

        assert response.status_code == 200, response.data
        summary = response.data["summary"]
        assert summary["decisions"]["total_count"] == 2
        assert summary["financial"]["primary_amount"] == 175.0
        assert summary["financial"]["total_decisions"] == 2
        assert summary["financial"]["decisions_with_amounts"] == 2
        # Per-decision totals are 150 and 25, not the amount rows 100/50/25.
        assert summary["decisions"]["avg_amount"] == 87.5
        assert summary["decisions"]["max_amount"] == 150.0
        assert summary["decisions"]["min_amount"] == 25.0

    def test_grouped_breakdowns_count_each_decision_once(
        self, organization, decision_type
    ):
        _seed(organization, decision_type)

        response = entity_statistics_api_dev(
            _request(), entity_type="organization", entity_id=organization.uid
        )

        monthly = response.data["charts"]["monthly_breakdown"]
        assert monthly == [{"month": "2026-01-01", "count": 2, "amount": 175.0}]

        top_types = response.data["charts"]["top_decision_types"]
        assert len(top_types) == 1
        assert top_types[0]["count"] == 2
        assert top_types[0]["total_amount"] == 175.0

        assert response.data["summary"]["status_breakdown"] == {"PUBLISHED": 2}

    def test_amount_queries_do_not_group_by_amount_columns(
        self, organization, decision_type
    ):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            entity_statistics_api_dev(
                _request(), entity_type="organization", entity_id=organization.uid
            )

        amount_queries = _amount_queries(ctx)
        assert amount_queries
        for sql in amount_queries:
            group_by = _group_by_clause(sql)
            assert "verified_amount" not in group_by, sql
            assert "parent_key_path" not in group_by, sql
            assert "invalid_amount_reason" not in group_by, sql

    def test_lite_mode_scans_amount_table_once_without_nesting(
        self, organization, decision_type
    ):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            response = entity_statistics_api_dev(
                _request(lite="true"),
                entity_type="organization",
                entity_id=organization.uid,
            )

        assert response.status_code == 200
        assert response.data["summary"]["decisions"]["total_count"] == 2
        assert response.data["summary"]["financial"]["primary_amount"] == 175.0

        amount_queries = _amount_queries(ctx)
        assert len(amount_queries) == 1, amount_queries
        assert "FROM (SELECT" not in amount_queries[0].upper()

    def test_count_matches_list_paginator(self, organization, decision_type):
        """The aggregate and the paginated list must agree on the total."""
        from api.views.search.entity_analytics import entity_decisions_api_dev

        _seed(organization, decision_type)

        stats = entity_statistics_api_dev(
            _request(), entity_type="organization", entity_id=organization.uid
        )
        listing = entity_decisions_api_dev(
            _request(), entity_type="organization", entity_id=organization.uid
        )

        assert stats.data["summary"]["decisions"]["total_count"] == 2
        assert listing.data["pagination"]["total_count"] == 2


class TestEntityTimelineAggregate:
    def test_counts_and_amounts_are_per_decision(self, organization, decision_type):
        _seed(organization, decision_type)

        response = entity_timeline_api_dev(
            _request(granularity="month"),
            entity_type="organization",
            entity_id=organization.uid,
        )

        assert response.status_code == 200
        assert response.data["timeline"] == [
            {
                "period": "2026-01-01",
                "count": 2,
                "total_amount": 175.0,
                "avg_amount": 87.5,
            }
        ]
        assert response.data["summary"]["total_decisions"] == 2
        assert response.data["summary"]["total_amount"] == 175.0

    def test_single_amount_pass_grouped_by_period(self, organization, decision_type):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            entity_timeline_api_dev(
                _request(granularity="month"),
                entity_type="organization",
                entity_id=organization.uid,
            )

        amount_queries = _amount_queries(ctx)
        assert len(amount_queries) == 1, amount_queries
        sql = amount_queries[0]
        assert re.search(r"COUNT\s*\(\s*DISTINCT", sql, re.IGNORECASE), sql
        assert "FROM (SELECT" not in sql.upper()
        assert "verified_amount" not in _group_by_clause(sql)


class TestEntityAggregateDistinctForAFM:
    """
    AFM entities build their queryset from ``entity_relationships`` and call
    ``.distinct()``.  A decision linked to the same AFM twice must still be
    counted and summed once.
    """

    def test_lite_statistics_deduplicates_decisions_and_amounts(
        self, afm_entity, decision_type
    ):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
        )

        afm_entity.afm = "777777777"
        afm_entity.save()
        decision = DecisionFactory(
            ada="AFM-MULTI", decision_type=decision_type, issue_date=ISSUE_DATE
        )
        DecisionAmountFieldFactory(
            decision=decision, amount=100, parent_key_path="a.expenseAmount"
        )
        DecisionAmountFieldFactory(
            decision=decision, amount=50, parent_key_path="b.expenseAmount"
        )
        # Same decision, same entity, two roles → two relationship rows.
        DecisionEntityRelationshipFactory(
            decision=decision, entity=afm_entity, role="grantor"
        )
        DecisionEntityRelationshipFactory(
            decision=decision, entity=afm_entity, role="grantee"
        )
        DecisionAmountFieldFactory(
            decision=DecisionFactory(
                ada="AFM-OTHER",
                decision_type=decision_type,
                issue_date=datetime(2025, 6, 1, 12, tzinfo=timezone.utc),
            ),
            amount=999,
            parent_key_path="other.expenseAmount",
        )

        response = entity_statistics_api_dev(
            _request(lite="true"),
            entity_type="afm",
            entity_id=afm_entity.afm,
        )

        assert response.status_code == 200
        assert response.data["statistics"]["total_decisions"] == 1
        assert response.data["statistics"]["total_amount"] == 150.0
