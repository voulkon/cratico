from django.db import models
from django.utils.translation import gettext_lazy as _


class NotificationBatch(models.Model):
    """
    A batch of matching decisions for a notification subscription.

    Represents one "check" of a subscription that found multiple matching decisions.
    Replaces the one-notification-per-decision model to prevent notification spam.
    """

    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="notification_batches",
        verbose_name=_("User"),
    )

    subscription = models.ForeignKey(
        "notifications.NotificationSubscription",
        on_delete=models.CASCADE,
        related_name="batches",
        verbose_name=_("Subscription"),
        help_text=_("The subscription that triggered this batch"),
    )

    # Time window that was checked
    check_window_start = models.DateTimeField(
        verbose_name=_("Check window start"),
        help_text=_("Start of the time range checked for matching decisions"),
    )

    check_window_end = models.DateTimeField(
        verbose_name=_("Check window end"),
        help_text=_("End of the time range checked for matching decisions"),
    )

    # Match counts
    match_count = models.IntegerField(
        default=0,
        verbose_name=_("Match count"),
        help_text=_("Total number of decisions that matched"),
    )

    # Aggregate statistics (from matching decisions)
    aggregate_stats = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Aggregate statistics"),
        help_text=_(
            "Pre-computed stats: total_amount, avg_amount, decision_type_breakdown, etc."
        ),
    )

    # Status
    is_read = models.BooleanField(
        default=False,
        verbose_name=_("Read"),
        help_text=_("Whether the user has viewed this batch"),
    )

    is_dismissed = models.BooleanField(
        default=False,
        verbose_name=_("Dismissed"),
        help_text=_("Whether the user has dismissed this batch"),
    )

    # Email tracking
    email_sent = models.BooleanField(
        default=False,
        verbose_name=_("Email sent"),
        help_text=_("Whether an email notification has been sent for this batch"),
    )

    email_sent_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Email sent at"),
        help_text=_("When the email notification was sent"),
    )

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    read_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Read at"))

    dismissed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Dismissed at")
    )

    # AI summary
    ai_summary = models.TextField(
        null=True, blank=True, verbose_name=_("AI summary"),
        help_text=_("AI-generated summary of the decisions in this batch"),
    )
    ai_summary_status = models.CharField(
        max_length=20,
        default="PENDING",
        verbose_name=_("AI summary status"),
        help_text=_("PENDING / RUNNING / COMPLETED / FAILED / SKIPPED"),
    )
    ai_summary_run = models.ForeignKey(
        "core.PipelineRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="notification_batches",
        verbose_name=_("AI summary pipeline run"),
    )
    ai_summary_error = models.TextField(
        null=True, blank=True, verbose_name=_("AI summary error"),
    )
    ai_summary_completed_at = models.DateTimeField(
        null=True, blank=True, verbose_name=_("AI summary completed at"),
    )

    class Meta:
        verbose_name = _("Notification Batch")
        verbose_name_plural = _("Notification Batches")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read", "is_dismissed"]),
            models.Index(fields=["subscription", "created_at"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            # Prevent duplicate batches for same subscription+time window
            models.UniqueConstraint(
                fields=["subscription", "check_window_start", "check_window_end"],
                name="unique_subscription_time_window",
            ),
        ]

    def __str__(self):
        return f"Batch #{self.id} - {self.subscription.user.username} - {self.match_count} decisions"

    def mark_as_read(self):
        """Mark this batch as read."""
        from django.utils import timezone

        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=["is_read", "read_at"])

    def dismiss(self):
        """Dismiss this batch."""
        from django.utils import timezone

        if not self.is_dismissed:
            self.is_dismissed = True
            self.dismissed_at = timezone.now()
            self.save(update_fields=["is_dismissed", "dismissed_at"])


class NotificationBatchDecision(models.Model):
    """
    Junction table linking batches to decisions.

    Many-to-many relationship with additional metadata about why each decision matched.
    """

    batch = models.ForeignKey(
        "notifications.NotificationBatch",
        on_delete=models.CASCADE,
        related_name="batch_decisions",
        verbose_name=_("Batch"),
    )

    subscription = models.ForeignKey(
        "notifications.NotificationSubscription",
        on_delete=models.CASCADE,
        related_name="batch_decisions",
        verbose_name=_("Subscription"),
        help_text=_(
            "Denormalized subscription reference to enable unique constraint across batches"
        ),
    )

    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="notification_batches",
        verbose_name=_("Decision"),
    )

    # Match metadata (snapshot at time of matching)
    match_reason = models.CharField(
        max_length=100,
        verbose_name=_("Match reason"),
        help_text=_(
            "Why this decision matched (e.g., 'keyword_match', 'amount_filter', 'organization')"
        ),
    )

    match_details = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Match details"),
        help_text=_(
            "Details about the match (e.g., which keywords matched, decision snapshot)"
        ),
    )

    # View tracking (for future use)
    is_viewed = models.BooleanField(
        default=False,
        verbose_name=_("Viewed"),
        help_text=_("Whether the user has viewed this specific decision"),
    )

    viewed_at = models.DateTimeField(null=True, blank=True, verbose_name=_("Viewed at"))

    # Timestamp
    added_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Added at"))

    class Meta:
        verbose_name = _("Notification Batch Decision")
        verbose_name_plural = _("Notification Batch Decisions")
        ordering = ["-added_at"]
        indexes = [
            models.Index(fields=["batch", "decision"]),
            models.Index(fields=["decision"]),
            models.Index(fields=["is_viewed"]),
            models.Index(fields=["subscription", "decision"]),
        ]
        constraints = [
            # Prevent duplicate decision in same batch
            models.UniqueConstraint(
                fields=["batch", "decision"], name="unique_batch_decision"
            ),
            # Prevent same decision appearing in multiple batches for same subscription
            models.UniqueConstraint(
                fields=["subscription", "decision"], name="unique_subscription_decision"
            ),
        ]

    def __str__(self):
        return f"Batch #{self.batch_id} - Decision {self.decision.ada if self.decision else 'N/A'}"

    def mark_as_viewed(self):
        """Mark this decision as viewed."""
        from django.utils import timezone

        if not self.is_viewed:
            self.is_viewed = True
            self.viewed_at = timezone.now()
            self.save(update_fields=["is_viewed", "viewed_at"])
