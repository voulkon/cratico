"""
No re-notification across overlapping runs (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §5.6).

Under hourly imports the lookback window is re-examined every run, so the same
decisions are matched many times a day.  Dedupe happens BEFORE a batch exists,
which gives four guarantees this file pins:

  * a decision is never added to a second batch for the same subscription;
  * a decision matched again is not re-summarised and not re-emailed;
  * an all-duplicates run adds nothing and creates no summary work;
  * an older un-emailed batch for an unverified user never sends.

The race between "email sent" and "email_sent=True" is a known residual risk
(§4.4 risk 3); its test is marked ``xfail(strict=True)`` until a guard exists.
"""

from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone
from freezegun import freeze_time

pytestmark = pytest.mark.django_db

EMAIL_SENDER = (
    "core.email_service.NotificationEmailService."
    "send_consolidated_batch_summary"
)
SUMMARIZE_DELAY = (
    "notifications.tasks.ai_summary_tasks.summarize_notification_batch.delay"
)


@pytest.fixture
def verified_user(user):
    user.email_verified = True
    user.save(update_fields=["email_verified"])
    return user


@pytest.fixture
def org(organization):
    return organization


@pytest.fixture
def subscription(verified_user, org):
    from conftest import NotificationSubscriptionFactory

    preference = verified_user.notification_preference
    preference.email_mode = "every_run"
    preference.ai_summary_enabled = True
    preference.save(update_fields=["email_mode", "ai_summary_enabled"])

    return NotificationSubscriptionFactory(
        user=verified_user, organization=org, check_frequency="daily"
    )


def _decision(org, ada):
    from conftest import DecisionFactory

    return DecisionFactory(
        ada=ada,
        organization=org,
        subject=f"Decision {ada}",
        publish_timestamp=timezone.now(),
    )


def _check_run(subscription, lookback_days=1):
    """One post-import subscription check (the hourly-run stand-in)."""
    from notifications.tasks.notification_tasks import check_user_subscriptions

    return check_user_subscriptions(
        user_id=subscription.user_id,
        subscription_ids=[subscription.id],
        lookback_days=lookback_days,
    )


def _email_run(header_result, user_id):
    """The chord body that would follow the check in a real run."""
    from notifications.tasks.notification_tasks import (
        send_consolidated_email_for_user,
    )

    return send_consolidated_email_for_user(header_result, user_id=user_id)


class TestConsecutiveRuns:
    def test_two_new_runs_send_two_emails_not_three(self, subscription, org):
        """Runs 1 and 3 add decisions; run 2 re-matches them. → 2 emails."""
        from notifications.models import NotificationBatch

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            _decision(org, "CADENCE-1")
            first = _check_run(subscription)
            assert first["total_decisions"] > 0
            _email_run(first, subscription.user_id)

            second = _check_run(subscription)
            _email_run(second, subscription.user_id)

            _decision(org, "CADENCE-2")
            third = _check_run(subscription)
            assert third["total_decisions"] > 0
            _email_run(third, subscription.user_id)

        assert mock_send.call_count == 2
        # Three runs, but only two batches with decisions.
        assert (
            NotificationBatch.objects.filter(subscription=subscription)
            .exclude(match_count=0)
            .count()
            == 2
        )

    def test_rematched_run_is_a_no_op(self, subscription, org):
        """Run 2: no new batch rows, no summaries, no email."""
        from notifications.models import NotificationBatchDecision

        _decision(org, "CADENCE-REMATCH")

        with patch(EMAIL_SENDER, return_value=True):
            first = _check_run(subscription)
            _email_run(first, subscription.user_id)

        junctions_after_first = NotificationBatchDecision.objects.filter(
            subscription=subscription
        ).count()

        with (
            patch(EMAIL_SENDER, return_value=True) as mock_send,
            patch(
                "notifications.tasks.notification_tasks.chord"
            ) as mock_chord,
            patch(SUMMARIZE_DELAY) as mock_summarize,
        ):
            from notifications.tasks.notification_tasks import (
                dispatch_summaries_then_email,
            )

            second = _check_run(subscription)
            dispatch_summaries_then_email(second, user_id=subscription.user_id)

        assert second["total_decisions"] == 0
        assert second["new_batch_ids"] == []
        assert (
            NotificationBatchDecision.objects.filter(
                subscription=subscription
            ).count()
            == junctions_after_first
        )
        mock_chord.assert_not_called()
        mock_summarize.assert_not_called()
        mock_send.assert_not_called()


class TestBatchContents:
    def test_all_duplicates_returns_zero_added(self, subscription, org):
        from notifications.tasks.notification_tasks import create_batch_for_matches

        decision = _decision(org, "CADENCE-DUP")
        start = timezone.now()
        end = start + timedelta(days=1)

        first = create_batch_for_matches(subscription, [decision], start, end)
        second = create_batch_for_matches(
            subscription,
            [decision],
            end,
            end + timedelta(days=1),
        )

        assert first["decisions_added"] == 1
        assert second["decisions_added"] == 0
        assert second["all_duplicates"] is True
        assert second["batch_id"] == first["batch_id"]

    def test_batch_contains_only_the_new_decision(self, subscription, org):
        """One old + one new decision → the new batch holds only the new one."""
        from notifications.models import NotificationBatch
        from notifications.tasks.notification_tasks import create_batch_for_matches

        old = _decision(org, "CADENCE-OLD")
        new = _decision(org, "CADENCE-NEW")
        start = timezone.now()
        end = start + timedelta(days=1)

        create_batch_for_matches(subscription, [old], start, end)
        result = create_batch_for_matches(
            subscription, [old, new], end, end + timedelta(days=1)
        )

        batch = NotificationBatch.objects.get(id=result["batch_id"])
        batched_adas = set(
            batch.batch_decisions.values_list("decision__ada", flat=True)
        )
        assert batched_adas == {"CADENCE-NEW"}
        assert result["decisions_added"] == 1


class TestUnverifiedUser:
    def test_repeated_runs_never_send_and_never_duplicate(
        self, subscription, org
    ):
        from notifications.models import NotificationBatch
        from notifications.tasks.notification_tasks import create_batch_for_matches

        subscription.user.email_verified = False
        subscription.user.save(update_fields=["email_verified"])

        decision = _decision(org, "CAD-UNVERIFIED")
        start = timezone.now()
        end = start + timedelta(days=1)
        result = create_batch_for_matches(subscription, [decision], start, end)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            for _ in range(3):
                _email_run(result, subscription.user_id)

        mock_send.assert_not_called()
        assert (
            NotificationBatch.objects.filter(subscription=subscription).count() == 1
        )
        batch = NotificationBatch.objects.get(id=result["batch_id"])
        assert batch.email_sent is False


class TestEmailRace:
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "§4.4 risk 3: nothing serialises two concurrent senders between "
            "send_consolidated_batch_summary and email_sent=True; a guard is "
            "not implemented yet"
        ),
    )
    def test_concurrent_senders_produce_one_email(self, verified_user):
        """Two overlapping calls for the same un-emailed batch must send once."""
        from conftest import NotificationBatchFactory
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        batch = NotificationBatchFactory(user=verified_user, email_sent=False)
        preference = verified_user.notification_preference
        preference.email_mode = "every_run"
        preference.save(update_fields=["email_mode"])

        sends = []
        nested = {"done": False}

        def fake_send(**kwargs):
            sends.append(kwargs)
            if not nested["done"]:
                # The second run starts before the first marks email_sent.
                nested["done"] = True
                send_consolidated_email_for_user(
                    {"batch_ids": [batch.id]}, user_id=verified_user.id
                )
            return True

        with patch(EMAIL_SENDER, side_effect=fake_send):
            send_consolidated_email_for_user(
                {"batch_ids": [batch.id]}, user_id=verified_user.id
            )

        assert len(sends) == 1


class TestWeeklyCadence:
    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_six_days_ago_is_skipped(self):
        from conftest import NotificationSubscriptionFactory

        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=6),
        )

        from notifications.tasks.notification_tasks import (
            check_all_active_subscriptions,
        )

        with patch("notifications.tasks.notification_tasks.chord") as mock_chord:
            result = check_all_active_subscriptions()

        assert result["dispatched"] == 0
        assert result["skipped"] == 1
        mock_chord.assert_not_called()

    @freeze_time("2026-05-30 12:00:00")
    def test_weekly_checked_seven_days_ago_is_dispatched(self):
        from conftest import NotificationSubscriptionFactory

        NotificationSubscriptionFactory(
            check_frequency="weekly",
            last_checked=timezone.now() - timedelta(days=7),
        )

        from notifications.tasks.notification_tasks import (
            check_all_active_subscriptions,
        )

        with patch("notifications.tasks.notification_tasks.chord") as mock_chord:
            mock_chord.return_value = MagicMock(
                return_value=MagicMock(id="fake-chord-id")
            )
            result = check_all_active_subscriptions()

        assert result["dispatched"] == 1
        mock_chord.assert_called_once()


class TestNotificationGate:
    @pytest.mark.parametrize("enabled", [False, True])
    def test_trigger_is_a_noop_when_notifications_flag_off(self, enabled):
        from core.services.feature_flag_service import feature_flags
        from core.tasks.tasks_post_import import trigger_check_all_subscriptions

        with (
            patch.object(feature_flags, "is_enabled", return_value=enabled),
            patch(
                "notifications.tasks.notification_tasks."
                "check_all_active_subscriptions.delay"
            ) as mock_delay,
        ):
            result = trigger_check_all_subscriptions(
                reference_date_str="2026-05-29"
            )

        if enabled:
            mock_delay.assert_called_once_with()
            assert result["status"] == "dispatched"
        else:
            mock_delay.assert_not_called()
            assert result == {
                "status": "skipped",
                "reason": "feature_flag_disabled",
            }
