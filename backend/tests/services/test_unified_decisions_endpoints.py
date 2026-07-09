"""
Integration tests for the new endpoint wrappers:

- ``/api/entity/afm/<afm>/decision-types/``
- ``/api/entity/afm/<afm>/statistics/``
- ``/api/entity/afm/<afm>/date-range/``
- ``/api/relationship/entity/<afm>/org/<orgUid>/decisions/``
"""

from datetime import datetime, timezone

import pytest
from django.test import RequestFactory

from api.views.entities.details import (
    afm_entity_decision_types,
    afm_entity_date_range,
    afm_entity_statistics,
)
from api.views.organization_entity_relationships.date_range_and_stats import (
    relationship_decisions_api,
)


@pytest.mark.django_db
class TestAFMEntityDecisionTypes:
    """Tests for ``afm_entity_decision_types``."""

    def test_returns_decision_types(self, decision_type, afm_entity):
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory, DecisionTypeFactory

        entity = afm_entity
        entity.afm = "111111111"
        entity.save()
        dt_a = DecisionTypeFactory(uid="ΔA")
        dt_b = DecisionTypeFactory(uid="ΔB")

        d1 = DecisionFactory(ada="A1", decision_type=dt_a, amount=100)
        d2 = DecisionFactory(ada="A2", decision_type=dt_b, amount=200)
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        DecisionEntityRelationshipFactory(decision=d2, entity=entity)

        # Unrelated decision, should not appear
        DecisionFactory(ada="OTHER", decision_type=dt_a)

        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_decision_types(req, afm="111111111")

        assert resp.status_code == 200
        data = resp.data
        assert data["total_types"] == 2

    def test_not_found(self):
        """Non-existent AFM → 404."""
        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_decision_types(req, afm="000000000")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestAFMEntityStatistics:
    """Tests for ``afm_entity_statistics``."""

    def test_returns_statistics(self, decision_type, afm_entity):
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "222222222"
        entity.save()
        d1 = DecisionFactory(ada="A1", decision_type=decision_type, amount=100)
        d2 = DecisionFactory(ada="A2", decision_type=decision_type, amount=300)
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        DecisionEntityRelationshipFactory(decision=d2, entity=entity)

        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_statistics(req, afm="222222222")

        assert resp.status_code == 200
        data = resp.data
        assert data["summary"]["decisions"]["total_count"] == 2
        assert data["summary"]["decisions"]["total_amount"] == 400.0
        assert data["entity"]["type"] == "afm"

    def test_not_found(self):
        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_statistics(req, afm="000000000")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestAFMEntityDateRange:
    """Tests for ``afm_entity_date_range``."""

    def test_returns_date_range(self, decision_type, afm_entity):
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory
        from datetime import datetime, timezone

        entity = afm_entity
        entity.afm = "333333333"
        entity.save()
        d1 = DecisionFactory(
            ada="OLD",
            issue_date=datetime(2020, 1, 1, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        d2 = DecisionFactory(
            ada="NEW",
            issue_date=datetime(2024, 6, 15, tzinfo=timezone.utc),
            decision_type=decision_type,
        )
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        DecisionEntityRelationshipFactory(decision=d2, entity=entity)

        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_date_range(req, afm="333333333")

        assert resp.status_code == 200
        data = resp.data
        assert data["has_data"] is True
        # earliest is an ISO date string from the DB
        assert "2020-01-01" in str(data["date_range"]["earliest"])

    def test_not_found(self):
        factory = RequestFactory()
        req = factory.get("/")
        resp = afm_entity_date_range(req, afm="000000000")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestRelationshipDecisions:
    """Tests for ``relationship_decisions_api``."""

    def test_returns_decisions_for_relationship(self, decision_type, afm_entity, organization):
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "444444444"
        entity.save()
        org = organization
        org.uid = "777777777"
        org.save()

        d_match = DecisionFactory(ada="MATCH", organization=org, decision_type=decision_type)
        DecisionEntityRelationshipFactory(decision=d_match, entity=entity)

        # Wrong org
        d_wrong = DecisionFactory(ada="WRONG", decision_type=decision_type)
        DecisionEntityRelationshipFactory(decision=d_wrong, entity=entity)

        factory = RequestFactory()
        req = factory.get("/", {"page": "1", "page_size": "10"})
        resp = relationship_decisions_api(req, afm="444444444", orgUid="777777777")

        assert resp.status_code == 200
        data = resp.data
        assert len(data["results"]) == 1
        assert data["results"][0]["ada"] == "MATCH"

    def test_pagination(self, decision_type, afm_entity, organization):
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "555555555"
        entity.save()
        org = organization
        org.uid = "666666666"
        org.save()

        for i in range(15):
            d = DecisionFactory(ada=f"ADA{i:06d}", organization=org, decision_type=decision_type)
            DecisionEntityRelationshipFactory(decision=d, entity=entity)

        factory = RequestFactory()
        req = factory.get("/", {"page": "1", "page_size": "5"})
        resp = relationship_decisions_api(req, afm="555555555", orgUid="666666666")

        assert resp.status_code == 200
        assert resp.data["pagination"]["total_count"] == 15
        assert resp.data["pagination"]["total_pages"] == 3
        assert len(resp.data["results"]) == 5

    def test_facets_applied(self, decision_type, afm_entity, organization):
        """Date/amount/search facets work on the relationship decisions endpoint."""
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory
        from datetime import datetime, timezone

        entity = afm_entity
        entity.afm = "777777777"
        entity.save()
        org = organization
        org.uid = "888888888"
        org.save()

        d1 = DecisionFactory(
            ada="MATCH_LOW", organization=org, decision_type=decision_type, amount=50,
            issue_date=datetime(2024, 3, 1, tzinfo=timezone.utc),
        )
        d2 = DecisionFactory(
            ada="MATCH_HIGH", organization=org, decision_type=decision_type, amount=5000,
            issue_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
        )
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        DecisionEntityRelationshipFactory(decision=d2, entity=entity)

        factory = RequestFactory()
        req = factory.get("/", {
            "min_amount": "100",
            "start_date": "2024-04-01",
            "end_date": "2024-12-31",
        })
        resp = relationship_decisions_api(req, afm="777777777", orgUid="888888888")

        assert resp.status_code == 200
        assert len(resp.data["results"]) == 1
        assert resp.data["results"][0]["ada"] == "MATCH_HIGH"
