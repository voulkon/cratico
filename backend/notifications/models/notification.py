from django.db import models
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    """
    A notification for a user about a decision that matched their subscription.
    """

    # Match reason choices
    MATCH_ORGANIZATION = "organization"
    MATCH_ENTITY = "entity"
    MATCH_RELATIONSHIP = "relationship"
    MATCH_PERSON = "person"
    MATCH_SIGNER = "signer"
    MATCH_FILTER = "filter"
    MATCH_KEYWORD = "keyword_match"
    MATCH_AMOUNT = "amount_match"

    MATCH_REASONS = [
        (MATCH_ORGANIZATION, _("Organization match")),
        (MATCH_ENTITY, _("Entity match")),
        (MATCH_RELATIONSHIP, _("Relationship match")),
        (MATCH_PERSON, _("Person match")),
        (MATCH_SIGNER, _("Signer match")),
        (MATCH_FILTER, _("Filter match")),
        (MATCH_KEYWORD, _("Keyword match")),
        (MATCH_AMOUNT, _("Amount match")),
    ]

    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("User"),
    )

    subscription = models.ForeignKey(
        "notifications.NotificationSubscription",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Subscription"),
    )

    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("Decision"),
    )

    match_reason = models.CharField(
        max_length=50,
        choices=MATCH_REASONS,
        verbose_name=_("Match reason"),
        help_text=_("What type of match triggered this notification"),
    )

    match_details = models.JSONField(
        verbose_name=_("Match details"),
        help_text=_("Details about what matched (keywords found, amounts, etc.)"),
    )

    is_read = models.BooleanField(
        default=False,
        verbose_name=_("Read"),
        help_text=_("Whether the user has read this notification"),
    )

    is_dismissed = models.BooleanField(
        default=False,
        verbose_name=_("Dismissed"),
        help_text=_("Whether the user has dismissed this notification"),
    )

    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))

    read_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Read at"),
        help_text=_("When the notification was marked as read"),
    )

    class Meta:
        verbose_name = _("Notification")
        verbose_name_plural = _("Notifications")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user", "subscription", "decision"],
                name="unique_notification_per_user_subscription_decision",
            )
        ]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self):
        return f"Notification for {self.user.username}: {self.match_reason} - {self.decision.ada}"
