"""
View-level regression test for the unified list paginator count.

``view=decisions`` must build its count from a queryset that does not carry
``calculated_amount``.  Otherwise the COUNT joins ``core_decisionamountfield``
and groups by decision for no reason.  An amount filter is the exception: the
filter needs the annotation, so the join is expected there.
"""

from datetime import datetime, timezone

import pytest
from django.db import connection
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext

from api.views.decisions_unified import decisions_unified_api
from core.models.decision_classification import DecisionClassification

pytestmark = pytest.mark.django_db

ISSUE_DATE = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)


def _seed(organization, decision_type, count=3):
    from conftest import DecisionAmountFieldFactory, DecisionFactory

    for i in range(count):
        decision = DecisionFactory(
            ada=f"UNIFIED-COUNT-{i}",
            organization=organization,
            decision_type=decision_type,
            issue_date=ISSUE_DATE,
        )
        DecisionClassification.objects.create(
            decision=decision, is_direct_assignment=True
        )
        DecisionAmountFieldFactory(decision=decision, amount=100 + i)


def _request(organization, **extra):
    params = {
        "source": "entity",
        "entity_type": "organization",
        "entity_id": organization.uid,
        "view": "decisions",
        "start_date": "2025-11-01",
        "end_date": "2026-10-31",
        "direct_assignments_only": "true",
        "sort_by": "amount_desc",
        "page": "1",
        "page_size": "2",
    }
    params.update(extra)
    return RequestFactory().get("/api/decisions/unified/", params)


def _count_sql(ctx):
    sql = [
        q["sql"]
        for q in ctx.captured_queries
        if q["sql"].lstrip().upper().startswith("SELECT COUNT(")
    ]
    assert len(sql) == 1, sql
    return sql[0]


class TestUnifiedDecisionsCount:
    def test_view_count_skips_amount_join(self, organization, decision_type):
        _seed(organization, decision_type, 3)

        with CaptureQueriesContext(connection) as ctx:
            response = decisions_unified_api(_request(organization))

        assert response.status_code == 200
        count_sql = _count_sql(ctx)
        assert "core_decisionamountfield" not in count_sql
        assert "GROUP BY" not in count_sql
        assert response.data["pagination"]["total_count"] == 3

    def test_view_count_keeps_amount_join_with_amount_filter(
        self, organization, decision_type
    ):
        _seed(organization, decision_type, 3)

        with CaptureQueriesContext(connection) as ctx:
            response = decisions_unified_api(_request(organization, min_amount="50"))

        assert response.status_code == 200
        count_sql = _count_sql(ctx)
        assert "core_decisionamountfield" in count_sql
        assert response.data["pagination"]["total_count"] == 3
