"""Resolve the digest period a batch belongs to."""

from datetime import timedelta

from django.utils import timezone

from notifications.models import EmailMode, NotificationPreference


def resolve_digest_period(user, at):
    """Return ``(period_start, period_end)`` for ``at`` or ``None``.

    ``every_run`` users keep batches as the unit (no group).  Daily and weekly
    digests group by the user's local digest hour, not calendar midnight, so
    the email and the group describe the same window.
    """
    preference = NotificationPreference.get_for_user(user)
    local = timezone.localtime(at)

    if preference.email_mode == EmailMode.EVERY_RUN:
        return None

    end = local.replace(
        hour=preference.digest_hour_local,
        minute=0,
        second=0,
        microsecond=0,
    )
    if end <= local:
        end += timedelta(days=1)

    if preference.email_mode == EmailMode.WEEKLY_DIGEST:
        days_until_monday = (7 - end.weekday()) % 7
        end += timedelta(days=days_until_monday)
        start = end - timedelta(days=7)
    else:
        start = end - timedelta(days=1)

    return start, end
