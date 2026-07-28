"""
UserAISettings model — per-user AI provider configuration.

Stores an encrypted API key (via :mod:`core.utils.encryption`) and a default
model.  When a user has no key (or their settings are inactive) the system
fallback key is used and calls are billed to ``SYSTEM``.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from core.utils.encryption import decrypt, encrypt


class UserAISettings(models.Model):
    """Per-user AI provider settings (API key, default model, budget)."""

    class Provider(models.TextChoices):
        OPENROUTER = "OPENROUTER", _("OpenRouter")
        AWS_BEDROCK = "AWS_BEDROCK", _("AWS Bedrock")

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="ai_settings",
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
        ordering = ["-created_at"]

    def __str__(self):
        return f"AI Settings for {self.user}"

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
            # Key rotated / corrupted — treat as no key
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
