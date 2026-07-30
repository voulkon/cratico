"""
Tests for AI Pipeline endpoints:

- GET /api/ai/pipelines/
- GET /api/ai/pipelines/<id>/
"""

import pytest
from django.urls import reverse

from core.models.pipeline import PipelineDefinition, PipelineStep


# ============================================================================
# Helpers
# ============================================================================


def _url(name: str, **kwargs) -> str:
    return reverse(f"ai_{name}", kwargs=kwargs)


def _create_pipeline(name="test-pipeline", active=True, trigger_type=None) -> PipelineDefinition:
    return PipelineDefinition.objects.create(
        name=name,
        version=1,
        description="A test pipeline",
        is_active=active,
        trigger_type=trigger_type,
    )


def _add_step(pipeline: PipelineDefinition, order: int, **kwargs) -> PipelineStep:
    defaults = {
        "step_type": "AI_CALL",
        "name": f"step-{order}",
        "config": {"model": "openai/gpt-4o"},
    }
    defaults.update(kwargs)
    return PipelineStep.objects.create(pipeline=pipeline, order=order, **defaults)


# ============================================================================
# GET /api/ai/pipelines/
# ============================================================================


@pytest.mark.django_db
class TestPipelinesList:
    def test_returns_active_pipelines(self, authenticated_client):
        """Only active pipelines are returned."""
        p1 = _create_pipeline("active-1", active=True)
        _create_pipeline("inactive", active=False)
        p3 = _create_pipeline("active-2", active=True)

        resp = authenticated_client.get(_url("pipelines_list"))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        ids = {d["id"] for d in data}
        assert ids == {p1.id, p3.id}

    def test_returns_pipeline_fields(self, authenticated_client):
        """Each pipeline includes expected fields."""
        p = _create_pipeline("my-pipeline", trigger_type="notification_batch_summary")

        resp = authenticated_client.get(_url("pipelines_list"))
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        item = data[0]
        assert item["id"] == p.id
        assert item["name"] == "my-pipeline"
        assert item["version"] == 1
        assert item["description"] == "A test pipeline"
        assert item["is_active"] is True
        assert item["trigger_type"] == "notification_batch_summary"
        assert "steps" not in item  # List view excludes steps

    def test_filter_by_trigger_type(self, authenticated_client):
        """Filter pipelines by trigger_type query param."""
        _create_pipeline("type-a", trigger_type="import")
        p2 = _create_pipeline("type-b", trigger_type="notification_batch_summary")

        resp = authenticated_client.get(
            _url("pipelines_list"), {"trigger_type": "notification_batch_summary"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == p2.id

    def test_empty_list(self, authenticated_client):
        """No active pipelines returns empty list."""
        resp = authenticated_client.get(_url("pipelines_list"))
        assert resp.status_code == 200
        assert resp.json() == []

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        resp = api_client.get(_url("pipelines_list"))
        assert resp.status_code == 401


# ============================================================================
# GET /api/ai/pipelines/<id>/
# ============================================================================


@pytest.mark.django_db
class TestPipelinesDetail:
    def test_returns_pipeline_with_steps(self, authenticated_client):
        """Detail includes steps."""
        p = _create_pipeline("detailed")
        s1 = _add_step(p, 0, name="extract", step_type="EXTRACT")
        s2 = _add_step(p, 1, name="ai-summarize", step_type="AI_CALL")

        resp = authenticated_client.get(_url("pipeline_detail", pk=p.id))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == p.id
        assert data["name"] == "detailed"
        assert len(data["steps"]) == 2
        assert data["steps"][0]["id"] == s1.id
        assert data["steps"][0]["name"] == "extract"
        assert data["steps"][0]["order"] == 0
        assert data["steps"][1]["id"] == s2.id
        assert data["steps"][1]["step_type"] == "AI_CALL"
        assert data["steps"][1]["config"] == {"model": "openai/gpt-4o"}

    def test_pipeline_without_steps(self, authenticated_client):
        """Pipeline with no steps returns empty steps list."""
        p = _create_pipeline("no-steps")
        resp = authenticated_client.get(_url("pipeline_detail", pk=p.id))
        assert resp.status_code == 200
        assert resp.json()["steps"] == []

    def test_not_found(self, authenticated_client):
        """Non-existent pipeline returns 404."""
        resp = authenticated_client.get(_url("pipeline_detail", pk=99999))
        assert resp.status_code == 404
        assert resp.json()["error"] == "Not found"

    def test_returns_inactive_pipeline(self, authenticated_client):
        """Detail view returns even inactive pipelines."""
        p = _create_pipeline("inactive", active=False)
        resp = authenticated_client.get(_url("pipeline_detail", pk=p.id))
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        p = _create_pipeline("test")
        resp = api_client.get(_url("pipeline_detail", pk=p.id))
        assert resp.status_code == 401
