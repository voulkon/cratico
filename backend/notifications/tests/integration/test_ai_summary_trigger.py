"""
Integration tests for the AI summarization trigger in ``create_batch_for_matches``.

Verifies that ``summarize_notification_batch.delay`` is called only when
the subscription has ``ai_summary_enabled=True`` and new decisions were added.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestAISummaryTriggerInCreateBatch:
    """Tests for AI summary trigger in ``create_batch_for_matches``."""

    def test_triggers_when_enabled_and_decisions_added(
        self, notification_subscription, decision
    ):
        """
        When ai_summary_enabled=True and new decisions are added,
        ``summarize_notification_batch.delay()`` is called.
        """
        from notifications.tasks.notification_tasks import create_batch_for_matches

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()

        with patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
        ) as mock_delay:
            result = create_batch_for_matches(
                notification_subscription,
                [decision],
                check_start,
                check_end,
            )

            assert result["decisions_added"] == 1
            assert result["batch_id"] is not None
            mock_delay.assert_called_once_with(batch_id=result["batch_id"])

    def test_does_not_trigger_when_disabled(
        self, notification_subscription, decision
    ):
        """
        When ai_summary_enabled=False, no summarization task is triggered.
        """
        from notifications.tasks.notification_tasks import create_batch_for_matches

        notification_subscription.ai_summary_enabled = False
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()

        with patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
        ) as mock_delay:
            result = create_batch_for_matches(
                notification_subscription,
                [decision],
                check_start,
                check_end,
            )

            assert result["decisions_added"] == 1
            mock_delay.assert_not_called()

    def test_does_not_trigger_when_no_new_decisions(
        self, notification_subscription, decision
    ):
        """
        When ai_summary_enabled=True but all decisions are already in a batch,
        no summarization task is triggered (decisions_added == 0).
        """
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from notifications.tasks.notification_tasks import create_batch_for_matches

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()

        # Create an existing batch + decision so it's a duplicate
        existing_batch = NotificationBatchFactory(
            user=notification_subscription.user,
            subscription=notification_subscription,
            check_window_start=check_start,
            check_window_end=check_end,
        )
        NotificationBatchDecisionFactory(
            batch=existing_batch, decision=decision
        )

        with patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
        ) as mock_delay:
            result = create_batch_for_matches(
                notification_subscription,
                [decision],
                check_start,
                check_end,
            )

            assert result["decisions_added"] == 0
            mock_delay.assert_not_called()

    def test_does_not_trigger_on_empty_decisions(
        self, notification_subscription
    ):
        """
        When no matching decisions are passed, no batch is created and no
        summarization task is triggered.
        """
        from notifications.tasks.notification_tasks import create_batch_for_matches

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()

        with patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
        ) as mock_delay:
            result = create_batch_for_matches(
                notification_subscription,
                [],
                check_start,
                check_end,
            )

            assert result["decisions_added"] == 0
            assert result["batch_id"] is None
            mock_delay.assert_not_called()

    def test_trigger_exception_does_not_crash_batch_creation(
        self, notification_subscription, decision
    ):
        """
        If triggering the summarization task raises an exception,
        batch creation still succeeds (the exception is caught and logged).
        """
        from notifications.tasks.notification_tasks import create_batch_for_matches

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()

        with patch(
            "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay",
            side_effect=RuntimeError("Redis connection failed"),
        ):
            # Should not raise — exception is caught inside
            result = create_batch_for_matches(
                notification_subscription,
                [decision],
                check_start,
                check_end,
            )

            assert result["decisions_added"] == 1
            assert result["batch_id"] is not None

    def test_ai_summary_disabled_by_default(self, notification_subscription):
        """New subscriptions have ai_summary_enabled=False by default."""
        # The fixture already creates a fresh subscription; just check its defaults
        assert notification_subscription.ai_summary_enabled is False
        assert notification_subscription.ai_summary_pipeline is None
