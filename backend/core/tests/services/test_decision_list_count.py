"""
Paginator-count tests for the decision list.

The count used to inherit the ``calculated_amount`` annotation from
``apply_decision_facets``, which pulled a LEFT JOIN to
``core_decisionamountfield`` and forced a GROUP BY.  The count does not
read the sum, so it was pure overhead:

    SELECT COUNT(*) FROM (
        SELECT decision.id FROM decision
        LEFT OUTER JOIN core_decisionamountfield ...
        INNER JOIN core_decisionclassification ...
        WHERE ...
        GROUP BY 1
    ) subquery

``apply_decision_facets(count_only=True)`` skips the annotation and the
sort, leaving a plain ``COUNT(*)``.  An amount filter still forces the
annotation, because the filter needs it.
"""

from datetime import datetime, timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models.decision_classification import DecisionClassification
from core.models.decisions import Decision
from core.services.decision_facets import apply_decision_facets
from core.services.decision_projections import paginate_decisions

pytestmark = pytest.mark.django_db

START = datetime(2025, 11, 1, tzinfo=timezone.utc)
END = datetime(2026, 10, 31, 23, 59, 59, tzinfo=timezone.utc)
ISSUE_DATE = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def _seed(organization, decision_type, count=3):
    from conftest import DecisionAmountFieldFactory, DecisionFactory

    decisions = []
    for i in range(count):
        decision = DecisionFactory(
            ada=f"COUNT-{i}",
            organization=organization,
            decision_type=decision_type,
            issue_date=ISSUE_DATE,
        )
        DecisionClassification.objects.create(
            decision=decision, is_direct_assignment=True
        )
        DecisionAmountFieldFactory(decision=decision, amount=100 + i)
        decisions.append(decision)
    return decisions


def _facets(**overrides):
    params = {
        "start_dt": START,
        "end_dt": END,
        "direct_assignments_only": True,
        "sort_by": "amount_desc",
    }
    params.update(overrides)
    return apply_decision_facets(Decision.objects.all(), **params)


def _count_sql(ctx):
    sql = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().upper().startswith("SELECT COUNT(")
    ]
    assert len(sql) == 1, sql
    return sql[0]


class TestPaginatorCount:
    def test_count_skips_amount_join_without_amount_filter(
        self, organization, decision_type
    ):
        decisions = _seed(organization, decision_type, 3)

        page_qs = _facets()
        count_qs = _facets(count_only=True)

        assert "calculated_amount" in page_qs.query.annotations
        assert "calculated_amount" not in count_qs.query.annotations

        with CaptureQueriesContext(connection) as ctx:
            payload = paginate_decisions(page_qs, page_size=2, count_qs=count_qs)

        count_sql = _count_sql(ctx)
        assert "core_decisionamountfield" not in count_sql
        assert "GROUP BY" not in count_sql
        assert payload["pagination"]["total_count"] == len(decisions)

    def test_page_query_still_annotates_amount(self, organization, decision_type):
        _seed(organization, decision_type, 3)

        with CaptureQueriesContext(connection) as ctx:
            payload = paginate_decisions(
                _facets(),
                page_size=10,
                count_qs=_facets(count_only=True),
            )

        page_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if 'FROM "core_decision"' in q["sql"] and "LIMIT" in q["sql"]
        ]
        assert len(page_sql) == 1
        assert "core_decisionamountfield" in page_sql[0]
        assert payload["results"][0]["amount"] == 102.0

    def test_count_keeps_amount_join_when_amount_filter_is_used(
        self, organization, decision_type
    ):
        decisions = _seed(organization, decision_type, 3)

        count_qs = _facets(min_amount=50, count_only=True)
        assert "calculated_amount" in count_qs.query.annotations

        with CaptureQueriesContext(connection) as ctx:
            count = count_qs.count()

        count_sql = _count_sql(ctx)
        assert "core_decisionamountfield" in count_sql
        assert count == len(decisions)

    def test_count_qs_matches_page_qs_total(self, organization, decision_type):
        decisions = _seed(organization, decision_type, 5)

        assert _facets(count_only=True).count() == len(decisions)
        assert _facets().count() == len(decisions)
