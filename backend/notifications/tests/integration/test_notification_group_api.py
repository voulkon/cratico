"""Integration tests for the read-only notification group API."""

from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework import status

pytestmark = [pytest.mark.django_db, pytest.mark.integration]


def _make_group(user, subscription, *, start=None, end=None):
    from notifications.models import NotificationBatchGroup

    start = start or timezone.now()
    end = end or (start + timedelta(days=1))
    return NotificationBatchGroup.objects.create(
        user=user,
        subscription=subscription,
        period_start=start,
        period_end=end,
        local_date=timezone.localtime(end).date(),
    )


def _make_shared_one_liner(decision):
    from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
    from core.models.one_liner_config import OneLinerConfig

    config = OneLinerConfig.get_or_create_for(
        prompt_kind="batch_one_liner",
        system_prompt="s",
        prompt_template="t",
        provider="OPENROUTER",
        model="test/model",
        temperature=0.3,
        max_tokens=None,
    )
    return DecisionOneLiner.objects.create(
        decision=decision,
        config=config,
        attempt=1,
        status=OneLinerStatus.COMPLETED,
        one_liner="Shared group one-liner.",
        completed_at=timezone.now(),
    )


class TestNotificationGroupList:
    def test_list_is_scoped_to_current_user(
        self, authenticated_client, user, notification_subscription
    ):
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
            UserFactory,
        )

        own = _make_group(user, notification_subscription)
        NotificationBatchFactory(user=user, subscription=notification_subscription, group=own)

        other_user = UserFactory()
        other_sub = NotificationSubscriptionFactory(user=other_user)
        other = _make_group(other_user, other_sub)
        NotificationBatchFactory(user=other_user, subscription=other_sub, group=other)

        response = authenticated_client.get("/api/notifications/groups/")

        assert response.status_code == status.HTTP_200_OK
        results = (
            response.data["results"]
            if isinstance(response.data, dict) and "results" in response.data
            else response.data
        )
        assert [row["id"] for row in results] == [own.id]

    def test_list_filters_by_local_date(
        self, authenticated_client, user, notification_subscription
    ):
        from conftest import NotificationSubscriptionFactory

        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        old = _make_group(
            user,
            notification_subscription,
            start=yesterday,
            end=today,
        )
        current = _make_group(
            user,
            NotificationSubscriptionFactory(user=user),
            start=today,
            end=today + timedelta(days=1),
        )

        response = authenticated_client.get(
            "/api/notifications/groups/",
            {"local_date": str(current.local_date)},
        )

        assert response.status_code == status.HTTP_200_OK
        results = (
            response.data["results"]
            if isinstance(response.data, dict) and "results" in response.data
            else response.data
        )
        assert [row["id"] for row in results] == [current.id]
        assert old.id not in [row["id"] for row in results]

    def test_periods_group_same_window_and_are_newest_first(
        self, authenticated_client, user, notification_subscription
    ):
        from conftest import NotificationSubscriptionFactory

        today = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday = today - timedelta(days=1)

        _make_group(
            user,
            notification_subscription,
            start=yesterday,
            end=today,
        )
        _make_group(
            user,
            NotificationSubscriptionFactory(user=user),
            start=yesterday,
            end=today,
        )
        _make_group(
            user,
            notification_subscription,
            start=today,
            end=today + timedelta(days=1),
        )

        response = authenticated_client.get(
            "/api/notifications/groups/periods/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 2
        assert response.data[0]["local_date"] > response.data[1]["local_date"]
        older = response.data[1]
        assert older["group_count"] == 2

    def test_detail_has_no_group_ai_fields(
        self, authenticated_client, user, notification_subscription
    ):
        group = _make_group(user, notification_subscription)

        response = authenticated_client.get(
            f"/api/notifications/groups/{group.id}/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert "ai_summary" not in response.data
        assert "ai_summary_status" not in response.data


class TestNotificationGroupReads:
    def test_decisions_include_shared_one_liner(
        self, authenticated_client, user, notification_subscription, decision
    ):
        from conftest import (
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        group = _make_group(user, notification_subscription)
        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, group=group
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)
        _make_shared_one_liner(decision)

        response = authenticated_client.get(
            f"/api/notifications/groups/{group.id}/decisions/"
        )

        assert response.status_code == status.HTTP_200_OK
        results = (
            response.data["results"]
            if isinstance(response.data, dict) and "results" in response.data
            else response.data
        )
        assert results[0]["decision"]["one_liner"] == "Shared group one-liner."

    def test_summary_composes_batches_and_shared_cache(
        self, authenticated_client, user, notification_subscription, decision
    ):
        from conftest import (
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )

        group = _make_group(user, notification_subscription)
        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            group=group,
            ai_summary_status="SKIPPED",
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)
        _make_shared_one_liner(decision)

        response = authenticated_client.get(
            f"/api/notifications/groups/{group.id}/summary/"
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.data["status"] == "SKIPPED"
        assert response.data["shared_items_available"] == 1
        assert response.data["items"][0]["one_liner"] == "Shared group one-liner."

    def test_mark_read_and_dismiss(self, authenticated_client, user, notification_subscription):
        group = _make_group(user, notification_subscription)

        response = authenticated_client.post(
            f"/api/notifications/groups/{group.id}/mark-read/"
        )
        assert response.status_code == status.HTTP_200_OK
        group.refresh_from_db()
        assert group.is_read is True

        response = authenticated_client.post(
            f"/api/notifications/groups/{group.id}/dismiss/"
        )
        assert response.status_code == status.HTTP_200_OK
        group.refresh_from_db()
        assert group.is_dismissed is True
