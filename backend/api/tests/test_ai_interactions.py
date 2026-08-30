"""
Tests for AI Interactions endpoints:

- GET /api/ai/interactions/
- GET /api/ai/interactions/summary/
- GET /api/ai/interactions/<id>/
- GET /api/ai/interactions/system-report/  (admin only)
"""

import csv
import io
from datetime import date

import pytest
from django.urls import reverse
from django.utils import timezone

from core.models.ai_interaction_log import AIInteractionLog


# ============================================================================
# Helpers
# ============================================================================


def _url(name: str, **kwargs) -> str:
    return reverse(f"ai_{name}", kwargs=kwargs)


def _create_log(user, **kwargs) -> AIInteractionLog:
    defaults = {
        "user": user,
        "billed_to": "SYSTEM",
        "trigger": "notification_batch_summary",
        "provider": "OpenRouter",
        "model_name": "openai/gpt-4o-mini",
        "input_tokens": 1000,
        "output_tokens": 500,
        "cost_usd": "0.003",
        "latency_ms": 420,
        "status": "SUCCESS",
    }
    defaults.update(kwargs)
    return AIInteractionLog.objects.create(**defaults)


# ============================================================================
# GET /api/ai/interactions/ — paginated list
# ============================================================================


@pytest.mark.django_db
class TestInteractionsList:
    def test_returns_user_interactions(self, authenticated_client, user):
        """Only the requesting user's interactions are returned."""
        _create_log(user)
        _create_log(user, trigger="import")

        resp = authenticated_client.get(_url("interactions_list"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 2
        assert len(data["results"]) == 2

    def test_pagination(self, authenticated_client, user):
        """Respects page and page_size params."""
        for i in range(5):
            _create_log(user, trigger_ref=f"ref-{i}")

        resp = authenticated_client.get(
            _url("interactions_list"), {"page_size": 2, "page": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 5
        assert data["page"] == 2
        assert data["page_size"] == 2
        assert len(data["results"]) == 2

    def test_filter_by_provider(self, authenticated_client, user):
        """Filter interactions by provider."""
        _create_log(user, provider="OpenRouter")
        _create_log(user, provider="AWS Bedrock")

        resp = authenticated_client.get(
            _url("interactions_list"), {"provider": "AWS Bedrock"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["results"][0]["provider"] == "AWS Bedrock"

    def test_filter_by_model(self, authenticated_client, user):
        """Filter interactions by model name substring."""
        _create_log(user, model_name="openai/gpt-4o")
        _create_log(user, model_name="google/gemini-flash")

        resp = authenticated_client.get(
            _url("interactions_list"), {"model": "gemini"}
        )
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_filter_by_trigger(self, authenticated_client, user):
        """Filter interactions by trigger type."""
        _create_log(user, trigger="import")
        _create_log(user, trigger="notification_batch_summary")

        resp = authenticated_client.get(
            _url("interactions_list"), {"trigger": "import"}
        )
        assert resp.json()["count"] == 1

    def test_filter_by_date_range(self, authenticated_client, user):
        """Filter by date_from and date_to."""
        _create_log(user)
        resp = authenticated_client.get(
            _url("interactions_list"),
            {"date_from": "2020-01-01", "date_to": "2030-12-31"},
        )
        assert resp.json()["count"] == 1

    def test_isolates_users(self, authenticated_client, user):
        """User A cannot see User B's interactions."""
        from conftest import UserFactory

        other = UserFactory(username="other-user")
        _create_log(user, trigger="mine")
        _create_log(other, trigger="other")

        resp = authenticated_client.get(_url("interactions_list"))
        assert resp.json()["count"] == 1
        assert resp.json()["results"][0]["trigger"] == "mine"

    def test_serialization_format(self, authenticated_client, user):
        """Each log is serialized with all expected fields."""
        log = _create_log(user)

        resp = authenticated_client.get(_url("interactions_list"))
        item = resp.json()["results"][0]
        assert item["id"] == log.id
        assert item["user"] == user.id
        assert item["billed_to"] == "SYSTEM"
        assert item["trigger"] == "notification_batch_summary"
        assert item["provider"] == "OpenRouter"
        assert item["model_name"] == "openai/gpt-4o-mini"
        assert item["input_tokens"] == 1000
        assert item["output_tokens"] == 500
        assert item["cost_usd"] == "0.003000"
        assert item["latency_ms"] == 420
        assert item["status"] == "SUCCESS"
        assert item["pipeline_run"] is None
        assert item["pipeline_step_run"] is None

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        resp = api_client.get(_url("interactions_list"))
        assert resp.status_code == 401


# ============================================================================
# GET /api/ai/interactions/summary/
# ============================================================================


@pytest.mark.django_db
class TestInteractionsSummary:
    def test_returns_spend_summary(self, authenticated_client, user):
        """Summary aggregates cost, tokens, and provider breakdown."""
        _create_log(user, provider="OpenRouter", input_tokens=100, output_tokens=50, cost_usd="0.001")
        _create_log(user, provider="OpenRouter", input_tokens=200, output_tokens=60, cost_usd="0.002")
        _create_log(user, provider="AWS Bedrock", input_tokens=300, output_tokens=70, cost_usd="0.003")

        resp = authenticated_client.get(_url("interactions_summary"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["call_count"] == 3
        assert data["total_cost_usd"] == "0.006000"
        assert data["total_input_tokens"] == 600
        assert data["total_output_tokens"] == 180
        assert len(data["by_provider"]) >= 2

    def test_filter_by_month(self, authenticated_client, user):
        """Month parameter filters to a specific month."""
        _create_log(user, cost_usd="0.001")
        # Use a month that doesn't include recent data
        resp = authenticated_client.get(
            _url("interactions_summary"), {"month": "2000-01"}
        )
        assert resp.status_code == 200
        assert resp.json()["call_count"] == 0

    def test_invalid_month_format(self, authenticated_client):
        """Invalid month returns 400."""
        resp = authenticated_client.get(
            _url("interactions_summary"), {"month": "not-a-date"}
        )
        assert resp.status_code == 400
        assert "Invalid month format" in resp.json()["error"]

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        resp = api_client.get(_url("interactions_summary"))
        assert resp.status_code == 401


# ============================================================================
# GET /api/ai/interactions/<id>/
# ============================================================================


@pytest.mark.django_db
class TestInteractionsDetail:
    def test_returns_own_interaction(self, authenticated_client, user):
        """User can retrieve their own interaction."""
        log = _create_log(user)
        resp = authenticated_client.get(_url("interaction_detail", pk=log.id))
        assert resp.status_code == 200
        assert resp.json()["id"] == log.id

    def test_cannot_see_other_users_interaction(self, authenticated_client, user):
        """User cannot see another user's interaction."""
        from conftest import UserFactory

        other = UserFactory(username="other-user")
        log = _create_log(other)
        resp = authenticated_client.get(_url("interaction_detail", pk=log.id))
        assert resp.status_code == 404

    def test_not_found(self, authenticated_client):
        """Non-existent ID returns 404."""
        resp = authenticated_client.get(_url("interaction_detail", pk=99999))
        assert resp.status_code == 404

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        resp = api_client.get(_url("interaction_detail", pk=1))
        assert resp.status_code == 401


# ============================================================================
# GET /api/ai/interactions/system-report/  (admin only)
# ============================================================================


@pytest.mark.django_db
class TestInteractionsSystemReport:
    def test_admin_can_download_csv(self, admin_client, admin_user):
        """Admin gets a CSV with SYSTEM-billed rows."""
        _create_log(admin_user, billed_to="SYSTEM", cost_usd="0.005")
        _create_log(admin_user, billed_to="USER", cost_usd="0.010")

        resp = admin_client.get(_url("system_report"))
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        assert "attachment" in resp["Content-Disposition"]

        # Parse CSV
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8")))
        rows = list(reader)
        assert len(rows) == 1  # Only SYSTEM row
        assert rows[0]["cost_usd"] == "0.005000"

    def test_filters_by_month(self, admin_client, admin_user):
        """Month parameter scopes the CSV."""
        _create_log(admin_user, billed_to="SYSTEM")
        resp = admin_client.get(
            _url("system_report"), {"month": "2000-01"}
        )
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8")))
        assert len(list(reader)) == 0  # No data in that month

    def test_invalid_month(self, admin_client):
        """Invalid month returns 400."""
        resp = admin_client.get(
            _url("system_report"), {"month": "bad"}
        )
        assert resp.status_code == 400

    def test_non_admin_gets_403(self, authenticated_client):
        """Regular users cannot access system report."""
        resp = authenticated_client.get(_url("system_report"))
        assert resp.status_code == 403

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests get 401."""
        resp = api_client.get(_url("system_report"))
        assert resp.status_code == 401

    def test_csv_columns_match_expected(self, admin_client, admin_user):
        """CSV header matches defined columns."""
        _create_log(admin_user, billed_to="SYSTEM")
        resp = admin_client.get(_url("system_report"))
        reader = csv.DictReader(io.StringIO(resp.content.decode("utf-8")))
        expected_columns = [
            "user_id", "email", "provider", "model",
            "tokens_in", "tokens_out", "cost_usd", "trigger", "date",
        ]
        assert reader.fieldnames == expected_columns
