"""Digest period resolution for single and multiple daily hours."""

from datetime import datetime

import pytest
from django.utils import timezone

from notifications.services.batch_grouping import resolve_digest_period

pytestmark = pytest.mark.django_db


def _at(year, month, day, hour):
    return timezone.make_aware(
        datetime(year, month, day, hour, 0),
        timezone.get_current_timezone(),
    )


class TestMultipleDigestHours:
    def _configure(self, user, hours, mode="daily_digest"):
        preference = user.notification_preference
        preference.email_mode = mode
        preference.digest_hours_local = hours
        preference.digest_hour_local = hours[0]
        preference.save(
            update_fields=[
                "email_mode",
                "digest_hours_local",
                "digest_hour_local",
            ]
        )

    def test_empty_list_falls_back_to_legacy_hour(self, user):
        preference = user.notification_preference
        preference.digest_hours_local = []
        preference.digest_hour_local = 7
        preference.save(update_fields=["digest_hours_local", "digest_hour_local"])

        assert preference.get_digest_hours() == [7]

    def test_period_before_the_first_hour(self, user):
        self._configure(user, [10, 13])

        start, end = resolve_digest_period(user, _at(2026, 11, 10, 9))

        assert start == _at(2026, 11, 9, 13)
        assert end == _at(2026, 11, 10, 10)

    def test_period_between_hours(self, user):
        self._configure(user, [10, 13])

        start, end = resolve_digest_period(user, _at(2026, 11, 10, 11))

        assert start == _at(2026, 11, 10, 10)
        assert end == _at(2026, 11, 10, 13)

    def test_period_after_the_last_hour(self, user):
        self._configure(user, [10, 13])

        start, end = resolve_digest_period(user, _at(2026, 11, 10, 14))

        assert start == _at(2026, 11, 10, 13)
        assert end == _at(2026, 11, 11, 10)

    def test_weekly_multiple_hours(self, user):
        self._configure(user, [10, 13], mode="weekly_digest")

        # Monday 2026-11-09, between the two configured hours.
        start, end = resolve_digest_period(user, _at(2026, 11, 9, 11))

        assert start == _at(2026, 11, 9, 10)
        assert end == _at(2026, 11, 9, 13)

        # Monday after the last hour -> next Monday's first hour.
        start, end = resolve_digest_period(user, _at(2026, 11, 9, 14))

        assert start == _at(2026, 11, 9, 13)
        assert end == _at(2026, 11, 16, 10)
