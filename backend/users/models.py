from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


def _generate_public_slug():
    """Generate a short unique slug for public sharing."""
    import uuid
    return uuid.uuid4().hex[:12]


class Subscription(models.Model):
    name = models.CharField(max_length=50)
    max_requests_per_day = models.PositiveIntegerField(default=1000)
    price = models.DecimalField(max_digits=6, decimal_places=2)
    can_access_premium_data = models.BooleanField(default=False)
    can_queue_bulk_tasks = models.BooleanField(default=False)
    max_saved_items = models.PositiveIntegerField(default=100)  # New: limit saved items
    max_search_history = models.PositiveIntegerField(
        default=50
    )  # New: limit search history

    def __str__(self):
        return self.name


class CustomUser(AbstractUser):
    clerk_id = models.CharField(max_length=255, unique=True, null=True, blank=True)
    subscription = models.ForeignKey(
        Subscription, null=True, blank=True, on_delete=models.SET_NULL
    )
    subscription_expires = models.DateTimeField(null=True, blank=True)
    api_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    usage_this_month = models.IntegerField(default=0)

    # Email verification for Django-registered users (Clerk handles this for Clerk users)
    email_verified = models.BooleanField(
        default=False, help_text="Whether email has been verified"
    )
    email_verification_token = models.UUIDField(
        null=True, blank=True, help_text="Token for email verification"
    )
    email_verification_token_expires = models.DateTimeField(
        null=True, blank=True, help_text="Expiry time for verification token"
    )

    # Password reset for Django-registered users
    password_reset_token = models.UUIDField(
        null=True, blank=True, help_text="Token for password reset"
    )
    password_reset_token_expires = models.DateTimeField(
        null=True, blank=True, help_text="Expiry time for password reset token"
    )

    # User preferences
    preferred_theme = models.CharField(max_length=20, default="light")  # light/dark
    preferred_palette = models.CharField(
        max_length=20, default="blue"
    )  # blue/purple/green/etc
    preferred_layout = models.CharField(max_length=30, default="horizontal-right")
    preferred_language = models.CharField(
        max_length=10, default="en", choices=[("en", "English"), ("el", "Greek")]
    )  # en/el

    # AI spend tracking (rolled up from AIInteractionLog by CostLedgerService)
    ai_spent_this_month_usd = models.DecimalField(
        max_digits=10, decimal_places=2, default=0
    )
    ai_spent_month = models.IntegerField(
        null=True, blank=True, help_text="YYYYMM for monthly reset logic"
    )

    # AI feature flags
    ai_enabled = models.BooleanField(
        default=True,
        help_text="Master switch — when off, no AI calls are made for this user.",
    )
    ai_system_key_accepted = models.BooleanField(
        default=False,
        help_text="User has acknowledged using the platform system key for AI.",
    )

    @property
    def has_active_subscription(self):
        return (
            self.subscription is not None
            and self.subscription_expires is not None
            and self.subscription_expires > timezone.now()
        )

    @property
    def daily_request_limit(self):
        if self.has_active_subscription:
            return self.subscription.max_requests_per_day
        return 100  # Default limit for authenticated users without subscription

    @property
    def max_saved_items(self):
        if self.has_active_subscription:
            return self.subscription.max_saved_items
        return 20  # Free tier limit

    @property
    def max_search_history(self):
        if self.has_active_subscription:
            return self.subscription.max_search_history
        return 10  # Free tier limit

    def __str__(self):
        return self.username


# New: User activity tracking models
class BookmarkFolder(models.Model):
    """Folders to organize bookmarks"""

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="bookmark_folders"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    color = models.CharField(
        max_length=7, default="#3b82f6", help_text="Hex color code for folder"
    )
    icon = models.CharField(max_length=50, blank=True, help_text="Icon name or emoji")
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="subfolders",
        help_text="Parent folder for nested organization",
    )
    # Sharing
    is_public = models.BooleanField(
        default=False,
        help_text="When enabled, this folder and its bookmarks are publicly accessible via a share link",
    )
    public_slug = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        default=_generate_public_slug,
        help_text="Unique slug for the public share URL",
    )
    public_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this folder was first made public",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        unique_together = ["user", "name", "parent"]

    def __str__(self):
        return f"{self.user.username} - {self.name}"


class Bookmark(models.Model):
    """URL-based bookmarks for any view/filter combination"""

    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="bookmarks"
    )
    title = models.CharField(
        max_length=255, help_text="User-defined title for the bookmark"
    )
    url = models.TextField(help_text="Full URL path including query parameters")
    notes = models.TextField(blank=True)
    folder = models.ForeignKey(
        BookmarkFolder,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookmarks",
    )

    # Metadata for better UX
    view_type = models.CharField(
        max_length=50,
        blank=True,
        help_text="Type of view (e.g., temporal, entity, search, decision)",
    )
    preview_data = models.JSONField(
        null=True,
        blank=True,
        help_text="Cached preview data (e.g., filter summary, result counts)",
    )

    is_favorite = models.BooleanField(default=False)
    visit_count = models.PositiveIntegerField(default=0)
    last_visited = models.DateTimeField(null=True, blank=True)

    # Sharing
    is_public = models.BooleanField(
        default=False,
        help_text="When enabled, this bookmark is publicly accessible via a share link",
    )
    public_slug = models.CharField(
        max_length=32,
        unique=True,
        null=True,
        blank=True,
        default=_generate_public_slug,
        help_text="Unique slug for the public share URL",
    )
    public_created_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When this bookmark was first made public",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        indexes = [
            models.Index(fields=["user", "is_favorite"]),
            models.Index(fields=["user", "folder"]),
            models.Index(fields=["user", "-last_visited"]),
        ]

    def __str__(self):
        return f"{self.user.username} - {self.title}"


class SavedDecision(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="saved_decisions"
    )
    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="saved_by_users",
        to_field="ada",
    )
    tags = models.JSONField(default=list, blank=True)
    notes = models.TextField(blank=True)
    is_favorite = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["user", "decision"]  # New constraint
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.user.username} - {self.decision.ada}"

    # Convenience properties for backward compatibility
    @property
    def decision_ada(self):
        return self.decision.ada

    @property
    def decision_subject(self):
        return self.decision.subject


class SearchHistory(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name="search_history"
    )
    query = models.TextField()
    filters = models.JSONField(null=True, blank=True)  # Store search filters
    results_count = models.IntegerField(null=True, blank=True)
    search_type = models.CharField(
        max_length=50, default="general"
    )  # 'general', 'entity', 'decision'
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.query[:50]}"


class AllowedUser(models.Model):
    """
    Allowlist for stealth mode access control.

    When STEALTH_MODE is enabled with STEALTH_ALLOWLIST=true,
    only users in this list can access the app after authenticating.
    Users are identified by email and/or Clerk user ID.
    """

    email = models.EmailField(unique=True, help_text="User's email address")
    clerk_user_id = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        help_text="Clerk user ID (optional, auto-filled on first login)",
    )
    name = models.CharField(max_length=255, blank=True, help_text="User's full name")
    is_active = models.BooleanField(
        default=True, help_text="Uncheck to temporarily revoke access without deleting"
    )
    notes = models.TextField(blank=True, help_text="Internal notes about this user")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        CustomUser,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_allowed_users",
        help_text="Admin who added this user",
    )

    class Meta:
        verbose_name = "Allowed User"
        verbose_name_plural = "Allowed Users"
        ordering = ["email"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["clerk_user_id"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        status = "[OK]" if self.is_active else "[FAIL]"
        return f"{status} {self.email}" + (f" ({self.name})" if self.name else "")
