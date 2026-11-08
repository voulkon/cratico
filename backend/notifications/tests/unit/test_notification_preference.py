"""
NotificationPreference: defaults, enforcement points, digests, and the
legacy-guard migration (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §5.2).

Email is a digest by default, so a per-run send is deferred and the hourly
digest task sends every un-emailed batch exactly once.
"""

import importlib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
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


def _batch(user, **kwargs):
    from conftest import NotificationBatchFactory, NotificationSubscriptionFactory

    subscription = kwargs.pop(
        "subscription", NotificationSubscriptionFactory(user=user)
    )
    defaults = {
        "user": user,
        "subscription": subscription,
        "match_count": 1,
        "email_sent": False,
    }
    defaults.update(kwargs)
    return NotificationBatchFactory(**defaults)


class TestDefaultsAndConstraints:
    def test_new_user_gets_the_documented_defaults(self, user):
        preference = user.notification_preference
        assert preference.email_enabled is True
        assert preference.email_mode == "daily_digest"
        assert preference.digest_hour_local == 8
        assert preference.ai_summary_enabled is False

    def test_one_preference_per_user(self, user):
        from notifications.models import NotificationPreference

        with pytest.raises(Exception):
            NotificationPreference.objects.create(user=user)

    def test_digest_hour_outside_range_fails_validation(self, user):
        preference = user.notification_preference
        preference.digest_hour_local = 24
        with pytest.raises(ValidationError):
            preference.full_clean()


class TestEmailEnforcement:
    def test_email_disabled_sends_nothing_and_keeps_batches_unread(self, user):
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.email_enabled = False
        preference.email_mode = "every_run"
        preference.save(update_fields=["email_enabled", "email_mode"])
        batch = _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_consolidated_email_for_user(
                {"batch_ids": [batch.id]}, user_id=user.id
            )

        mock_send.assert_not_called()
        batch.refresh_from_db()
        assert batch.email_sent is False
        assert result["email_disabled"] is True

    def test_every_run_sends_one_email_per_run(self, user):
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.email_mode = "every_run"
        preference.save(update_fields=["email_mode"])

        first = _batch(user)
        second = _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            r1 = send_consolidated_email_for_user(
                {"batch_ids": [first.id]}, user_id=user.id
            )
            r2 = send_consolidated_email_for_user(
                {"batch_ids": [second.id]}, user_id=user.id
            )

        assert mock_send.call_count == 2
        assert r1["batches_emailed"] == 1
        assert r2["batches_emailed"] == 1

    def test_daily_digest_defers_per_run_email(self, user):
        from notifications.tasks.notification_tasks import (
            send_consolidated_email_for_user,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        batch = _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_consolidated_email_for_user(
                {"batch_ids": [batch.id]}, user_id=user.id
            )

        mock_send.assert_not_called()
        batch.refresh_from_db()
        assert batch.email_sent is False
        assert result["email_deferred"] is True


class TestDigestTask:
    @freeze_time("2026-05-30 08:00:00")
    def test_daily_digest_sends_at_the_configured_hour_once(self, user):
        from notifications.tasks.notification_tasks import (
            send_notification_digests,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.digest_hour_local = timezone.localtime().hour
        preference.save(update_fields=["digest_hour_local"])

        first = _batch(user)
        second = _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_notification_digests()
            # A second run in the same hour is a no-op (batches are sent).
            second_result = send_notification_digests()

        assert result["emails_sent"] == 1
        assert second_result["emails_sent"] == 0
        assert mock_send.call_count == 1
        sent_batches = mock_send.call_args.kwargs["batches"]
        assert {b["id"] for b in sent_batches} == {first.id, second.id}

        first.refresh_from_db()
        second.refresh_from_db()
        assert first.email_sent is True
        assert second.email_sent is True

    @freeze_time("2026-05-30 08:00:00")
    def test_digest_waits_for_the_configured_hour(self, user):
        from notifications.tasks.notification_tasks import (
            send_notification_digests,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.digest_hour_local = (timezone.localtime().hour + 1) % 24
        preference.save(update_fields=["digest_hour_local"])
        _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_notification_digests()

        assert result["due_users"] == 0
        mock_send.assert_not_called()

    @freeze_time("2026-05-30 08:00:00")
    def test_digest_skips_batches_in_the_next_period(self, user):
        from conftest import NotificationSubscriptionFactory
        from notifications.models import NotificationBatchGroup
        from notifications.tasks.notification_tasks import (
            send_notification_digests,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.digest_hour_local = timezone.localtime().hour
        preference.save(update_fields=["digest_hour_local"])

        subscription = NotificationSubscriptionFactory(user=user)
        now = timezone.now()
        ended = NotificationBatchGroup.objects.create(
            user=user,
            subscription=subscription,
            period_start=now - timedelta(days=1),
            period_end=now,
            local_date=now.date(),
        )
        next_period = NotificationBatchGroup.objects.create(
            user=user,
            subscription=subscription,
            period_start=now,
            period_end=now + timedelta(days=1),
            local_date=(now + timedelta(days=1)).date(),
        )
        ended_batch = _batch(user, subscription=subscription, group=ended)
        future_batch = _batch(user, subscription=subscription, group=next_period)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            send_notification_digests()

        assert mock_send.call_count == 1
        sent_batches = mock_send.call_args.kwargs["batches"]
        assert {b["id"] for b in sent_batches} == {ended_batch.id}

        ended_batch.refresh_from_db()
        future_batch.refresh_from_db()
        assert ended_batch.email_sent is True
        assert future_batch.email_sent is False

    @freeze_time("2026-06-01 08:00:00")  # Monday
    def test_weekly_digest_sends_on_monday(self, user):
        from notifications.tasks.notification_tasks import (
            send_notification_digests,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.email_mode = "weekly_digest"
        preference.digest_hour_local = timezone.localtime().hour
        preference.save(update_fields=["email_mode", "digest_hour_local"])
        _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_notification_digests()

        assert result["emails_sent"] == 1
        mock_send.assert_called_once()

    @freeze_time("2026-06-02 08:00:00")  # Tuesday
    def test_weekly_digest_does_not_send_other_days(self, user):
        from notifications.tasks.notification_tasks import (
            send_notification_digests,
        )

        user.email_verified = True
        user.save(update_fields=["email_verified"])
        preference = user.notification_preference
        preference.email_mode = "weekly_digest"
        preference.digest_hour_local = timezone.localtime().hour
        preference.save(update_fields=["email_mode", "digest_hour_local"])
        _batch(user)

        with patch(EMAIL_SENDER, return_value=True) as mock_send:
            result = send_notification_digests()

        assert result["emails_sent"] == 0
        mock_send.assert_not_called()


class TestUserLevelAiToggle:
    def test_toggle_off_dispatches_no_summaries(self, user):
        from conftest import NotificationSubscriptionFactory
        from notifications.tasks.notification_tasks import (
            dispatch_summaries_then_email,
        )

        preference = user.notification_preference
        preference.ai_summary_enabled = False
        preference.save(update_fields=["ai_summary_enabled"])

        subscription = NotificationSubscriptionFactory(
            user=user, ai_summary_enabled=True
        )
        batch = _batch(user, subscription=subscription)

        with (
            patch(
                "notifications.tasks.notification_tasks.chord"
            ) as mock_chord,
            patch(SUMMARIZE_DELAY) as mock_summarize,
        ):
            dispatch_summaries_then_email(
                {
                    "user_id": user.id,
                    "batch_ids": [batch.id],
                    "new_batch_ids": [batch.id],
                },
                user_id=user.id,
            )

        mock_chord.assert_not_called()
        mock_summarize.assert_not_called()
        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"

    def test_toggle_on_without_pipeline_is_accepted_and_dispatched(self, user):
        """§6.3 / §8 item 11: the toggle is accepted; the task falls back to
        the default pipeline."""
        from conftest import NotificationSubscriptionFactory
        from notifications.tasks.notification_tasks import (
            dispatch_summaries_then_email,
        )

        preference = user.notification_preference
        preference.ai_summary_enabled = True
        preference.save(update_fields=["ai_summary_enabled"])

        subscription = NotificationSubscriptionFactory(
            user=user, ai_summary_enabled=True, ai_summary_pipeline=None
        )
        batch = _batch(user, subscription=subscription)

        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord:
            result = dispatch_summaries_then_email(
                {
                    "user_id": user.id,
                    "batch_ids": [batch.id],
                    "new_batch_ids": [batch.id],
                },
                user_id=user.id,
            )

        assert result["summaries_dispatched"] == 1
        mock_chord.assert_called_once()


class TestPreferenceDataMigration:
    @staticmethod
    def _migration():
        return importlib.import_module(
            "notifications.migrations.0013_notification_preference"
        )

    def test_every_existing_user_gets_a_daily_digest_row(self):
        from conftest import UserFactory
        from notifications.models import NotificationPreference

        users = [UserFactory(), UserFactory()]
        NotificationPreference.objects.all().delete()

        self._migration().create_preferences_for_existing_users(
            django_apps, None
        )

        for user in users:
            preference = NotificationPreference.objects.get(user=user)
            assert preference.email_mode == "daily_digest"
            assert preference.email_enabled is True

    def test_existing_operator_values_are_not_overwritten(self):
        from conftest import UserFactory
        from notifications.models import NotificationPreference

        user = UserFactory()
        preference = NotificationPreference.objects.get(user=user)
        preference.email_mode = "every_run"
        preference.digest_hour_local = 20
        preference.ai_summary_enabled = True
        preference.save(
            update_fields=["email_mode", "digest_hour_local", "ai_summary_enabled"]
        )

        self._migration().create_preferences_for_existing_users(
            django_apps, None
        )

        preference.refresh_from_db()
        assert preference.email_mode == "every_run"
        assert preference.digest_hour_local == 20
        assert preference.ai_summary_enabled is True

    def test_ai_toggle_is_on_when_a_subscription_has_it_on(self):
        from conftest import NotificationSubscriptionFactory, UserFactory
        from notifications.models import NotificationPreference

        user = UserFactory()
        NotificationSubscriptionFactory(user=user, ai_summary_enabled=True)
        NotificationPreference.objects.filter(user=user).delete()

        self._migration().create_preferences_for_existing_users(
            django_apps, None
        )

        preference = NotificationPreference.objects.get(user=user)
        assert preference.ai_summary_enabled is True


class TestAiSummaryCeiling:
    """WI-7: at most NOTIFICATION_AI_SUMMARIES_PER_SUBSCRIPTION_PER_DAY."""

    def _setup(self, user, ai_summarised_today):
        from conftest import NotificationSubscriptionFactory

        preference = user.notification_preference
        preference.email_mode = "every_run"
        preference.ai_summary_enabled = True
        preference.save(update_fields=["email_mode", "ai_summary_enabled"])

        user.email_verified = True
        user.save(update_fields=["email_verified"])

        subscription = NotificationSubscriptionFactory(
            user=user, ai_summary_enabled=True
        )
        for _ in range(ai_summarised_today):
            _batch(user, subscription=subscription, ai_summary_status="COMPLETED")
        new_batch = _batch(
            user, subscription=subscription, ai_summary_status="PENDING"
        )
        return subscription, new_batch

    def test_under_the_ceiling_a_summary_is_dispatched(self, user):
        from notifications.tasks.notification_tasks import (
            dispatch_summaries_then_email,
        )

        _, new_batch = self._setup(user, ai_summarised_today=1)

        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord:
            result = dispatch_summaries_then_email(
                {
                    "user_id": user.id,
                    "batch_ids": [new_batch.id],
                    "new_batch_ids": [new_batch.id],
                },
                user_id=user.id,
            )

        assert result["summaries_dispatched"] == 1
        mock_chord.assert_called_once()
        new_batch.refresh_from_db()
        assert new_batch.ai_summary_status == "PENDING"

    def test_legacy_batch_count_ceiling_no_longer_blocks_dispatch(self, user):
        """The old batch-count ceiling was replaced by a new-decision budget.

        Dispatch now always hands summarisable batches to the task; the task
        decides how much *new provider work* is affordable from the shared
        cache inventory.
        """
        from notifications.tasks.notification_tasks import (
            dispatch_summaries_then_email,
        )

        _, new_batch = self._setup(user, ai_summarised_today=2)

        with patch(
            "notifications.tasks.notification_tasks.chord"
        ) as mock_chord:
            result = dispatch_summaries_then_email(
                {
                    "user_id": user.id,
                    "batch_ids": [new_batch.id],
                    "new_batch_ids": [new_batch.id],
                },
                user_id=user.id,
            )

        assert result["summaries_dispatched"] == 1
        mock_chord.assert_called_once()
        new_batch.refresh_from_db()
        assert new_batch.ai_summary_status == "PENDING"
