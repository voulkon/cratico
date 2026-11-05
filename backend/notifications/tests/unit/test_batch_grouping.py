"""Batch grouping at creation and aggregate stats from the actual rows."""

from datetime import timedelta

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestBatchGroupingAtCreation:
    def test_daily_digest_user_gets_one_group_per_period(
        self, user, notification_subscription, decision
    ):
        from conftest import DecisionFactory
        from notifications.tasks.notification_tasks import create_batch_for_matches

        preference = user.notification_preference
        preference.email_mode = "daily_digest"
        preference.digest_hour_local = 8
        preference.save(update_fields=["email_mode", "digest_hour_local"])

        end = timezone.now()
        start = end - timedelta(days=1)
        first = create_batch_for_matches(
            notification_subscription, [decision], start, end
        )
        second = create_batch_for_matches(
            notification_subscription,
            [DecisionFactory()],
            start + timedelta(minutes=1),
            end + timedelta(minutes=1),
        )

        from notifications.models import NotificationBatch, NotificationBatchGroup

        b1 = NotificationBatch.objects.get(id=first["batch_id"])
        b2 = NotificationBatch.objects.get(id=second["batch_id"])
        assert b1.group_id is not None
        assert b1.group_id == b2.group_id

        group = NotificationBatchGroup.objects.get(id=b1.group_id)
        assert group.user_id == user.id
        assert group.subscription_id == notification_subscription.id
        assert group.total_match_count == 2

    def test_every_run_user_has_no_group(self, user, notification_subscription, decision):
        from conftest import DecisionFactory
        from notifications.models import NotificationBatch
        from notifications.tasks.notification_tasks import create_batch_for_matches

        preference = user.notification_preference
        preference.email_mode = "every_run"
        preference.save(update_fields=["email_mode"])

        end = timezone.now()
        result = create_batch_for_matches(
            notification_subscription, [decision], end - timedelta(days=1), end
        )
        batch = NotificationBatch.objects.get(id=result["batch_id"])
        assert batch.group_id is None

        second = create_batch_for_matches(
            notification_subscription,
            [DecisionFactory()],
            end,
            end + timedelta(minutes=1),
        )
        assert NotificationBatch.objects.get(id=second["batch_id"]).group_id is None


class TestAggregateStats:
    def test_stats_cover_all_junction_rows(self, user, notification_subscription):
        from conftest import (
            DecisionFactory,
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )
        from notifications.tasks.notification_tasks import (
            compute_batch_aggregate_stats,
        )

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription
        )
        d1 = DecisionFactory(amount=10)
        d2 = DecisionFactory(amount=30)
        NotificationBatchDecisionFactory(batch=batch, decision=d1)
        NotificationBatchDecisionFactory(batch=batch, decision=d2)

        stats = compute_batch_aggregate_stats(batch)

        assert stats["total_amount"] == 40
        assert stats["avg_amount"] == 20
        assert stats["min_amount"] == 10
        assert stats["max_amount"] == 30
        assert stats["decision_type_counts"] == stats["decision_types"]
