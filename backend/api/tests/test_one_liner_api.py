"""
API tests for the per-decision one-liner:

- Decision detail payload: ``one_liners`` attempts array (newest first) and
  ``default_one_liner`` (latest COMPLETED across lineages).
- ``POST /api/ai/decisions/<ref>/one-liner/``: idempotent
  ``already_completed`` without force; dispatch on miss; ``force`` always
  dispatches.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
from core.models.one_liner_config import OneLinerConfig

pytestmark = pytest.mark.django_db

CONFIG_KWARGS = dict(
    prompt_kind="batch_one_liner",
    system_prompt="Be brief.",
    prompt_template="Summarize: {{ text }}",
    provider="OPENROUTER",
    model="test/model",
    temperature=0.3,
    max_tokens=3000,
)


def _add_attempt(decision, extraction, text=None, status=OneLinerStatus.COMPLETED,
                 attempt=1, config=None, error=None, completed=False):
    config = config or OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
    row = DecisionOneLiner.objects.create(
        decision=decision,
        extraction=extraction,
        config=config,
        attempt=attempt,
        status=status,
        one_liner=text,
        error_message=error,
        cost_usd=Decimal("0.0002") if text else None,
        completed_at=timezone.now() if completed else None,
    )
    return row


class TestDecisionDetailOneLiners:
    def test_attempts_newest_first_and_default(self, authenticated_client, decision, decision_type):
        from conftest import DocumentExtractionFactory

        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        first = _add_attempt(decision, extraction, text="Πρώτη.", completed=True)
        _add_attempt(decision, extraction, text=None, status=OneLinerStatus.FAILED,
                     attempt=2, error="quota", config=first.config)

        resp = authenticated_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200

        one_liners = resp.data["one_liners"]
        assert [row["attempt"] for row in one_liners] == [2, 1]  # newest first
        assert one_liners[0]["status"] == "FAILED"
        assert one_liners[0]["error_message"] == "quota"
        assert one_liners[0]["model"] == "test/model"
        assert one_liners[0]["prompt_kind"] == "batch_one_liner"
        assert one_liners[1]["one_liner"] == "Πρώτη."
        assert one_liners[1]["cost_usd"] == "0.000200"

        # The FAILED newest attempt must not hide the COMPLETED default
        default = resp.data["default_one_liner"]
        assert default["id"] == first.id
        assert default["one_liner"] == "Πρώτη."

    def test_no_attempts_render_empty(self, authenticated_client, decision):
        resp = authenticated_client.get(f"/api/decisions/{decision.id}/")
        assert resp.status_code == 200
        assert resp.data["one_liners"] == []
        assert resp.data["default_one_liner"] is None


class TestRequestOneLinerEndpoint:
    def _post(self, client, decision, body=None):
        return client.post(f"/api/ai/decisions/{decision.id}/one-liner/", body or {}, format="json")

    def test_already_completed_without_force(self, authenticated_client, decision, decision_type):
        from conftest import DocumentExtractionFactory

        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        _add_attempt(decision, extraction, text="Έτοιμο.", completed=True)

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            resp = self._post(authenticated_client, decision)

        assert resp.status_code == 200
        assert resp.data["status"] == "already_completed"
        assert resp.data["one_liner"] == "Έτοιμο."
        assert resp.data["attempt"] == 1
        mock_delay.assert_not_called()

    def test_dispatches_on_miss(self, authenticated_client, user, decision):
        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            resp = self._post(authenticated_client, decision)

        assert resp.status_code == 202
        assert resp.data["status"] == "dispatched"
        assert resp.data["force"] is False
        mock_delay.assert_called_once_with(
            decision_id=decision.id, user_id=user.id, force=False,
        )

    def test_force_always_dispatches(self, authenticated_client, decision, decision_type):
        from conftest import DocumentExtractionFactory

        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        _add_attempt(decision, extraction, text="Έτοιμο.", completed=True)

        with patch(
            "core.tasks.tasks_decision_ai.generate_decision_one_liner.delay"
        ) as mock_delay:
            resp = self._post(authenticated_client, decision, {"force": True})

        assert resp.status_code == 202
        assert resp.data["force"] is True
        mock_delay.assert_called_once()

    def test_unknown_decision_404(self, authenticated_client):
        resp = authenticated_client.post("/api/ai/decisions/999999/one-liner/", {}, format="json")
        assert resp.status_code == 404

    def test_requires_authentication(self, api_client, decision):
        resp = api_client.post(f"/api/ai/decisions/{decision.id}/one-liner/", {}, format="json")
        assert resp.status_code in (401, 403)
