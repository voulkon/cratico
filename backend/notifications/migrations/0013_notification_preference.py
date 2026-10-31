from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def create_preferences_for_existing_users(apps, schema_editor):
    """Give every existing user the documented digest defaults.

    Legacy guard: a row that already exists (operator-set values included) is
    never overwritten.  The user-level AI toggle is on when any of the user's
    subscriptions has AI summaries on, otherwise the new user-level toggle
    would silently switch those summaries off.
    """
    User = apps.get_model(settings.AUTH_USER_MODEL)
    NotificationPreference = apps.get_model("notifications", "NotificationPreference")
    NotificationSubscription = apps.get_model("notifications", "NotificationSubscription")

    for user_id in User.objects.values_list("id", flat=True).iterator():
        pref, created = NotificationPreference.objects.get_or_create(
            user_id=user_id,
            defaults={
                "email_enabled": True,
                "email_mode": "daily_digest",
                "digest_hour_local": 8,
                "ai_summary_enabled": NotificationSubscription.objects.filter(
                    user_id=user_id, ai_summary_enabled=True
                ).exists(),
            },
        )
        if created:
            continue
        # Never overwrite operator-set values on a re-run.


def delete_preferences(apps, schema_editor):
    """Reverse: drop the rows this migration created (all of them)."""
    NotificationPreference = apps.get_model("notifications", "NotificationPreference")
    NotificationPreference.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("notifications", "0012_notificationbatch_ai_summary_items"),
    ]

    operations = [
        migrations.CreateModel(
            name="NotificationPreference",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "email_enabled",
                    models.BooleanField(
                        default=True,
                        help_text="Turning this off keeps in-app notifications on.",
                        verbose_name="Email enabled",
                    ),
                ),
                (
                    "email_mode",
                    models.CharField(
                        choices=[
                            ("every_run", "Every run (power users)"),
                            ("daily_digest", "Daily digest"),
                            ("weekly_digest", "Weekly digest"),
                        ],
                        default="daily_digest",
                        max_length=20,
                        verbose_name="Email mode",
                    ),
                ),
                (
                    "digest_hour_local",
                    models.PositiveSmallIntegerField(
                        default=8,
                        help_text=(
                            "Hour of day at which a daily digest is sent. "
                            "Weekly digests send on Mondays."
                        ),
                        validators=[
                            django.core.validators.MinValueValidator(0),
                            django.core.validators.MaxValueValidator(23),
                        ],
                        verbose_name="Digest hour (local)",
                    ),
                ),
                (
                    "ai_summary_enabled",
                    models.BooleanField(
                        default=False,
                        help_text=(
                            "User-level toggle. When off, no batch summaries are "
                            "generated even if a subscription has them on."
                        ),
                        verbose_name="Enable AI summaries",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_preference",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="User",
                    ),
                ),
            ],
            options={
                "verbose_name": "Notification preference",
                "verbose_name_plural": "Notification preferences",
            },
        ),
        migrations.RunPython(
            create_preferences_for_existing_users, delete_preferences
        ),
    ]
