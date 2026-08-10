"""
Integration tests for Subscription History (All Decisions) API endpoint.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestSubscriptionHistoryAPI:
    """Test the all-decisions endpoint for subscriptions."""

    def test_get_subscription_all_decisions_basic(
        self, authenticated_client, user, notification_subscription
    ):
        """Test basic retrieval of all decisions from subscription"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        # Create 2 batches
        batch1 = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            check_window_start=timezone.now() - timedelta(days=2),
            check_window_end=timezone.now() - timedelta(days=1),
            match_count=3,
        )
        batch2 = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            check_window_start=timezone.now() - timedelta(days=1),
            check_window_end=timezone.now(),
            match_count=2,
        )

        # Add 3 decisions to batch1
        for i in range(3):
            decision = DecisionFactory(
                ada=f"BATCH1-{i}",
                subject=f"Decision {i} for batch 1",
                organization=notification_subscription.organization,
                issue_date=timezone.now() - timedelta(days=2),
                amount=Decimal(f"{1000 * (i+1)}"),
            )
            NotificationBatchDecisionFactory(
                batch=batch1, subscription=notification_subscription, decision=decision
            )

        # Add 2 decisions to batch2
        for i in range(2):
            decision = DecisionFactory(
                ada=f"BATCH2-{i}",
                subject=f"Decision {i} for batch 2",
                organization=notification_subscription.organization,
                issue_date=timezone.now() - timedelta(days=1),
                amount=Decimal(f"{5000 * (i+1)}"),
            )
            NotificationBatchDecisionFactory(
                batch=batch2, subscription=notification_subscription, decision=decision
            )

        # Get all decisions
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 5
        assert response.data["count"] == 5

        # Check metadata
        assert "metadata" in response.data
        assert response.data["metadata"]["total_batches"] == 2
        assert "subscription" in response.data["metadata"]
        assert "date_range" in response.data["metadata"]
        assert response.data["metadata"]["date_range"]["from"] is not None
        assert response.data["metadata"]["date_range"]["to"] is not None

    def test_all_decisions_pagination(
        self, authenticated_client, user, notification_subscription
    ):
        """Test pagination of all decisions"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        # Create a batch
        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            check_window_start=timezone.now() - timedelta(days=1),
            check_window_end=timezone.now(),
            match_count=25,
        )

        # Add 25 decisions
        for i in range(25):
            decision = DecisionFactory(
                ada=f"ADA-{i:03d}",
                subject=f"Decision {i}",
                organization=notification_subscription.organization,
                issue_date=timezone.now() - timedelta(days=1),
                amount=Decimal(f"{1000 * (i+1)}"),
            )
            NotificationBatchDecisionFactory(
                batch=batch, subscription=notification_subscription, decision=decision
            )

        # Get page 1 with 10 items per page
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?page=1&page_size=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 25
        assert len(response.data["results"]) == 10
        assert response.data["next"] is not None
        assert response.data["previous"] is None

        # Get page 2
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?page=2&page_size=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 10
        assert response.data["next"] is not None
        assert response.data["previous"] is not None

        # Get page 3 (last page, should have 5 items)
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?page=3&page_size=10"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data["results"]) == 5
        assert response.data["next"] is None
        assert response.data["previous"] is not None

    def test_all_decisions_sorting(
        self, authenticated_client, user, notification_subscription
    ):
        """Test sorting by recent, oldest, amount"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            check_window_start=timezone.now() - timedelta(days=5),
            check_window_end=timezone.now(),
            match_count=3,
        )

        # Create decisions with different dates and amounts
        decisions_data = [
            {"ada": "ADA-001", "date_offset": 3, "amount": 10000},
            {"ada": "ADA-002", "date_offset": 1, "amount": 5000},
            {"ada": "ADA-003", "date_offset": 2, "amount": 15000},
        ]

        for data in decisions_data:
            decision = DecisionFactory(
                ada=data["ada"],
                subject=f"Decision {data['ada']}",
                organization=notification_subscription.organization,
                issue_date=timezone.now() - timedelta(days=data["date_offset"]),
                amount=Decimal(data["amount"]),
            )
            NotificationBatchDecisionFactory(
                batch=batch, subscription=notification_subscription, decision=decision
            )

        # Test sort by recent (default)
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?sort=recent"
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            response.data["results"][0]["decision"]["ada"] == "ADA-002"
        )  # Most recent (1 day ago)
        assert (
            response.data["results"][2]["decision"]["ada"] == "ADA-001"
        )  # Oldest (3 days ago)

        # Test sort by oldest
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?sort=oldest"
        )
        assert response.status_code == status.HTTP_200_OK
        assert (
            response.data["results"][0]["decision"]["ada"] == "ADA-001"
        )  # Oldest first
        assert (
            response.data["results"][2]["decision"]["ada"] == "ADA-002"
        )  # Most recent last

        # Test sort by amount_desc
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?sort=amount_desc"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["decision"]["amount"] == 15000.0
        assert response.data["results"][2]["decision"]["amount"] == 5000.0

        # Test sort by amount_asc
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?sort=amount_asc"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["results"][0]["decision"]["amount"] == 5000.0
        assert response.data["results"][2]["decision"]["amount"] == 15000.0

    def test_all_decisions_viewed_filter(
        self, authenticated_client, user, notification_subscription
    ):
        """Test filtering by viewed status"""
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            check_window_start=timezone.now() - timedelta(days=1),
            check_window_end=timezone.now(),
            match_count=5,
        )

        # Create 5 decisions, mark 1 as viewed
        for i in range(5):
            decision = DecisionFactory(
                ada=f"ADA-{i:03d}",
                subject=f"Decision {i}",
                organization=notification_subscription.organization,
                issue_date=timezone.now() - timedelta(days=1),
                amount=Decimal(f"{1000 * (i+1)}"),
            )
            NotificationBatchDecisionFactory(
                batch=batch,
                decision=decision,
                is_viewed=(i == 0),  # Mark the first decision as viewed
            )

        # Test filter by is_viewed=true
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?is_viewed=true"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 1

        # Test filter by is_viewed=false
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/?is_viewed=false"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 4

        # Test without filter (should return all)
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{notification_subscription.id}/all-decisions/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["count"] == 5

    def test_user_cannot_access_other_subscription(self, authenticated_client, user):
        """Test permission check - users can't access others' subscriptions"""
        from conftest import (
            NotificationSubscriptionFactory,
            OrganizationFactory,
            UserFactory,
        )

        # Create another user
        other_user = UserFactory()

        # Create an organization
        org = OrganizationFactory()

        # Create subscription for other user
        other_subscription = NotificationSubscriptionFactory(
            user=other_user, organization=org
        )

        # Try to access the other user's subscription - should return 404
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/{other_subscription.id}/all-decisions/"
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
