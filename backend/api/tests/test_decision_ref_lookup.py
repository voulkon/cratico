"""
Decision endpoints must accept the ΑΔΑ (ADA) in the URL as well as the integer PK.

    GET /api/decisions/128820/            → by PK
    GET /api/decisions/ΨΦ4Μ4653ΠΓ-ΜΜΥ/    → by ADA (raw or percent-encoded)

Both must resolve to the same decision, and an unknown reference must 404
rather than 500.
"""

from urllib.parse import quote

import pytest
from django.utils import timezone

from core.models.decisions import Decision
from core.models.types import ActType

ADA = "ΨΦ4Μ4653ΠΓ-ΜΜΥ"


@pytest.fixture
def act_type(db):
    act, _ = ActType.objects.get_or_create(uid="Β.2.2", defaults={"label": "Πληρωμή"})
    return act


@pytest.fixture
def decision(db, act_type):
    return Decision.objects.create(
        ada=ADA,
        version_id="v-1",
        subject="Απόφαση με ΑΔΑ",
        issue_date=timezone.now(),
        submission_timestamp=timezone.now(),
        decision_type=act_type,
        status="PUBLISHED",
    )


@pytest.mark.django_db
class TestDecisionDetailByRef:
    def test_by_integer_pk(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == decision.id
        assert data["ada"] == ADA

    def test_by_ada(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{ADA}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == decision.id
        assert data["ada"] == ADA

    def test_by_percent_encoded_ada(self, api_client, decision):
        """Browser-style request: non-ASCII path segment arrives encoded."""
        encoded = quote(ADA, safe="")
        resp = api_client.get(f"/api/decisions/{encoded}/")
        assert resp.status_code == 200
        assert resp.json()["id"] == decision.id

    def test_lowercased_ada_falls_back_case_insensitively(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{ADA.lower()}/")
        assert resp.status_code == 200
        assert resp.json()["id"] == decision.id

    def test_unknown_ada_is_404(self, api_client, db):
        resp = api_client.get("/api/decisions/ΑΑΑΑΑΑΑΑΑΑ-ΑΑΑ/")
        assert resp.status_code == 404

    def test_unknown_pk_is_404(self, api_client, db):
        resp = api_client.get("/api/decisions/999999999/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestOtherDecisionEndpointsByAda:
    def test_entities_by_ada(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{ADA}/entities/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision_id"] == decision.id
        assert data["decision_ada"] == ADA
        assert data["relationships"] == []

    def test_related_by_ada(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{ADA}/related/")
        assert resp.status_code == 200
        assert resp.json()["decision_id"] == decision.id

    def test_companies_by_ada(self, api_client, decision):
        resp = api_client.get(f"/api/decisions/{ADA}/companies/")
        assert resp.status_code == 200
        assert resp.json()["decision_ada"] == ADA

    def test_document_content_by_ada(self, api_client, decision):
        """No DocumentExtraction row yet → 200 with status NOT_FOUND (pollable)."""
        resp = api_client.get(f"/api/decisions/{ADA}/content/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["decision_id"] == decision.id
        assert data["ada"] == ADA
        assert data["status"] == "NOT_FOUND"

    def test_document_content_unknown_ada_is_404(self, api_client, db):
        resp = api_client.get("/api/decisions/ΑΑΑΑΑΑΑΑΑΑ-ΑΑΑ/content/")
        assert resp.status_code == 404
