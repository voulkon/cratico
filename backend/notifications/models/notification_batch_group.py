"""Presentation/email grouping of notification batches.

A group is the unit users see and the email renders.  It deliberately owns no
AI summary fields: summaries are generated per batch at detection time, and
the shareable asset is the per-decision ``DecisionOneLiner``.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationBatchGroup(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_batch_groups",
        verbose_name=_("User"),
    )
    subscription = models.ForeignKey(
        "notifications.NotificationSubscription",
        on_delete=models.CASCADE,
        related_name="batch_groups",
        verbose_name=_("Subscription"),
    )

    period_start = models.DateTimeField(verbose_name=_("Period start"))
    period_end = models.DateTimeField(verbose_name=_("Period end"))
    local_date = models.DateField(verbose_name=_("Local date"))

    total_match_count = models.IntegerField(
        default=0, verbose_name=_("Total match count")
    )
    is_read = models.BooleanField(default=False, verbose_name=_("Read"))
    is_dismissed = models.BooleanField(default=False, verbose_name=_("Dismissed"))
    email_sent = models.BooleanField(default=False, verbose_name=_("Email sent"))
    email_sent_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Email sent at")
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated at"))

    class Meta:
        verbose_name = _("Notification Batch Group")
        verbose_name_plural = _("Notification Batch Groups")
        ordering = ["-period_end"]
        constraints = [
            models.UniqueConstraint(
                fields=["subscription", "period_start", "period_end"],
                name="unique_subscription_group_period",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "local_date"]),
            models.Index(fields=["subscription", "period_end"]),
        ]

    def __str__(self):
        return (
            f"Group #{self.id} - subscription {self.subscription_id} "
            f"({self.period_start} → {self.period_end})"
        )

    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.save(update_fields=["is_read", "updated_at"])

    def dismiss(self):
        if not self.is_dismissed:
            self.is_dismissed = True
            self.save(update_fields=["is_dismissed", "updated_at"])
