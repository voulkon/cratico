"""
UserAISettings model — per-user AI provider configuration.

A user may have several settings rows (e.g. multiple providers/keys), but at
most one is marked ``is_default``.  The default row drives key resolution,
budget enforcement and billing attribution.  When a user has no usable key
(or their settings are inactive) the system fallback key is used and calls
are billed to ``SYSTEM``.
"""

import logging

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.utils.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)


class UserAISettings(models.Model):
    """Per-user AI provider settings (API key, default model, budget)."""

    class Provider(models.TextChoices):
        OPENROUTER = "OPENROUTER", _("OpenRouter")
        AWS_BEDROCK = "AWS_BEDROCK", _("AWS Bedrock")

    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="ai_settings",
    )
    label = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=_("Optional human-friendly name to distinguish multiple keys."),
    )
    is_default = models.BooleanField(
        default=False,
        help_text=_(
            "The default row is used for key resolution and billing. "
            "At most one row per user may be the default."
        ),
    )
    provider = models.CharField(
        max_length=50,
        choices=Provider.choices,
        default=Provider.OPENROUTER,
    )

    # Encrypted — never expose in API responses without explicit unmask
    api_key_encrypted = models.TextField(null=True, blank=True)

    default_model = models.CharField(max_length=200, null=True, blank=True)

    # Budget controls
    monthly_budget_usd = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text=_("User-set soft cap. Null = unlimited."),
    )
    is_active = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User AI Settings")
        verbose_name_plural = _("User AI Settings")
        ordering = ["-is_default", "-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="unique_default_ai_settings_per_user",
            )
        ]

    def __str__(self):
        suffix = " (default)" if self.is_default else ""
        return f"AI Settings for {self.user}{suffix}"

    def save(self, *args, **kwargs):
        # First row for a user becomes the default automatically.
        if not self.pk and not self.is_default:
            if not UserAISettings.objects.filter(user=self.user).exists():
                self.is_default = True
        # Setting this row as default clears the flag on siblings so the
        # unique constraint is never violated.
        if self.is_default and self.user_id:
            UserAISettings.objects.filter(user_id=self.user_id, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Default-row resolution
    # ------------------------------------------------------------------
    @classmethod
    def get_default_for_user(cls, user) -> "UserAISettings | None":
        """Return the user's default settings row, or ``None``."""
        if user is None:
            return None
        return (
            cls.objects.filter(user=user, is_default=True).first()
            or cls.objects.filter(user=user).order_by("created_at").first()
        )

    # ------------------------------------------------------------------
    # API key helpers
    # ------------------------------------------------------------------
    def set_api_key(self, plaintext: str | None) -> None:
        """Encrypt and store *plaintext*.  Pass ``None``/``""`` to clear."""
        if not plaintext:
            self.api_key_encrypted = ""
        else:
            self.api_key_encrypted = encrypt(plaintext)

    def get_api_key(self) -> str | None:
        """Return the decrypted key, or ``None`` if none is stored."""
        if not self.api_key_encrypted:
            return None
        try:
            return decrypt(self.api_key_encrypted)
        except Exception:
            # Key rotated / corrupted / encrypted under a different
            # AI_SECRETS_KEY — treat as no key, but make it visible.
            logger.warning(
                "UserAISettings %s (user=%s): failed to decrypt stored API "
                "key — AI_SECRETS_KEY may have changed. Treating as no key.",
                self.pk,
                self.user_id,
                exc_info=True,
            )
            return None

    @property
    def has_own_key(self) -> bool:
        """True when the user has a usable, active key of their own."""
        return self.is_active and bool(self.get_api_key())

    @property
    def masked_key(self) -> str:
        """Return a masked representation for API responses (``sk-...XXXX``)."""
        key = self.get_api_key()
        if not key:
            return ""
        if len(key) <= 8:
            return "****"
        return f"{key[:3]}...{key[-4:]}"

    # ------------------------------------------------------------------
    # Key resolution
    # ------------------------------------------------------------------
    @property
    def effective_api_key(self) -> str:
        """
        Return the key that should be used for AI calls.

        Precedence: user key → system fallback key (from settings).
        """
        own = self.get_api_key()
        if own and self.is_active:
            return own
        return getattr(settings, "OPENROUTER_API_KEY", "") or ""

    @property
    def billed_to(self) -> str:
        """``"USER"`` when using own key, ``"SYSTEM"`` when on fallback."""
        return "USER" if self.has_own_key else "SYSTEM"
