"""
Regression tests for the unified aggregate projections
(``view=date_range`` / ``decision_types`` / ``statistics``).

The aggregate projections reuse the faceted queryset.  If that queryset
carries the ``calculated_amount`` annotation, Django wraps the projection
aggregate in a subquery grouped by decision *and* every amount column.  On a
large organization that plan reads the whole amount table through a nested
loop and inflates ``COUNT(id)`` for decisions with more than one amount row.

These tests pin the cheap shape: the date metadata aggregate must not touch
the amount table at all, and the amount aggregates must remain a plain
``GROUP BY`` (no inner per-decision subquery).
"""

from datetime import datetime, timezone

import pytest
from django.core.cache import cache
from django.db import connection
from django.test import RequestFactory, override_settings
from django.test.utils import CaptureQueriesContext

from api.views.decisions_unified import decisions_unified_api

pytestmark = pytest.mark.django_db

_LOCMEM_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unified-aggregate-sql-tests",
    }
}

ISSUE_DATE = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _use_locmem_cache():
    with override_settings(CACHES=_LOCMEM_CACHES):
        cache.clear()
        yield
        cache.clear()


def _seed(organization, decision_type):
    from conftest import DecisionAmountFieldFactory, DecisionFactory

    d1 = DecisionFactory(
        ada="AGG-MULTI-1",
        organization=organization,
        decision_type=decision_type,
        issue_date=ISSUE_DATE,
    )
    d2 = DecisionFactory(
        ada="AGG-MULTI-2",
        organization=organization,
        decision_type=decision_type,
        issue_date=ISSUE_DATE,
    )
    # d1 has two amount rows (150 total), d2 has one (25).
    DecisionAmountFieldFactory(
        decision=d1, amount=100, parent_key_path="a.expenseAmount"
    )
    DecisionAmountFieldFactory(
        decision=d1, amount=50, parent_key_path="b.expenseAmount"
    )
    DecisionAmountFieldFactory(
        decision=d2, amount=25, parent_key_path="c.expenseAmount"
    )
    return d1, d2


def _request(organization, view_name, **extra):
    params = {
        "source": "entity",
        "entity_type": "organization",
        "entity_id": organization.uid,
        "view": view_name,
    }
    params.update(extra)
    return RequestFactory().get("/api/decisions/unified/", params)


def _queries(ctx):
    return [q["sql"] for q in ctx.captured_queries]


class TestUnifiedDateRangeAggregate:
    def test_counts_decisions_once_not_amount_rows(self, organization, decision_type):
        _seed(organization, decision_type)

        response = decisions_unified_api(_request(organization, "date_range"))

        assert response.status_code == 200
        assert response.data["summary"]["total_decisions"] == 2
        assert response.data["summary"]["total_amount"] == 175.0

    def test_metadata_aggregate_does_not_join_amount_table(
        self, organization, decision_type
    ):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            decisions_unified_api(_request(organization, "date_range"))

        metadata_queries = [
            sql
            for sql in _queries(ctx)
            if "MIN(" in sql.upper() and "MAX(" in sql.upper()
        ]
        assert metadata_queries, "expected a MIN/MAX aggregate for date_range"
        for sql in metadata_queries:
            assert "core_decisionamountfield" not in sql, sql

    def test_amount_aggregates_do_not_use_per_decision_subquery(
        self, organization, decision_type
    ):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            decisions_unified_api(_request(organization, "date_range"))

        amount_queries = [
            sql for sql in _queries(ctx) if "core_decisionamountfield" in sql
        ]
        assert amount_queries, "expected amount aggregates to run"
        for sql in amount_queries:
            assert "FROM (SELECT" not in sql.upper(), sql

    def test_date_range_scans_amount_table_once(self, organization, decision_type):
        """
        The summary totals are derived from the activity chart, so the whole
        date_range projection touches ``core_decisionamountfield`` exactly
        once.  A second amount-table aggregate doubles the cold I/O that
        makes a large organization's first load slow.
        """
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            decisions_unified_api(_request(organization, "date_range"))

        amount_queries = [
            sql for sql in _queries(ctx) if "core_decisionamountfield" in sql
        ]
        assert len(amount_queries) == 1, amount_queries


class TestUnifiedDecisionTypesAggregate:
    def test_counts_decisions_once_not_amount_rows(self, organization, decision_type):
        _seed(organization, decision_type)

        with CaptureQueriesContext(connection) as ctx:
            response = decisions_unified_api(
                _request(
                    organization,
                    "decision_types",
                    start_date="2026-01-01",
                    end_date="2026-01-31",
                )
            )

        assert response.status_code == 200
        assert response.data["total_types"] == 1
        row = response.data["decision_types"][0]
        assert row["count"] == 2
        assert row["total_amount"] == 175.0

        amount_queries = [
            sql for sql in _queries(ctx) if "core_decisionamountfield" in sql
        ]
        for sql in amount_queries:
            assert "FROM (SELECT" not in sql.upper(), sql
