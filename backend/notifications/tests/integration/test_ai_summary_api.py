"""
Integration tests for AI summarization API endpoints on NotificationBatch.

Tests:
- POST /api/notifications/batches/{id}/summarize/
- GET  /api/notifications/batches/{id}/summary/
"""

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestBatchSummarizeAction:
    """Tests for the ``summarize`` custom action (POST)."""

    def test_summarize_triggers_task(
        self, authenticated_client, user, notification_subscription
    ):
        """POST /batches/{id}/summarize/ triggers a celery task and returns task_id."""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )

        response = authenticated_client.post(
            f"/api/notifications/batches/{batch.id}/summarize/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json() if hasattr(response, "json") else response.data
        assert data["status"] == "started"
        assert data["batch_id"] == batch.id
        assert "task_id" in data

    def test_summarize_other_user_batch_returns_404(
        self, authenticated_client
    ):
        """Users cannot trigger summarization on another user's batch."""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        other_user = UserFactory()
        other_org = OrganizationFactory()
        other_sub = NotificationSubscriptionFactory(
            user=other_user, organization=other_org
        )
        other_batch = NotificationBatchFactory(
            user=other_user, subscription=other_sub
        )

        response = authenticated_client.post(
            f"/api/notifications/batches/{other_batch.id}/summarize/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_summarize_unauthenticated_returns_401(self, api_client, notification_batch):
        """Unauthenticated requests to summarize are rejected."""
        response = api_client.post(
            f"/api/notifications/batches/{notification_batch.id}/summarize/"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestBatchSummaryAction:
    """Tests for the ``summary`` custom action (GET)."""

    def test_summary_returns_pending_status_by_default(
        self, authenticated_client, user, notification_subscription
    ):
        """GET /batches/{id}/summary/ returns PENDING when no summary has run."""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )

        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/summary/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json() if hasattr(response, "json") else response.data
        assert data["status"] == "PENDING"
        assert data["summary"] is None
        assert data["error"] is None
        assert data["completed_at"] is None

    def test_summary_returns_completed_data(
        self, authenticated_client, user, notification_subscription
    ):
        """GET summary returns AI summary fields when populated (e.g. COMPLETED)."""
        from conftest import NotificationBatchFactory
        from core.models.pipeline import (
            BilledTo,
            PipelineDefinition,
            PipelineRun,
            RunStatus,
        )

        pipeline = PipelineDefinition.objects.create(
            name="test_pipeline",
            version=1,
            is_active=True,
        )
        run = PipelineRun.objects.create(
            pipeline=pipeline,
            status=RunStatus.COMPLETED,
            total_input_tokens=200,
            total_output_tokens=80,
            total_cost_usd="0.035",
            billed_to=BilledTo.SYSTEM,
            completed_at=timezone.now(),
        )

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=3,
            ai_summary="Synthesized summary of 3 decisions.",
            ai_summary_status="COMPLETED",
            ai_summary_run=run,
            ai_summary_error=None,
            ai_summary_completed_at=run.completed_at,
        )

        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/summary/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json() if hasattr(response, "json") else response.data
        assert data["status"] == "COMPLETED"
        assert data["summary"] == "Synthesized summary of 3 decisions."
        assert data["error"] is None
        assert data["completed_at"] is not None
        assert data["cost_usd"] == "0.035000"
        assert data["total_input_tokens"] == 200
        assert data["total_output_tokens"] == 80
        assert data["billed_to"] == "SYSTEM"

    def test_summary_returns_failed_data(
        self, authenticated_client, user, notification_subscription
    ):
        """GET summary returns error info when status is FAILED."""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
            ai_summary_status="FAILED",
            ai_summary_error="API rate limit exceeded",
            ai_summary_completed_at=timezone.now(),
        )

        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/summary/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json() if hasattr(response, "json") else response.data
        assert data["status"] == "FAILED"
        assert data["error"] == "API rate limit exceeded"
        assert data["summary"] is None

    def test_summary_other_user_batch_returns_404(
        self, authenticated_client
    ):
        """Users cannot view summary of another user's batch."""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        other_user = UserFactory()
        other_org = OrganizationFactory()
        other_sub = NotificationSubscriptionFactory(
            user=other_user, organization=other_org
        )
        other_batch = NotificationBatchFactory(
            user=other_user, subscription=other_sub
        )

        response = authenticated_client.get(
            f"/api/notifications/batches/{other_batch.id}/summary/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_summary_unauthenticated_returns_401(self, api_client, notification_batch):
        """Unauthenticated requests to summary are rejected."""
        response = api_client.get(
            f"/api/notifications/batches/{notification_batch.id}/summary/"
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_summary_without_ai_summary_run_has_no_cost(
        self, authenticated_client, user, notification_subscription
    ):
        """When batch has ai_summary but no ai_summary_run, cost/token fields are absent."""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
            ai_summary="A summary without a run record.",
            ai_summary_status="COMPLETED",
            ai_summary_run=None,
        )

        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/summary/"
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json() if hasattr(response, "json") else response.data
        assert data["status"] == "COMPLETED"
        assert data["summary"] == "A summary without a run record."
        # cost fields should not be present when no run
        assert "cost_usd" not in data
        assert "total_input_tokens" not in data
