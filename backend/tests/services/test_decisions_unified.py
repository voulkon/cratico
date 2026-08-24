"""
Integration tests for the unified decisions endpoint
(``/api/decisions/unified/``).
"""

from unittest.mock import patch

import pytest
from django.test import RequestFactory
from django.urls import reverse
from rest_framework.test import APIClient, force_authenticate

from api.views.decisions_unified import decisions_unified_api

# The unified endpoint has @cached_view(defer_on_miss=True).  In tests
# there is no Redis, so cache-miss triggers a 202 deferral instead of
# synchronous execution.  Mock the warmup-status check to return "ready"
# so the decorator falls through to the real view.
_UNIFIED_CACHE_MOCK = patch(
    "core.decorators.cache_decorator.response_cache.get_warmup_status",
    return_value="ready",
)


@pytest.mark.django_db
class TestUnifiedEndpoint:
    """Integration tests for the unified decisions endpoint."""

    @classmethod
    def setup_class(cls):
        cls._cache_patcher = _UNIFIED_CACHE_MOCK.start()

    @classmethod
    def teardown_class(cls):
        cls._cache_patcher.stop()

    # ── Basic source dispatch ───────────────────────────────────────

    def test_source_temporal_returns_all(self, decision_type):
        """source=temporal with view=decisions returns paginated results."""
        from conftest import DecisionFactory

        for i in range(5):
            DecisionFactory(ada=f"ADA{i:06d}", decision_type=decision_type, amount=100)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "page": "1",
            "page_size": "10",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        data = resp.data
        assert len(data["results"]) == 5
        assert data["pagination"]["total_count"] == 5

    def test_source_entity(self, decision_type, organization):
        """source=entity returns decisions for a specific organization."""
        from conftest import DecisionFactory

        org = organization
        org.uid = "999999999"
        org.save()
        DecisionFactory(ada="ORG_DEC", organization=org, decision_type=decision_type)
        DecisionFactory(ada="OTHER", decision_type=decision_type)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "entity",
            "entity_type": "organization",
            "entity_id": org.uid,
            "view": "decisions",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["ada"] == "ORG_DEC"

    def test_source_afm(self, decision_type, afm_entity):
        """source=afm returns decisions linked to an AFM entity."""
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "123456789"
        entity.save()
        d1 = DecisionFactory(ada="AFM_DEC", decision_type=decision_type)
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        DecisionFactory(ada="OTHER", decision_type=decision_type)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "afm",
            "afm": "123456789",
            "view": "decisions",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["ada"] == "AFM_DEC"

    # ── Projections ─────────────────────────────────────────────────

    def test_view_decision_types(self):
        """view=decision_types returns aggregated types."""
        from conftest import DecisionFactory, DecisionTypeFactory

        dt_a = DecisionTypeFactory(uid="ΔA", label="Type A")
        dt_b = DecisionTypeFactory(uid="ΔB", label="Type B")
        DecisionFactory(decision_type=dt_a, amount=100)
        DecisionFactory(decision_type=dt_b, amount=200)
        DecisionFactory(decision_type=dt_b, amount=300)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decision_types",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        data = resp.data
        assert data["total_types"] == 2
        # Most frequent first
        assert data["decision_types"][0]["uid"] == "ΔB"
        assert data["decision_types"][0]["count"] == 2

    def test_view_statistics(self, decision_type):
        """view=statistics returns summary stats."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        d1 = DecisionFactory(decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d1, amount=100)
        d2 = DecisionFactory(decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d2, amount=300)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "statistics",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        assert resp.data["summary"]["decisions"]["total_count"] == 2
        assert resp.data["summary"]["decisions"]["total_amount"] == 400.0

    def test_view_date_range(self, decision_type):
        """view=date_range returns date boundaries and activity chart."""
        from conftest import DecisionFactory
        from datetime import datetime, timezone

        DecisionFactory(
            ada="OLD",
            issue_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        DecisionFactory(
            ada="NEW",
            issue_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            decision_type=decision_type,
        )

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "date_range",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        assert resp.data["has_data"] is True
        assert resp.data["date_range"] is not None

    # ── Facets ──────────────────────────────────────────────────────

    def test_date_filter(self, decision_type):
        """Date filtering via start_date/end_date params."""
        from conftest import DecisionFactory
        from datetime import datetime, timezone

        DecisionFactory(ada="JAN", issue_date=datetime(2024, 1, 15, tzinfo=timezone.utc), decision_type=decision_type)
        DecisionFactory(ada="JUN", issue_date=datetime(2024, 6, 15, tzinfo=timezone.utc), decision_type=decision_type)
        DecisionFactory(ada="DEC", issue_date=datetime(2024, 12, 15, tzinfo=timezone.utc), decision_type=decision_type)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "start_date": "2024-03-01",
            "end_date": "2024-09-30",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        adas = [r["ada"] for r in resp.data["results"]]
        assert "JUN" in adas
        assert "JAN" not in adas
        assert "DEC" not in adas

    def test_decision_type_filter(self):
        """Filtering by comma-separated decision_type UIDs."""
        from conftest import DecisionFactory, DecisionTypeFactory

        dt_a = DecisionTypeFactory(uid="ΔA")
        dt_b = DecisionTypeFactory(uid="ΔB")
        DecisionFactory(ada="A_DEC", decision_type=dt_a)
        DecisionFactory(ada="B_DEC", decision_type=dt_b)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "decision_types": "ΔA",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        adas = [r["ada"] for r in resp.data["results"]]
        assert "A_DEC" in adas
        assert "B_DEC" not in adas

    def test_amount_filter(self, decision_type):
        """Amount range filtering."""
        from conftest import DecisionAmountFieldFactory, DecisionFactory

        d_low = DecisionFactory(ada="LOW", decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d_low, amount=50)
        d_mid = DecisionFactory(ada="MID", decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d_mid, amount=500)
        d_high = DecisionFactory(ada="HIGH", decision_type=decision_type)
        DecisionAmountFieldFactory(decision=d_high, amount=5000)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "min_amount": "100",
            "max_amount": "1000",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        adas = [r["ada"] for r in resp.data["results"]]
        assert "MID" in adas
        assert "LOW" not in adas
        assert "HIGH" not in adas

    def test_search_filter(self, decision_type):
        """Full-text search filtering."""
        from conftest import DecisionFactory

        DecisionFactory(ada="A1", subject="Προμήθεια εξοπλισμού", decision_type=decision_type)
        DecisionFactory(ada="A2", subject="Ανάθεση καθαριότητας", decision_type=decision_type)

        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "q": "προμήθεια",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 200
        adas = [r["ada"] for r in resp.data["results"]]
        assert "A1" in adas
        assert "A2" not in adas

    # ── Error cases ─────────────────────────────────────────────────

    def test_missing_source_returns_400(self):
        """Missing source param → 400."""
        factory = RequestFactory()
        req = factory.get("/", {"view": "decisions"})
        resp = decisions_unified_api(req)
        assert resp.status_code == 400

    def test_unknown_source_returns_400(self):
        """Unknown source → 400."""
        factory = RequestFactory()
        req = factory.get("/", {"source": "garbage", "view": "decisions"})
        resp = decisions_unified_api(req)
        assert resp.status_code == 400

    def test_invalid_date_returns_400(self):
        """Invalid date format → 400."""
        factory = RequestFactory()
        req = factory.get("/", {
            "source": "temporal",
            "view": "decisions",
            "start_date": "not-a-date",
        })
        resp = decisions_unified_api(req)
        assert resp.status_code == 400
