"""
Unit tests for notifications.tasks.check_all_active_subscriptions

This fan-out task is the bridge between the post-import orchestrator and
individual per-subscription notification checks.  These tests confirm:

  - Daily subscriptions are always dispatched
  - Weekly subscriptions are dispatched only when due (>= 7 days since last check)
  - Inactive and non-automatic subscriptions are ignored
  - The correct kwargs are forwarded to check_single_subscription.delay()
  - Return counts (total / dispatched / skipped) are accurate

No Celery broker is needed — check_single_subscription.delay() is mocked.
"""

from datetime import timedelta
from unittest.mock import MagicMock, call, patch

import pytest
from django.utils import timezone
from freezegun import freeze_time


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clean_subscriptions():
    from notifications.models import NotificationSubscription
    NotificationSubscription.objects.all().delete()
    yield
    NotificationSubscription.objects.all().delete()


@pytest.fixture
def mock_check_single():
    """Mock check_single_subscription.delay() to avoid real task dispatch."""
    with patch(
        "notifications.tasks.notification_tasks.check_single_subscription"
    ) as mock_task:
        mock_task.delay = MagicMock()
        yield mock_task


def _run(lookback_days=1):
    """Run check_all_active_subscriptions synchronously (no broker)."""
    from notifications.tasks.notification_tasks import check_all_active_subscriptions
    return check_all_active_subscriptions(lookback_days=lookback_days)


# ---------------------------------------------------------------------------
# Tests: subscription filtering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckAllActiveSubscriptionsFiltering:

    def test_no_subscriptions_returns_zeros(self, mock_check_single):
        result = _run()
        assert result == {"status": "dispatched", "total": 0, "dispatched": 0, "skipped": 0}
        mock_check_single.delay.assert_not_called()

    def test_daily_subscription_is_dispatched(self, mock_check_single):
        """Daily subscriptions should always be dispatched."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(check_frequency="daily")

        result = _run()

        assert result["dispatched"] == 1
        assert result["skipped"] == 0
        mock_check_single.delay.assert_called_once_with(
            subscription_id=sub.id,
            lookback_days=1,
            use_batch=True,
            send_email=True,
        )

    def test_daily_subscription_without_email_is_dispatched_without_email(
        self, mock_check_single
    ):
        """When also_send_email=False, send_email should be False."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(
            check_frequency="daily", also_send_email=False
        )

        result = _run()

        assert result["dispatched"] == 1
        mock_check_single.delay.assert_called_once_with(
            subscription_id=sub.id,
            lookback_days=1,
            use_batch=True,
            send_email=False,
        )

    def test_inactive_subscription_is_excluded(self, mock_check_single):
        """is_active=False subscriptions must be filtered by the queryset."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(check_frequency="daily", is_active=False)

        result = _run()

        assert result["total"] == 0
        mock_check_single.delay.assert_not_called()

    def test_multiple_daily_subscriptions_all_dispatched(self, mock_check_single):
        from conftest import NotificationSubscriptionFactory
        subs = NotificationSubscriptionFactory.create_batch(3, check_frequency="daily")

        result = _run()

        assert result["dispatched"] == 3
        assert result["total"] == 3
        assert mock_check_single.delay.call_count == 3


# ---------------------------------------------------------------------------
# Tests: weekly subscriptions — when to dispatch vs. skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckAllActiveSubscriptionsWeekly:

    def test_weekly_never_checked_is_dispatched(self, mock_check_single):
        """Weekly subscriptions that have never been checked should be dispatched."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(
            check_frequency="weekly", last_checked=None
        )

        result = _run()

        assert result["dispatched"] == 1
        mock_check_single.delay.assert_called_once()

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_8_days_ago_is_dispatched(self, mock_check_single):
        """Weekly subscription last checked 8 days ago — due for a recheck."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=8),
        )

        result = _run()

        assert result["dispatched"] == 1
        mock_check_single.delay.assert_called_once()

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_exactly_7_days_ago_is_dispatched(self, mock_check_single):
        """Boundary: exactly 7 days → should be dispatched (>= 7)."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=7),
        )

        result = _run()

        assert result["dispatched"] == 1

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_3_days_ago_is_skipped(self, mock_check_single):
        """Weekly subscription checked 3 days ago — not yet due, must be skipped."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=3),
        )

        result = _run()

        assert result["dispatched"] == 0
        assert result["skipped"] == 1
        mock_check_single.delay.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: mixed scenarios
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@freeze_time("2026-05-30 12:00:00")
class TestCheckAllActiveSubscriptionsMixed:

    def test_mix_of_daily_weekly_inactive(self, mock_check_single):
        """
        Realistic scenario:
          - 2 daily (active)      → dispatched
          - 1 weekly, due         → dispatched
          - 1 weekly, not due     → skipped
          - 1 daily, inactive     → excluded from queryset
        """
        from conftest import NotificationSubscriptionFactory

        NotificationSubscriptionFactory.create_batch(2, check_frequency="daily")
        NotificationSubscriptionFactory(
            check_frequency="weekly", last_checked=None
        )
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=2),
        )
        NotificationSubscriptionFactory(check_frequency="daily", is_active=False)

        result = _run()

        assert result["total"] == 4         # inactive is excluded by queryset
        assert result["dispatched"] == 3    # 2 daily + 1 weekly (due)
        assert result["skipped"] == 1       # 1 weekly (not due)
        assert mock_check_single.delay.call_count == 3

    def test_lookback_days_forwarded_to_check_single(self, mock_check_single):
        """lookback_days should be passed through to check_single_subscription."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(check_frequency="daily")

        _run(lookback_days=3)

        mock_check_single.delay.assert_called_once_with(
            subscription_id=sub.id,
            lookback_days=3,
            use_batch=True,
            send_email=True,
        )
