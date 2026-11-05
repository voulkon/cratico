"""Consolidated email groups batches by subscription and composes shared items."""

from unittest.mock import patch

import pytest
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
