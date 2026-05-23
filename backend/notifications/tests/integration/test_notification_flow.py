"""
Integration tests for the complete notification flow.

These tests verify end-to-end functionality:
- User creates subscriptions via API
- Background tasks check subscriptions
- Notifications are created
- User retrieves and manages notifications
"""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


class TestCompleteNotificationFlow:
    """
    Test the complete user journey from subscription to notification.
    """

    def test_user_subscribes_and_receives_notification(
        self, authenticated_client, user, organization, decision_type, celery_eager_mode
    ):
        """
        Complete flow:
        1. User subscribes to an organization
        2. New decision is created for that organization
        3. Task runs and creates notification
        4. User sees unread notification
        5. User marks notification as read
        """
        # Step 1: User creates subscription via API
        response = authenticated_client.post(
            "/api/notifications/subscriptions/",
            {"organization_uid": organization.uid, "keywords": ["test", "contract"]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        subscription_id = response.data["id"]

        # Verify subscription was created
        from notifications.models import NotificationSubscription

        subscription = NotificationSubscription.objects.get(id=subscription_id)
        assert subscription.user == user
        assert subscription.organization == organization
        assert subscription.keywords == ["test", "contract"]

        # Step 2: Simulate a new decision being published
        from conftest import DecisionFactory

        decision = DecisionFactory(
            organization=organization,
            subject="Test contract decision",
            publish_timestamp=timezone.now(),
        )

        # Set last_checked to ensure the decision is "new"
        subscription.last_checked = timezone.now() - timedelta(days=1)
        subscription.save()

        # Step 3: Run the check task
        from notifications.tasks import check_subscriptions_for_new_decisions

        result = check_subscriptions_for_new_decisions()

        assert result["notifications_created"] >= 1

        # Step 4: User checks unread count (using batch API)
        response = authenticated_client.get("/api/notifications/batches/unread-count/")
        assert response.status_code == status.HTTP_200_OK
        assert response.data["unread_count"] >= 1

        # Step 5: User gets notification list (using batch API)
        response = authenticated_client.get("/api/notifications/batches/")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) >= 1

        batch_id = response.data[0]["id"]
        assert response.data[0]["is_read"] is False
        assert response.data[0]["match_count"] >= 1

        # Step 6: User marks batch as read
        response = authenticated_client.post(
            f"/api/notifications/batches/{batch_id}/mark-read/"
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify it's marked read
        response = authenticated_client.get("/api/notifications/batches/unread-count/")
        assert response.data["unread_count"] == 0

    def test_user_cannot_see_other_users_notifications(
        self, authenticated_client, user, api_client
    ):
        """
        Verify that users can only see their own notification batches.
        """
        from conftest import NotificationBatchFactory, UserFactory

        # Create another user with a batch
        other_user = UserFactory()
        other_batch = NotificationBatchFactory(user=other_user)

        # Create batch for authenticated user
        my_batch = NotificationBatchFactory(user=user)

        # Authenticated user should only see their batch
        response = authenticated_client.get("/api/notifications/batches/")
        assert response.status_code == status.HTTP_200_OK

        batch_ids = [n["id"] for n in response.data]
        assert my_batch.id in batch_ids
        assert other_batch.id not in batch_ids

    def test_subscription_check_frequency_respected(
        self, user, organization, celery_eager_mode
    ):
        """
        Test that check_frequency='manual' subscriptions are not checked automatically.
        """
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_subscriptions_for_new_decisions

        # Create subscription with manual check frequency
        manual_sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            check_frequency="manual",
            is_active=True,
        )
        manual_sub.last_checked = timezone.now() - timedelta(days=10)
        manual_sub.save()

        # Create a matching decision
        DecisionFactory(organization=organization, publish_timestamp=timezone.now())

        # Run scheduled task (should skip manual subscriptions)
        check_subscriptions_for_new_decisions()

        # No batches should be created for manual subscription
        from notifications.models import NotificationBatch

        batches = NotificationBatch.objects.filter(subscription=manual_sub)
        assert batches.count() == 0


class TestMultipleSubscriptionTypes:
    """
    Test different subscription types work correctly.

    NOTE: This class provides basic coverage of the main subscription types.
    For comprehensive testing of all subscription type combinations and filters,
    see test_subscription_types_comprehensive.py which covers:
    - All 6 target types: organization, entity, relationship, person, signer, filter-only
    - All 4 filter types: keywords, amount_min/max, decision_types
    - Complex combinations: target + multiple filters
    - Edge cases: case-insensitive matching, duplicate prevention, etc.
    """

    def test_organization_subscription(
        self, authenticated_client, user, organization, celery_eager_mode
    ):
        """Test organization-based subscription creates notifications"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.tasks import check_single_subscription

        # Create subscription
        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, check_frequency="daily"
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision
        DecisionFactory(organization=organization)

        # Check subscription
        result = check_single_subscription(sub.id)
        assert result["notifications_created"] >= 1

    def test_entity_subscription(
        self, authenticated_client, user, afm_entity, celery_eager_mode
    ):
        """Test entity-based subscription creates batch notifications"""
        from conftest import DecisionFactory, EntitySubscriptionFactory
        from notifications.models import NotificationBatch
        from notifications.tasks import check_single_subscription

        # Create entity subscription
        sub = EntitySubscriptionFactory(user=user, entity=afm_entity)
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create decision with entity relationship
        from core.models.entities import DecisionEntityRelationship, EntityRole

        decision = DecisionFactory()
        DecisionEntityRelationship.objects.create(
            decision=decision,
            entity=afm_entity,
            role=EntityRole.SPONSOR,
            parent_key_path="sponsor[0].sponsorAFMName",
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create batch
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() >= 1
        assert batches.first().match_count >= 1

    def test_keyword_filter(
        self, authenticated_client, user, organization, celery_eager_mode
    ):
        """Test keyword filtering works correctly"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.models import NotificationBatch, NotificationBatchDecision
        from notifications.tasks import check_single_subscription

        # Create subscription with keyword filter
        sub = NotificationSubscriptionFactory(
            user=user, organization=organization, keywords=["urgent", "contract"]
        )
        sub.last_checked = timezone.now() - timedelta(days=1)
        sub.save()

        # Create matching decision
        matching_decision = DecisionFactory(
            organization=organization, subject="Urgent contract renewal needed"
        )

        # Create non-matching decision
        non_matching_decision = DecisionFactory(
            organization=organization, subject="Regular administrative note"
        )

        # Check subscription
        check_single_subscription(sub.id)

        # Should create batch with only matching decision
        batches = NotificationBatch.objects.filter(subscription=sub)
        assert batches.count() == 1
        batch = batches.first()
        assert batch.match_count == 1

        # Verify the matching decision is in the batch
        batch_decisions = NotificationBatchDecision.objects.filter(batch=batch)
        assert batch_decisions.count() == 1
        assert batch_decisions.first().decision == matching_decision


class TestNotificationManagement:
    """
    Test notification batch management operations.
    """

    def test_mark_all_as_read(self, authenticated_client, unread_notifications):
        """Test marking all notification batches as read"""
        # Note: mark-all-read is not a batch endpoint in current implementation
        # This test would need a batch-specific implementation or iterate through batches
        # For now, test individual batch mark-read
        batch_id = unread_notifications[0].id
        response = authenticated_client.post(
            f"/api/notifications/batches/{batch_id}/mark-read/"
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify it's marked read
        response = authenticated_client.get("/api/notifications/batches/unread-count/")
        assert response.data["unread_count"] == len(unread_notifications) - 1

    def test_dismiss_notification(self, authenticated_client, notification):
        """Test dismissing a notification batch"""
        response = authenticated_client.post(
            f"/api/notifications/batches/{notification.id}/dismiss/"
        )
        assert response.status_code == status.HTTP_200_OK

        # Verify it's dismissed
        notification.refresh_from_db()
        assert notification.is_dismissed is True

    def test_filter_notifications_by_read_status(
        self, authenticated_client, unread_notifications, notification_with_read_status
    ):
        """Test filtering notification batches by read status"""
        # Get only unread
        response = authenticated_client.get("/api/notifications/batches/?is_read=false")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == len(unread_notifications)

        # Get only read
        response = authenticated_client.get("/api/notifications/batches/?is_read=true")
        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 1


class TestSubscriptionManagement:
    """
    Test subscription CRUD operations via API.
    """

    def test_create_organization_subscription(self, authenticated_client, organization):
        """Test creating an organization subscription"""
        response = authenticated_client.post(
            "/api/notifications/subscriptions/",
            {"organization_uid": organization.uid, "keywords": ["test"]},
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED
        assert "id" in response.data

    def test_prevent_duplicate_subscription_creation(
        self, authenticated_client, organization
    ):
        """Test that creating duplicate subscriptions is prevented"""
        # Create first subscription
        response1 = authenticated_client.post(
            "/api/notifications/subscriptions/",
            {"organization_uid": organization.uid, "keywords": ["test"]},
            format="json",
        )
        assert response1.status_code == status.HTTP_201_CREATED

        # Try to create duplicate (same user + organization)
        response2 = authenticated_client.post(
            "/api/notifications/subscriptions/",
            {
                "organization_uid": organization.uid,
                "keywords": [
                    "different",
                    "keywords",
                ],  # Different filters but same target
            },
            format="json",
        )

        # Should return 400 Bad Request
        assert response2.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response2.data
        assert (
            "already" in response2.data["error"].lower()
            or "exists" in response2.data["error"].lower()
        )

    def test_update_subscription(self, authenticated_client, notification_subscription):
        """Test updating subscription filters"""
        response = authenticated_client.patch(
            f"/api/notifications/subscriptions/{notification_subscription.id}/",
            {"keywords": ["updated", "keywords"], "is_active": False},
            format="json",
        )
        assert response.status_code == status.HTTP_200_OK

        notification_subscription.refresh_from_db()
        assert notification_subscription.keywords == ["updated", "keywords"]
        assert notification_subscription.is_active is False

    def test_delete_subscription(self, authenticated_client, notification_subscription):
        """Test deleting a subscription"""
        subscription_id = notification_subscription.id

        response = authenticated_client.delete(
            f"/api/notifications/subscriptions/{subscription_id}/"
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT

        # Verify it's deleted
        from notifications.models import NotificationSubscription

        assert not NotificationSubscription.objects.filter(id=subscription_id).exists()

    def test_check_subscription_status(
        self, authenticated_client, organization, notification_subscription
    ):
        """Test checking if user is subscribed to an organization"""
        # User is subscribed
        response = authenticated_client.get(
            f"/api/notifications/subscriptions/check-organization/{organization.uid}/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["subscribed"] is True
        assert response.data["subscription"]["id"] == notification_subscription.id

        # Check for organization user is not subscribed to
        from conftest import OrganizationFactory

        other_org = OrganizationFactory()

        response = authenticated_client.get(
            f"/api/notifications/subscriptions/check-organization/{other_org.uid}/"
        )
        assert response.status_code == status.HTTP_200_OK
        assert response.data["subscribed"] is False
        assert response.data["subscription"] is None


class TestTasksAndBackgroundJobs:
    """
    Test Celery tasks for notification checking.
    """

    def test_check_single_subscription_task(self, old_subscription, celery_eager_mode):
        """Test manual subscription check task"""
        from conftest import DecisionFactory
        from notifications.tasks import check_single_subscription

        # Create matching decision
        DecisionFactory(
            organization=old_subscription.organization, publish_timestamp=timezone.now()
        )

        # Run task
        result = check_single_subscription(
            old_subscription.id, lookback_days=15  # Covers the 10-day gap
        )

        assert result["subscription_id"] == old_subscription.id
        assert result["notifications_created"] >= 1
        assert result["lookback_days"] == 15

    def test_scheduled_task_only_checks_active_subscriptions(
        self, user, organization, celery_eager_mode
    ):
        """Test that inactive subscriptions are skipped"""
        from conftest import DecisionFactory, NotificationSubscriptionFactory
        from notifications.models.notification_batch import NotificationBatch
        from notifications.tasks import check_subscriptions_for_new_decisions

        # Create inactive subscription
        inactive_sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            is_active=False,
            check_frequency="daily",
        )

        # Create decision
        DecisionFactory(organization=organization)

        # Run scheduled task
        check_subscriptions_for_new_decisions()

        # No notification batches should be created for inactive subscription
        batches = NotificationBatch.objects.filter(subscription=inactive_sub)
        assert batches.count() == 0


class TestPerformanceAndScaling:
    """
    Test performance considerations and N+1 query prevention.
    """

    @pytest.mark.django_db(transaction=True)
    def test_notification_list_query_efficiency(
        self, authenticated_client, user, db_with_sample_data
    ):
        """
        Test that listing notifications doesn't cause N+1 queries.
        Uses select_related/prefetch_related properly.
        """
        from conftest import NotificationFactory, NotificationSubscriptionFactory
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        # Create subscriptions for each unique organization (5 total)
        subscriptions = []
        for i in range(5):
            org = db_with_sample_data["organizations"][i]
            sub = NotificationSubscriptionFactory(user=user, organization=org)
            subscriptions.append(sub)

        # Create 10 notifications distributed among those subscriptions
        for i in range(10):
            sub = subscriptions[i % 5]
            decision = db_with_sample_data["decisions"][i]
            NotificationFactory(user=user, subscription=sub, decision=decision)

        # Count queries when fetching notifications
        with CaptureQueriesContext(connection) as context:
            response = authenticated_client.get("/api/notifications/")
            assert response.status_code == status.HTTP_200_OK

        # Should be a reasonable number of queries (not 10+ due to N+1)
        # Exact number depends on pagination, but should be < 10
        assert (
            len(context.captured_queries) < 10
        ), f"Too many queries ({len(context.captured_queries)}), possible N+1 problem"
