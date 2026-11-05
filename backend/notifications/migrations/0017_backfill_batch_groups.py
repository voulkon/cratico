"""Backfill presentation/email groups for existing batches.

The digest-period calculation is inlined (frozen) because migrations must not
import application code that can change later.  summaries are not regenerated.
"""

from datetime import timedelta

from django.db import migrations
from django.db.models import Sum
from django.utils import timezone


def _resolve_period(preference, at):
    local = timezone.localtime(at)
    if preference is None:
        return None

    end = local.replace(
        hour=preference.digest_hour_local, minute=0, second=0, microsecond=0
    )
    if end <= local:
        end += timedelta(days=1)

    if preference.email_mode == "weekly_digest":
        days_until_monday = (7 - end.weekday()) % 7
        end += timedelta(days=days_until_monday)
        start = end - timedelta(days=7)
    else:
        start = end - timedelta(days=1)

    return start, end


def backfill_groups(apps, schema_editor):
    NotificationBatch = apps.get_model("notifications", "NotificationBatch")
    NotificationBatchGroup = apps.get_model(
        "notifications", "NotificationBatchGroup"
    )
    NotificationPreference = apps.get_model(
        "notifications", "NotificationPreference"
    )

    preferences = {
        preference.user_id: preference
        for preference in NotificationPreference.objects.all().iterator()
    }

    for batch in (
        NotificationBatch.objects.filter(group__isnull=True)
        .select_related("subscription")
        .iterator()
    ):
        preference = preferences.get(batch.user_id)
        if preference is not None and preference.email_mode == "every_run":
            # every_run keeps batches as the unit; no group is created.
            continue
        period = _resolve_period(preference, batch.created_at)
        if period is None:
            local = timezone.localtime(batch.created_at)
            start = local.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        else:
            start, end = period

        group, _ = NotificationBatchGroup.objects.get_or_create(
            subscription_id=batch.subscription_id,
            period_start=start,
            period_end=end,
            defaults={
                "user_id": batch.user_id,
                "local_date": timezone.localtime(end).date(),
            },
        )
        batch.group = group
        batch.save(update_fields=["group"])

    for group in NotificationBatchGroup.objects.all().iterator():
        group.total_match_count = (
            NotificationBatch.objects.filter(group_id=group.id).aggregate(
                total=Sum("match_count")
            )["total"]
            or 0
        )
        group.save(update_fields=["total_match_count"])


def reverse_noop(apps, schema_editor):
    NotificationBatch = apps.get_model("notifications", "NotificationBatch")
    NotificationBatch.objects.update(group=None)


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0016_notificationbatchgroup"),
    ]

    operations = [
        migrations.RunPython(backfill_groups, reverse_noop),
    ]
