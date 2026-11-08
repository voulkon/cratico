"""Resolve the digest period a batch belongs to."""

from datetime import timedelta

from django.utils import timezone

from notifications.models import EmailMode, NotificationPreference


def _candidate(local, day, hour):
    return local.replace(
        year=day.year,
        month=day.month,
        day=day.day,
        hour=hour,
        minute=0,
        second=0,
        microsecond=0,
    )


def _next_boundary(hours, local, weekly):
    """First scheduled digest boundary strictly after ``local``."""
    for offset in range(0, 8):
        day = local.date() + timedelta(days=offset)
        if weekly and day.weekday() != 0:
            continue
        for hour in hours:
            candidate = _candidate(local, day, hour)
            if candidate > local:
                return candidate
    raise ValueError("No digest boundary found for the configured hours")


def _previous_boundary(hours, boundary, weekly):
    """Last scheduled digest boundary before ``boundary``."""
    probe = boundary - timedelta(seconds=1)
    for offset in range(0, 8):
        day = probe.date() - timedelta(days=offset)
        if weekly and day.weekday() != 0:
            continue
        for hour in sorted(hours, reverse=True):
            candidate = _candidate(probe, day, hour)
            if candidate < boundary:
                return candidate
    raise ValueError("No previous digest boundary found")


def resolve_digest_period(user, at):
    """Return ``(period_start, period_end)`` for ``at`` or ``None``.

    ``every_run`` users keep batches as the unit (no group).  Daily and weekly
    digests use the user's configured local hours.  With multiple hours, the
    periods are consecutive slots (for example 10:00–13:00 and 13:00–10:00
    the next day), so splitting the day into several digests is supported.
    """
    preference = NotificationPreference.get_for_user(user)
    local = timezone.localtime(at)

    if preference.email_mode == EmailMode.EVERY_RUN:
        return None

    hours = preference.get_digest_hours()
    weekly = preference.email_mode == EmailMode.WEEKLY_DIGEST

    end = _next_boundary(hours, local, weekly)
    start = _previous_boundary(hours, end, weekly)
    return start, end
