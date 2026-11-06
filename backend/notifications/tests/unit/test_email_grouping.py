"""Consolidated email groups batches by subscription and composes shared items."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestConsolidatedEmailGrouping:
    def test_two_batches_one_subscription_and_one_other_make_two_sections(
        self, user
    ):
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks.notification_tasks import _send_unemailed_batches

        sub1 = NotificationSubscriptionFactory(user=user)
        sub2 = NotificationSubscriptionFactory(user=user)
        b1 = NotificationBatchFactory(user=user, subscription=sub1, match_count=2)
        b2 = NotificationBatchFactory(user=user, subscription=sub1, match_count=1)
        b3 = NotificationBatchFactory(user=user, subscription=sub2, match_count=4)

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            result = _send_unemailed_batches(user, [b1, b2, b3])

        assert result["batches_emailed"] == 3
        kwargs = mock_send.call_args.kwargs
        assert kwargs["subscription_count"] == 2
        assert kwargs["total_decisions"] == 7
        assert len(kwargs["batches"]) == 2
        assert {section["decision_count"] for section in kwargs["batches"]} == {3, 4}

        for batch in (b1, b2, b3):
            batch.refresh_from_db()
            assert batch.email_sent is True
            assert batch.email_sent_at is not None

    def test_sections_split_by_group_and_expose_group_id(self, user):
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.models import NotificationBatchGroup
        from notifications.tasks.notification_tasks import _send_unemailed_batches

        subscription = NotificationSubscriptionFactory(user=user)
        now = timezone.now()
        period1 = NotificationBatchGroup.objects.create(
            user=user,
            subscription=subscription,
            period_start=now - timedelta(days=2),
            period_end=now - timedelta(days=1),
            local_date=(now - timedelta(days=1)).date(),
        )
        period2 = NotificationBatchGroup.objects.create(
            user=user,
            subscription=subscription,
            period_start=now - timedelta(days=1),
            period_end=now,
            local_date=now.date(),
        )
        b1 = NotificationBatchFactory(
            user=user, subscription=subscription, group=period1, match_count=2
        )
        b2 = NotificationBatchFactory(
            user=user, subscription=subscription, group=period2, match_count=3
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            _send_unemailed_batches(user, [b1, b2])

        kwargs = mock_send.call_args.kwargs
        sections = kwargs["batches"]
        assert len(sections) == 2
        assert {section["group_id"] for section in sections} == {
            period1.id,
            period2.id,
        }
        # Two periods, one subscription: the subject still counts the
        # subscription once.
        assert kwargs["subscription_count"] == 1

        period1.refresh_from_db()
        period2.refresh_from_db()
        assert period1.email_sent is True
        assert period2.email_sent is True

    @override_settings(NOTIFICATION_EMAIL_MAX_ITEMS_PER_SECTION=2)
    def test_section_items_are_capped(self, user):
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks.notification_tasks import _send_unemailed_batches

        subscription = NotificationSubscriptionFactory(user=user)
        items = [
            {
                "decision_id": i,
                "ada": f"ADA-{i}",
                "subject": f"Subject {i}",
                "one_liner": f"One liner {i}",
            }
            for i in range(4)
        ]
        batch = NotificationBatchFactory(
            user=user,
            subscription=subscription,
            match_count=4,
            ai_summary_status="COMPLETED",
            ai_summary_items=items,
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            _send_unemailed_batches(user, [batch])

        section = mock_send.call_args.kwargs["batches"][0]
        assert len(section["ai_summary_items"]) == 2
        assert section["more_items_count"] == 2
        assert mock_send.call_args.kwargs["total_decisions"] == 4

    @override_settings(NOTIFICATION_EMAIL_MAX_SECTIONS=1)
    def test_sections_are_capped(self, user):
        from conftest import (
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
        )
        from notifications.tasks.notification_tasks import _send_unemailed_batches

        b1 = NotificationBatchFactory(
            user=user,
            subscription=NotificationSubscriptionFactory(user=user),
            match_count=1,
        )
        b2 = NotificationBatchFactory(
            user=user,
            subscription=NotificationSubscriptionFactory(user=user),
            match_count=1,
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            _send_unemailed_batches(user, [b1, b2])

        kwargs = mock_send.call_args.kwargs
        assert len(kwargs["batches"]) == 1
        assert kwargs["more_sections_count"] == 1
        # Hidden sections still mark their batches as emailed.
        for batch in (b1, b2):
            batch.refresh_from_db()
            assert batch.email_sent is True

    def test_skipped_batch_renders_later_shared_one_liner(
        self, user, decision
    ):
        from conftest import (
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
            NotificationSubscriptionFactory,
        )
        from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
        from core.models.one_liner_config import OneLinerConfig
        from notifications.tasks.notification_tasks import _send_unemailed_batches

        subscription = NotificationSubscriptionFactory(user=user)
        batch = NotificationBatchFactory(
            user=user,
            subscription=subscription,
            match_count=1,
            ai_summary_status="SKIPPED",
            ai_summary_items=None,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        config = OneLinerConfig.get_or_create_for(
            prompt_kind="batch_one_liner",
            system_prompt="s",
            prompt_template="t",
            provider="OPENROUTER",
            model="test/model",
            temperature=0.3,
            max_tokens=None,
        )
        DecisionOneLiner.objects.create(
            decision=decision,
            config=config,
            attempt=1,
            status=OneLinerStatus.COMPLETED,
            one_liner="Shared later one-liner.",
            completed_at=timezone.now(),
        )

        with patch(
            "core.email_service.NotificationEmailService.send_consolidated_batch_summary",
            return_value=True,
        ) as mock_send:
            _send_unemailed_batches(user, [batch])

        section = mock_send.call_args.kwargs["batches"][0]
        assert section["ai_summary_items"] == [
            {
                "decision_id": decision.id,
                "ada": decision.ada,
                "subject": decision.subject,
                "one_liner": "Shared later one-liner.",
            }
        ]
