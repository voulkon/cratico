"""
Unit tests for notification models.

These tests focus on model logic, validation, and methods in isolation.
"""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestNotificationSubscriptionModel:
    """Test NotificationSubscription model behavior"""

    def test_subscription_type_property_organization(self, notification_subscription):
        """Test subscription_type returns 'organization' for org subscriptions"""
        assert notification_subscription.subscription_type == "organization"

    def test_subscription_type_property_entity(self, entity_subscription):
        """Test subscription_type returns 'entity' for entity subscriptions"""
        assert entity_subscription.subscription_type == "entity"

    def test_subscription_type_property_relationship(self, relationship_subscription):
        """Test subscription_type returns 'relationship' for relationship subscriptions"""
        assert relationship_subscription.subscription_type == "relationship"

    def test_subscription_defaults(self, user, organization):
        """Test default values are set correctly"""
        from conftest import NotificationSubscriptionFactory

        sub = NotificationSubscriptionFactory(user=user, organization=organization)

        assert sub.is_active is True
        assert sub.check_frequency == "daily"
        assert sub.last_checked is None
        assert sub.keywords == []
        assert sub.amount_min is None
        assert sub.amount_max is None

    def test_subscription_string_representation(self, notification_subscription):
        """Test __str__ method returns meaningful representation"""
        string_repr = str(notification_subscription)
        assert (
            notification_subscription.user.username in string_repr
            or notification_subscription.organization.label in string_repr
        )

    def test_subscription_created_at_set_automatically(self, notification_subscription):
        """Test that created_at is set automatically"""
        assert notification_subscription.created_at is not None
        assert notification_subscription.created_at <= timezone.now()

    def test_multiple_subscriptions_for_same_user(self, user):
        """Test user can have multiple subscriptions"""
        from conftest import NotificationSubscriptionFactory, OrganizationFactory

        org1 = OrganizationFactory()
        org2 = OrganizationFactory()

        sub1 = NotificationSubscriptionFactory(user=user, organization=org1)
        sub2 = NotificationSubscriptionFactory(user=user, organization=org2)

        assert user.notification_subscriptions.count() == 2
        assert sub1.id != sub2.id

    def test_subscription_with_keyword_list(self, user, organization):
        """Test keywords are stored as list"""
        from conftest import NotificationSubscriptionFactory

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            keywords=["contract", "tender", "διαγωνισμός"],
        )

        assert isinstance(sub.keywords, list)
        assert len(sub.keywords) == 3
        assert "contract" in sub.keywords

    def test_subscription_with_amount_range(self, user, organization):
        """Test amount filtering fields"""
        from conftest import NotificationSubscriptionFactory

        sub = NotificationSubscriptionFactory(
            user=user,
            organization=organization,
            amount_min=Decimal("10000.00"),
            amount_max=Decimal("100000.00"),
        )

        assert sub.amount_min == Decimal("10000.00")
        assert sub.amount_max == Decimal("100000.00")


@pytest.mark.skip(reason="Deprecated Model")
class TestNotificationModel:
    """Test Notification model behavior"""

    def test_notification_defaults(self, notification):
        """Test default values for notifications"""
        assert notification.is_read is False
        assert notification.is_dismissed is False
        assert notification.read_at is None
        assert notification.created_at is not None

    def test_notification_read_timestamp_updated(self, notification):
        """Test that read_at is set when marking as read"""
        assert notification.read_at is None

        notification.is_read = True
        notification.read_at = timezone.now()
        notification.save()

        assert notification.read_at is not None

    def test_notification_string_representation(self, notification):
        """Test __str__ method returns meaningful representation"""
        string_repr = str(notification)
        assert (
            notification.decision.ada in string_repr
            or notification.user.username in string_repr
        )

    def test_notification_foreign_key_relationships(self, notification):
        """Test that foreign key relationships work correctly"""
        assert notification.user is not None
        assert notification.subscription is not None
        assert notification.decision is not None

        # Test reverse relationships
        assert notification in notification.user.notifications.all()
        assert notification in notification.subscription.notifications.all()

    def test_notification_match_details_json_field(
        self, user, notification_subscription, decision
    ):
        """Test match_details JSONField stores arbitrary data"""
        from conftest import NotificationFactory

        match_details = {
            "matched_on": "keyword",
            "keywords_found": ["contract", "urgent"],
            "confidence": 0.95,
        }

        notification = NotificationFactory(
            user=user,
            subscription=notification_subscription,
            decision=decision,
            match_details=match_details,
        )

        assert notification.match_details == match_details
        assert notification.match_details["matched_on"] == "keyword"
        assert len(notification.match_details["keywords_found"]) == 2

    def test_notification_cascade_delete_with_user(self, notification):
        """Test that notifications are deleted when user is deleted"""
        notification_id = notification.id
        user = notification.user

        user.delete()

        from notifications.models import Notification

        assert not Notification.objects.filter(id=notification_id).exists()

    def test_notification_cascade_delete_with_subscription(self, notification):
        """Test that notifications are deleted when subscription is deleted"""
        notification_id = notification.id
        subscription = notification.subscription

        subscription.delete()

        from notifications.models import Notification

        assert not Notification.objects.filter(id=notification_id).exists()


class TestNotificationQuerysets:
    """Test custom querysets and managers if they exist"""

    def test_filter_unread_notifications(self, user, unread_notifications):
        """Test filtering for unread notifications"""
        from notifications.models import NotificationBatch

        unread = NotificationBatch.objects.filter(user=user, is_read=False)
        assert unread.count() == len(unread_notifications)

    def test_filter_by_subscription_type(self, user, multiple_subscriptions):
        """Test filtering notifications by subscription type"""
        from conftest import DecisionFactory, NotificationFactory
        from notifications.models import Notification

        # Create notification for each subscription
        for sub in multiple_subscriptions.values():
            decision = DecisionFactory()
            NotificationFactory(user=user, subscription=sub, decision=decision)

        # Filter by organization subscriptions
        org_notifications = Notification.objects.filter(
            user=user,
            subscription__organization__isnull=False,
            subscription__entity__isnull=True,
        )

        assert org_notifications.count() == 2  # org_sub_1 and org_sub_2

    def test_notifications_ordered_by_created_at(self, user):
        """Test that notifications are ordered by created_at desc by default"""
        from conftest import NotificationFactory
        from notifications.models import Notification

        # Create notifications with different timestamps
        old_notification = NotificationFactory(user=user)
        old_notification.created_at = timezone.now() - timedelta(hours=2)
        old_notification.save()

        new_notification = NotificationFactory(user=user)

        # Default ordering should be newest first
        notifications = list(Notification.objects.filter(user=user))

        # Verify ordering (if model has Meta.ordering set)
        # Otherwise this test documents the expected behavior
        assert notifications[0].created_at >= notifications[-1].created_at
