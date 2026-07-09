"""
Tests for the decision-source registry (``core.services.decision_sources``).
"""

import pytest
from django.test import RequestFactory

from core.services.decision_sources import (
    SOURCE_BUILDERS,
    authorize_source,
    get_source_queryset,
)


# ── Source registry ─────────────────────────────────────────────────

class TestSourceRegistry:
    """Tests for the source builder registry."""

    def test_all_sources_registered(self):
        """Every expected source is in the registry."""
        expected = {"entity", "afm", "relationship", "temporal", "batch", "subscription"}
        assert set(SOURCE_BUILDERS.keys()) == expected


class TestGetSourceQueryset:
    """Tests for ``get_source_queryset``."""

    def test_missing_source_param(self, rf: RequestFactory):
        req = rf.get("/")
        with pytest.raises(ValueError, match="source query parameter is required"):
            get_source_queryset(req)

    def test_unknown_source(self, rf: RequestFactory):
        req = rf.get("/", {"source": "nonexistent"})
        with pytest.raises(ValueError, match="Unknown source"):
            get_source_queryset(req)

    def test_temporal_source(self, rf: RequestFactory):
        """source=temporal returns all decisions (no special params needed)."""
        req = rf.get("/", {"source": "temporal"})
        qs = get_source_queryset(req)
        assert qs.model.__name__ == "Decision"

    def test_entity_source_missing_params(self, rf: RequestFactory):
        """source=entity without entity_type/entity_id raises ValueError."""
        req = rf.get("/", {"source": "entity"})
        with pytest.raises(ValueError, match="entity_type and entity_id are required"):
            get_source_queryset(req)

    def test_afm_source_missing_afm(self, rf: RequestFactory):
        """source=afm without afm raises ValueError."""
        req = rf.get("/", {"source": "afm"})
        with pytest.raises(ValueError, match="afm is required"):
            get_source_queryset(req)

    def test_relationship_source_missing_params(self, rf: RequestFactory):
        """source=relationship without afm/org_uid raises ValueError."""
        req = rf.get("/", {"source": "relationship", "afm": "123"})
        with pytest.raises(ValueError, match="afm and org_uid are required"):
            get_source_queryset(req)

    def test_batch_source_missing_id(self, rf: RequestFactory):
        """source=batch without batch_id raises ValueError."""
        req = rf.get("/", {"source": "batch"})
        with pytest.raises(ValueError, match="batch_id is required"):
            get_source_queryset(req)

    def test_subscription_source_missing_id(self, rf: RequestFactory):
        """source=subscription without subscription_id raises ValueError."""
        req = rf.get("/", {"source": "subscription"})
        with pytest.raises(ValueError, match="subscription_id is required"):
            get_source_queryset(req)


@pytest.mark.django_db
class TestSourceQuerysetIntegration:
    """Integration tests that hit the database through source builders."""

    def test_temporal_returns_all(self, decision, decision_type):
        """source=temporal returns all decisions."""
        from conftest import DecisionFactory

        d1 = decision
        d2 = DecisionFactory(ada="A2", decision_type=decision_type)

        rf = RequestFactory()
        req = rf.get("/", {"source": "temporal"})
        qs = get_source_queryset(req)

        ids = set(qs.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id in ids

    def test_entity_source(self, decision, decision_type, organization):
        """source=entity with entity_type=organization returns org decisions."""
        from conftest import DecisionFactory

        org = organization
        org.uid = "999999999"
        org.save()
        d1 = DecisionFactory(ada="A1", organization=org, decision_type=decision_type)
        d2 = decision  # different org

        rf = RequestFactory()
        req = rf.get("/", {"source": "entity", "entity_type": "organization", "entity_id": org.uid})
        qs = get_source_queryset(req)

        ids = set(qs.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id not in ids

    def test_afm_source(self, decision, decision_type, afm_entity):
        """source=afm returns decisions linked to the AFM entity."""
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "123456789"
        entity.save()
        d1 = decision
        DecisionEntityRelationshipFactory(decision=d1, entity=entity)
        d2 = DecisionFactory(ada="A2", decision_type=decision_type)  # not linked

        rf = RequestFactory()
        req = rf.get("/", {"source": "afm", "afm": "123456789"})
        qs = get_source_queryset(req)

        ids = set(qs.values_list("id", flat=True))
        assert d1.id in ids
        assert d2.id not in ids

    def test_relationship_source(self, decision_type, afm_entity, organization):
        """source=relationship returns the intersection of AFM + org."""
        from conftest import DecisionFactory, DecisionEntityRelationshipFactory

        entity = afm_entity
        entity.afm = "111111111"
        entity.save()
        org = organization
        org.uid = "888888888"
        org.save()

        d_match = DecisionFactory(ada="MATCH", organization=org, decision_type=decision_type)
        DecisionEntityRelationshipFactory(decision=d_match, entity=entity)

        d_wrong_org = DecisionFactory(ada="WRONG_ORG", decision_type=decision_type)
        DecisionEntityRelationshipFactory(decision=d_wrong_org, entity=entity)

        d_wrong_entity = DecisionFactory(ada="WRONG_ENT", organization=org, decision_type=decision_type)

        rf = RequestFactory()
        req = rf.get("/", {
            "source": "relationship",
            "afm": "111111111",
            "org_uid": "888888888",
        })
        qs = get_source_queryset(req)

        ids = set(qs.values_list("id", flat=True))
        assert d_match.id in ids
        assert d_wrong_org.id not in ids
        assert d_wrong_entity.id not in ids


@pytest.mark.django_db
class TestAuthorizeSource:
    """Tests for ``authorize_source``."""

    def test_public_source_returns_none(self, rf: RequestFactory):
        """Temporal/entity/afm/relationship sources have no extra auth."""
        req = rf.get("/", {"source": "temporal"})
        from core.models.decisions import Decision
        assert authorize_source(req, Decision.objects.all()) is None

    def test_batch_source_not_found(self, rf: RequestFactory):
        """Non-existent batch → 404."""
        from core.models.decisions import Decision
        req = rf.get("/", {"source": "batch", "batch_id": "99999"})
        resp = authorize_source(req, Decision.objects.all())
        assert resp is not None
        assert resp.status_code == 404
