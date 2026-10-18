"""
Integration tests for AI summary dispatch ownership.

``create_batch_for_matches`` no longer dispatches summaries — the scheduled
path chains them via ``dispatch_summaries_then_email`` (summaries must
finish BEFORE the consolidated email so it can include the per-decision
one-liners), and the manual "check now" path
(``check_single_subscription``) dispatches explicitly after batch creation.
"""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestNoSummaryDispatchInCreateBatch:
    """``create_batch_for_matches`` never dispatches summaries itself."""

    def test_does_not_dispatch_even_when_enabled_and_decisions_added(
        self, notification_subscription, decision
    ):
        """
        Even with ai_summary_enabled=True and new decisions, batch creation
        does NOT queue ``summarize_notification_batch`` — the email chord
        (scheduled path) or the manual check task owns that now.
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
            mock_delay.assert_not_called()

    def test_does_not_dispatch_when_disabled(
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

    def test_does_not_dispatch_when_no_new_decisions(
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

    def test_does_not_dispatch_on_empty_decisions(
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

    def test_ai_summary_disabled_by_default(self, notification_subscription):
        """New subscriptions have ai_summary_enabled=False by default."""
        # The fixture already creates a fresh subscription; just check its defaults
        assert notification_subscription.ai_summary_enabled is False
        assert notification_subscription.ai_summary_pipeline is None


class TestManualPathDispatchesSummary:
    """``check_single_subscription`` dispatches summaries explicitly."""

    def _check(self, subscription, decision, **kwargs):
        from notifications.tasks.notification_tasks import check_single_subscription

        with (
            patch(
                "notifications.tasks.notification_tasks.find_matching_decisions",
                return_value=[decision],
            ),
            patch(
                "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
            ) as mock_delay,
        ):
            result = check_single_subscription(
                subscription.id, use_batch=True, send_email=False, **kwargs
            )
        return result, mock_delay

    def test_dispatches_when_enabled_and_new_decisions(
        self, notification_subscription, decision
    ):
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        result, mock_delay = self._check(notification_subscription, decision)

        assert result["decisions_added"] == 1
        mock_delay.assert_called_once_with(batch_id=result["batch_id"])

    def test_does_not_dispatch_when_disabled(
        self, notification_subscription, decision
    ):
        notification_subscription.ai_summary_enabled = False
        notification_subscription.save()

        _, mock_delay = self._check(notification_subscription, decision)

        mock_delay.assert_not_called()

    def test_does_not_dispatch_when_no_new_decisions(
        self, notification_subscription, decision
    ):
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        check_start = timezone.now() - timedelta(hours=1)
        check_end = timezone.now()
        existing_batch = NotificationBatchFactory(
            user=notification_subscription.user,
            subscription=notification_subscription,
            check_window_start=check_start,
            check_window_end=check_end,
        )
        NotificationBatchDecisionFactory(
            batch=existing_batch, decision=decision
        )

        _, mock_delay = self._check(notification_subscription, decision)

        mock_delay.assert_not_called()

    def test_dispatch_failure_does_not_break_the_check(
        self, notification_subscription, decision
    ):
        """A broker hiccup while dispatching must not fail the check."""
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        with (
            patch(
                "notifications.tasks.notification_tasks.find_matching_decisions",
                return_value=[decision],
            ),
            patch(
                "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay",
                side_effect=RuntimeError("Redis connection failed"),
            ),
        ):
            from notifications.tasks.notification_tasks import (
                check_single_subscription,
            )

            result = check_single_subscription(
                notification_subscription.id, use_batch=True, send_email=False
            )

        assert result["decisions_added"] == 1
        assert result["batch_id"] is not None
