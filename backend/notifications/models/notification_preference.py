"""
User-level notification preferences.

Email is a digest by default: hourly imports can create a batch every hour, and
a per-run email would mean up to 24 emails a day.  In-app notifications stay
real-time; only the email cadence (and the AI summary toggle) is user-level.
"""

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _


class EmailMode(models.TextChoices):
    EVERY_RUN = "every_run", _("Every run (power users)")
    DAILY_DIGEST = "daily_digest", _("Daily digest")
    WEEKLY_DIGEST = "weekly_digest", _("Weekly digest")


class NotificationPreference(models.Model):
    """One row per user (created by signal for new users, migration for old)."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_preference",
        verbose_name=_("User"),
    )

    email_enabled = models.BooleanField(
        default=True,
        verbose_name=_("Email enabled"),
        help_text=_("Turning this off keeps in-app notifications on."),
    )
    email_mode = models.CharField(
        max_length=20,
        choices=EmailMode.choices,
        default=EmailMode.DAILY_DIGEST,
        verbose_name=_("Email mode"),
    )
    digest_hour_local = models.PositiveSmallIntegerField(
        default=8,
        validators=[MinValueValidator(0), MaxValueValidator(23)],
        verbose_name=_("Digest hour (local)"),
        help_text=_("Hour of day at which a daily digest is sent. Weekly digests send on Mondays."),
    )
    ai_summary_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable AI summaries"),
        help_text=_(
            "User-level toggle. When off, no batch summaries are generated "
            "even if a subscription has them on."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Notification preference")
        verbose_name_plural = _("Notification preferences")

    def __str__(self):
        return f"NotificationPreference(user={self.user_id}, {self.email_mode})"

    @classmethod
    def get_for_user(cls, user):
        """Return the user's preference, creating the documented defaults."""
        preference, _created = cls.objects.get_or_create(user=user)
        return preference

    @classmethod
    def get_for_user_id(cls, user_id: int):
        """Same as ``get_for_user`` but by id (tasks carry ids, not instances)."""
        preference, _created = cls.objects.get_or_create(user_id=user_id)
        return preference
