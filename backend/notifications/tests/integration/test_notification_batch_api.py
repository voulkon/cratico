"""
Integration tests for Notification Batch API endpoints.

Tests verify:
- Batch listing and filtering
- Batch detail retrieval
- Batch decisions pagination
- Batch management (mark-read, dismiss)
- Query parameter filters (is_read, is_dismissed, subscription_id)
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestNotificationBatchListAPI:
    """
    Test listing notification batches with various filters.
    """

    def test_list_batches(self, authenticated_client, user, notification_subscription):
        """Test basic batch listing"""
        from conftest import NotificationBatchFactory

        # Create some batches
        batch1 = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=5
        )
        batch2 = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=3
        )

        response = authenticated_client.get("/api/notifications/batches/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 2

        # Verify response structure
        first_batch = response.data[0]
        assert "id" in first_batch
        assert "subscription" in first_batch
        assert "subscription_alias" in first_batch
        assert "match_count" in first_batch
        assert "check_window_start" in first_batch
        assert "check_window_end" in first_batch
        assert "is_read" in first_batch
        assert "is_dismissed" in first_batch

    def test_filter_batches_by_read_status(
        self, authenticated_client, user, notification_subscription
    ):
        """Test filtering batches by read status"""
        from conftest import NotificationBatchFactory

        # Create read and unread batches
        read_batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, is_read=True
        )
        unread_batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, is_read=False
        )

        # Get only unread
        response = authenticated_client.get("/api/notifications/batches/?is_read=false")
        assert response.status_code == status.HTTP_200_OK
        batch_ids = [b["id"] for b in response.data]
        assert unread_batch.id in batch_ids
        assert read_batch.id not in batch_ids

        # Get only read
        response = authenticated_client.get("/api/notifications/batches/?is_read=true")
        assert response.status_code == status.HTTP_200_OK
        batch_ids = [b["id"] for b in response.data]
        assert read_batch.id in batch_ids
        assert unread_batch.id not in batch_ids

    def test_filter_batches_by_subscription(
        self, authenticated_client, user, organization
    ):
        """Test filtering batches by subscription ID"""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
        )

        # Create two subscriptions with different organizations
        sub1 = NotificationSubscriptionFactory(user=user, organization=organization)
        organization2 = OrganizationFactory()
        sub2 = NotificationSubscriptionFactory(user=user, organization=organization2)

        # Create batches for each
        batch1 = NotificationBatchFactory(user=user, subscription=sub1)
        batch2 = NotificationBatchFactory(user=user, subscription=sub2)

        # Filter by subscription 1
        response = authenticated_client.get(
            f"/api/notifications/batches/?subscription_id={sub1.id}"
        )
        assert response.status_code == status.HTTP_200_OK
        batch_ids = [b["id"] for b in response.data]
        assert batch1.id in batch_ids
        assert batch2.id not in batch_ids

    def test_user_only_sees_own_batches(self, authenticated_client, user, api_client):
        """Test that users can only see their own batches"""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        # Create another user with a batch
        other_user = UserFactory()
        other_org = OrganizationFactory()
        other_sub = NotificationSubscriptionFactory(
            user=other_user, organization=other_org
        )
        other_batch = NotificationBatchFactory(user=other_user, subscription=other_sub)

        # Authenticated user's batch
        my_org = OrganizationFactory()
        my_sub = NotificationSubscriptionFactory(user=user, organization=my_org)
        my_batch = NotificationBatchFactory(user=user, subscription=my_sub)

        # User should only see their batch
        response = authenticated_client.get("/api/notifications/batches/")
        assert response.status_code == status.HTTP_200_OK

        batch_ids = [b["id"] for b in response.data]
        assert my_batch.id in batch_ids
        assert other_batch.id not in batch_ids


class TestNotificationBatchDetailAPI:
    """
    Test retrieving individual batch details.
    """

    def test_get_batch_detail(
        self, authenticated_client, user, notification_subscription
    ):
        """Test retrieving batch details"""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=10,
            aggregate_stats={
                "total_amount": 50000.0,
                "avg_amount": 5000.0,
                "decision_types": {"Α.1": 6, "Β.2": 4},
            },
        )

        response = authenticated_client.get(f"/api/notifications/batches/{batch.id}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["id"] == batch.id
        assert response.data["match_count"] == 10
        assert "subscription" in response.data
        assert "aggregate_stats" in response.data
        assert response.data["aggregate_stats"]["total_amount"] == 50000.0

    def test_cannot_access_other_users_batch(self, authenticated_client, user):
        """Test that users cannot access other users' batches"""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        # Create another user's batch
        other_user = UserFactory()
        other_org = OrganizationFactory()
        other_sub = NotificationSubscriptionFactory(
            user=other_user, organization=other_org
        )
        other_batch = NotificationBatchFactory(user=other_user, subscription=other_sub)

        # Try to access it
        response = authenticated_client.get(
            f"/api/notifications/batches/{other_batch.id}/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestNotificationBatchDecisionsAPI:
    """
    Test the paginated decisions endpoint for a batch.
    """

    def test_get_batch_decisions(
        self, authenticated_client, user, notification_subscription
    ):
        """Test retrieving decisions in a batch"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=5
        )

        # Create 5 decisions in the batch
        batch_decisions = []
        for i in range(5):
            decision = DecisionFactory(
                organization=notification_subscription.organization,
                subject=f"Decision {i+1}",
            )
            bd = NotificationBatchDecisionFactory(
                batch=batch, decision=decision, match_reason="organization_match"
            )
            batch_decisions.append(bd)

        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/decisions/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 5

        # Verify response structure
        first_item = response.data["results"][0]
        assert "id" in first_item
        assert "decision" in first_item
        assert "match_reason" in first_item
        assert "match_details" in first_item
        assert "is_viewed" in first_item

        # Verify decision nested data
        assert "ada" in first_item["decision"]
        assert "subject" in first_item["decision"]
        assert "organization" in first_item["decision"]
        assert "label" in first_item["decision"]["organization"]

    def test_batch_decisions_pagination(
        self, authenticated_client, user, notification_subscription
    ):
        """Test pagination of batch decisions"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=25
        )

        # Create 25 decisions
        for i in range(25):
            decision = DecisionFactory(
                organization=notification_subscription.organization
            )
            NotificationBatchDecisionFactory(batch=batch, decision=decision)

        # Get first page with page_size=10
        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/decisions/?page_size=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10
        assert response.data["count"] == 25
        assert response.data["next"] is not None

        # Get second page
        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/decisions/?page=2&page_size=10"
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10

    def test_filter_batch_decisions_by_viewed(
        self, authenticated_client, user, notification_subscription
    ):
        """Test filtering batch decisions by viewed status"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription
        )

        # Create viewed and unviewed decisions
        viewed_decision = DecisionFactory(
            organization=notification_subscription.organization
        )
        viewed_bd = NotificationBatchDecisionFactory(
            batch=batch, decision=viewed_decision, is_viewed=True
        )

        unviewed_decision = DecisionFactory(
            organization=notification_subscription.organization
        )
        unviewed_bd = NotificationBatchDecisionFactory(
            batch=batch, decision=unviewed_decision, is_viewed=False
        )

        # Get only unviewed
        response = authenticated_client.get(
            f"/api/notifications/batches/{batch.id}/decisions/?is_viewed=false"
        )
        assert response.status_code == status.HTTP_200_OK
        decision_ids = [item["decision"]["id"] for item in response.data["results"]]
        assert unviewed_decision.id in decision_ids
        assert viewed_decision.id not in decision_ids


class TestNotificationBatchManagement:
    """
    Test batch management operations (mark-read, dismiss).
    """

    def test_mark_batch_as_read(
        self, authenticated_client, user, notification_subscription
    ):
        """Test marking a batch as read"""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, is_read=False
        )

        response = authenticated_client.post(
            f"/api/notifications/batches/{batch.id}/mark-read/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "marked as read"
        assert response.data["batch_id"] == batch.id

        # Verify batch was updated
        batch.refresh_from_db()
        assert batch.is_read is True
        assert batch.read_at is not None

    def test_dismiss_batch(self, authenticated_client, user, notification_subscription):
        """Test dismissing a batch"""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, is_dismissed=False
        )

        response = authenticated_client.post(
            f"/api/notifications/batches/{batch.id}/dismiss/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "dismissed"
        assert response.data["batch_id"] == batch.id

        # Verify batch was updated
        batch.refresh_from_db()
        assert batch.is_dismissed is True
        assert batch.dismissed_at is not None

    def test_get_unread_batch_count(
        self, authenticated_client, user, notification_subscription
    ):
        """Test getting count of unread batches"""
        from conftest import NotificationBatchFactory

        # Create 3 unread and 2 read batches
        for _ in range(3):
            NotificationBatchFactory(
                user=user, subscription=notification_subscription, is_read=False
            )

        for _ in range(2):
            NotificationBatchFactory(
                user=user, subscription=notification_subscription, is_read=True
            )

        response = authenticated_client.get("/api/notifications/batches/unread-count/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["unread_count"] == 3

    def test_dismissed_batches_not_in_unread_count(
        self, authenticated_client, user, notification_subscription
    ):
        """Test that dismissed batches don't count as unread"""
        from conftest import NotificationBatchFactory

        # Create unread but dismissed batch
        NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            is_read=False,
            is_dismissed=True,
        )

        # Create unread not dismissed batch
        NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            is_read=False,
            is_dismissed=False,
        )

        response = authenticated_client.get("/api/notifications/batches/unread-count/")

        assert response.status_code == status.HTTP_200_OK
        assert response.data["unread_count"] == 1


class TestNotificationBatchPermissions:
    """
    Test that batch API endpoints enforce proper permissions.
    """

    def test_unauthenticated_cannot_list_batches(self, api_client):
        """Test that unauthenticated users cannot list batches"""
        response = api_client.get("/api/notifications/batches/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_unauthenticated_cannot_get_batch_detail(
        self, api_client, user, notification_subscription
    ):
        """Test that unauthenticated users cannot get batch details"""
        from conftest import NotificationBatchFactory

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription
        )

        response = api_client.get(f"/api/notifications/batches/{batch.id}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_cannot_modify_other_users_batch(self, authenticated_client):
        """Test that users cannot modify other users' batches"""
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        # Create another user's batch
        other_user = UserFactory()
        other_org = OrganizationFactory()
        other_sub = NotificationSubscriptionFactory(
            user=other_user, organization=other_org
        )
        other_batch = NotificationBatchFactory(user=other_user, subscription=other_sub)

        # Try to mark as read
        response = authenticated_client.post(
            f"/api/notifications/batches/{other_batch.id}/mark-read/"
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

        # Verify batch wasn't modified
        other_batch.refresh_from_db()
        assert other_batch.is_read is False


class TestNotificationBatchIntegration:
    """
    Integration tests combining batch creation and API access.
    """

    def test_complete_batch_workflow(
        self, authenticated_client, user, organization, celery_eager_mode
    ):
        """
        Test complete workflow:
        1. Create subscription
        2. Create matching decisions
        3. Run check task (creates batch)
        4. List batches via API
        5. Get batch decisions
        6. Mark as read
        """
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Step 1: Create subscription
        subscription = NotificationSubscriptionFactory(
            user=user, organization=organization, check_frequency="daily"
        )
        subscription.last_checked = timezone.now() - timedelta(days=1)
        subscription.save()

        # Step 2: Create matching decisions
        for i in range(5):
            DecisionFactory(
                organization=organization,
                publish_timestamp=timezone.now() - timedelta(hours=i),
            )

        # Step 3: Run check task
        result = check_single_subscription(subscription.id, use_batch=True)
        assert result["notifications_created"] >= 1

        # Step 4: List batches
        response = authenticated_client.get("/api/notifications/batches/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1

        batch_id = response.data[0]["id"]
        assert response.data[0]["match_count"] >= 5

        # Step 5: Get batch decisions
        response = authenticated_client.get(
            f"/api/notifications/batches/{batch_id}/decisions/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) >= 5

        # Step 6: Mark as read
        response = authenticated_client.post(
            f"/api/notifications/batches/{batch_id}/mark-read/"
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify unread count decreased
        response = authenticated_client.get("/api/notifications/batches/unread-count/")
        assert response.data["unread_count"] == 0
