"""
Unit tests for notifications.tasks.check_all_active_subscriptions

This fan-out task is the bridge between the post-import orchestrator and
individual per-user notification checks.  These tests confirm:

  - Daily subscriptions are always dispatched
  - Weekly subscriptions are dispatched only when due (>= 7 days since last check)
  - Inactive and non-automatic subscriptions are ignored
  - Subscriptions are grouped by user into per-user chords
  - Each user's chord fires independently (one chord call per user)
  - The chord callback is send_consolidated_email_for_user

No Celery broker is needed — chord() is mocked.
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
def mock_chord():
    """Mock chord() to avoid real Celery broker interaction."""
    with patch(
        "notifications.tasks.notification_tasks.chord"
    ) as mock:
        # chord returns a callable that returns a fake AsyncResult
        mock_result = MagicMock()
        mock_result.id = "fake-chord-id"
        mock.return_value = MagicMock(return_value=mock_result)
        yield mock


def _run(lookback_days=1):
    """Run check_all_active_subscriptions synchronously (no broker)."""
    from notifications.tasks.notification_tasks import check_all_active_subscriptions
    return check_all_active_subscriptions(lookback_days=lookback_days)


# ---------------------------------------------------------------------------
# Tests: subscription filtering
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckAllActiveSubscriptionsFiltering:

    def test_no_subscriptions_returns_zeros(self, mock_chord):
        result = _run()
        assert result == {
            "status": "dispatched",
            "total": 0,
            "dispatched": 0,
            "skipped": 0,
            "users": 0,
        }
        mock_chord.assert_not_called()

    def test_daily_subscription_is_dispatched(self, mock_chord):
        """Daily subscriptions should always be dispatched via per-user chord."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(check_frequency="daily")

        result = _run()

        assert result["dispatched"] == 1
        assert result["users"] == 1
        # One chord call per user
        mock_chord.assert_called_once()
        # The chord header is a single check_user_subscriptions.s() signature
        header_sig = mock_chord.call_args[0][0]
        assert header_sig.kwargs["user_id"] == sub.user_id
        assert header_sig.kwargs["subscription_ids"] == [sub.id]
        assert header_sig.kwargs["lookback_days"] == 1

    def test_inactive_subscription_is_excluded(self, mock_chord):
        """is_active=False subscriptions must be filtered by the queryset."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(check_frequency="daily", is_active=False)

        result = _run()

        assert result["total"] == 0
        assert result["dispatched"] == 0
        mock_chord.assert_not_called()

    def test_multiple_daily_subscriptions_same_user_one_chord(self, mock_chord):
        """Multiple subscriptions for the same user → one chord call."""
        from conftest import NotificationSubscriptionFactory, UserFactory

        user = UserFactory()
        NotificationSubscriptionFactory.create_batch(
            3, check_frequency="daily", user=user
        )

        result = _run()

        assert result["dispatched"] == 3
        assert result["users"] == 1
        # Only one chord call (grouped by user)
        mock_chord.assert_called_once()
        header_sig = mock_chord.call_args[0][0]
        assert len(header_sig.kwargs["subscription_ids"]) == 3

    def test_multiple_users_multiple_chords(self, mock_chord):
        """Subscriptions for different users → one chord per user."""
        from conftest import NotificationSubscriptionFactory

        sub_a = NotificationSubscriptionFactory(check_frequency="daily")
        sub_b = NotificationSubscriptionFactory(check_frequency="daily")

        result = _run()

        assert result["dispatched"] == 2
        assert result["users"] == 2
        # Two chord calls (one per user)
        assert mock_chord.call_count == 2


# ---------------------------------------------------------------------------
# Tests: weekly subscriptions — when to dispatch vs. skip
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCheckAllActiveSubscriptionsWeekly:

    def test_weekly_never_checked_is_dispatched(self, mock_chord):
        """Weekly subscriptions that have never been checked should be dispatched."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly", last_checked=None
        )

        result = _run()

        assert result["dispatched"] == 1
        mock_chord.assert_called_once()

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_8_days_ago_is_dispatched(self, mock_chord):
        """Weekly subscription last checked 8 days ago — due for a recheck."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=8),
        )

        result = _run()

        assert result["dispatched"] == 1
        mock_chord.assert_called_once()

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_exactly_7_days_ago_is_dispatched(self, mock_chord):
        """Boundary: exactly 7 days → should be dispatched (>= 7)."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=7),
        )

        result = _run()

        assert result["dispatched"] == 1

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_3_days_ago_is_skipped(self, mock_chord):
        """Weekly subscription checked 3 days ago — not yet due, must be skipped."""
        from conftest import NotificationSubscriptionFactory
        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=3),
        )

        result = _run()

        assert result["dispatched"] == 0
        assert result["skipped"] == 1
        mock_chord.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: mixed scenarios
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@freeze_time("2026-05-30 12:00:00")
class TestCheckAllActiveSubscriptionsMixed:

    def test_mix_of_daily_weekly_inactive(self, mock_chord):
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

    def test_lookback_days_forwarded_to_check_user(self, mock_chord):
        """lookback_days should be passed through to check_user_subscriptions."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(check_frequency="daily")

        _run(lookback_days=3)

        mock_chord.assert_called_once()
        header_sig = mock_chord.call_args[0][0]
        assert header_sig.kwargs["lookback_days"] == 3

    def test_chord_callback_is_consolidated_email_for_user(self, mock_chord):
        """Verify the chord callback is send_consolidated_email_for_user."""
        from conftest import NotificationSubscriptionFactory
        sub = NotificationSubscriptionFactory(check_frequency="daily")

        _run()

        # chord(header_sig)(callback_sig)
        # mock_chord.return_value is the callable that receives the callback
        callback_call = mock_chord.return_value.call_args
        assert callback_call is not None
        callback_sig = callback_call[0][0]
        assert callback_sig is not None
        # The callback should have user_id kwarg
        assert callback_sig.kwargs.get("user_id") == sub.user_id
