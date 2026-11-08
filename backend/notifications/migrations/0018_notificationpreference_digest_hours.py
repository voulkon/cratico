"""Add the multi-hour digest schedule.

Existing rows keep their single ``digest_hour_local`` by copying it into the
new JSON list.  The model and period resolver fall back to the legacy field,
so the data migration is for consistency and easier querying, not correctness.
"""

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import migrations, models


def backfill_digest_hours(apps, schema_editor):
    NotificationPreference = apps.get_model(
        "notifications", "NotificationPreference"
    )
    for preference in NotificationPreference.objects.all().iterator():
        preference.digest_hours_local = [preference.digest_hour_local]
        preference.save(update_fields=["digest_hours_local"])


def reverse_noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("notifications", "0017_backfill_batch_groups"),
    ]

    operations = [
        migrations.AlterField(
            model_name="notificationpreference",
            name="digest_hour_local",
            field=models.PositiveSmallIntegerField(
                default=8,
                help_text=(
                    "Legacy single digest hour. Used when digest_hours_local "
                    "is empty."
                ),
                validators=[MinValueValidator(0), MaxValueValidator(23)],
                verbose_name="Digest hour (local)",
            ),
        ),
        migrations.AddField(
            model_name="notificationpreference",
            name="digest_hours_local",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Local hours at which digests are sent. Multiple hours "
                    "split the day into consecutive periods; empty falls back "
                    "to digest_hour_local."
                ),
                verbose_name="Digest hours (local)",
            ),
        ),
        migrations.RunPython(backfill_digest_hours, reverse_noop),
    ]
