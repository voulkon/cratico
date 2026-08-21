"""
UserAIModelPreference — per-user AI model preference, independent of API keys.

A user's model choice lives here, separately from ``UserAISettings``, so that
a user can express a model preference even when using the system's API key.

Resolution order (implemented in ``AICallStep._resolve_model``):
    1. ``UserAIModelPreference.preferred_model`` (if set)
    2. ``PipelineStep.config.model`` (pipeline default)
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class UserAIModelPreference(models.Model):
    """A user's preferred AI model, independent of their API key configuration."""

    user = models.OneToOneField(
        "users.CustomUser",
        on_delete=models.CASCADE,
        related_name="ai_model_preference",
    )

    preferred_model = models.CharField(
        max_length=200,
        null=True,
        blank=True,
        help_text=_(
            "The user's preferred model ID (e.g. 'openai/gpt-4o'). "
            "When set, this overrides the pipeline's default model. "
            "Leave blank to use the pipeline default."
        ),
    )

    max_tokens = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_(
            "User-set output-token budget for AI pipeline calls. "
            "Leave blank to use the code-level default. Clamped to a safe "
            "ceiling at call time."
        ),
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User AI Model Preference")
        verbose_name_plural = _("User AI Model Preferences")

    def __str__(self):
        model = self.preferred_model or "(pipeline default)"
        return f"Model preference for {self.user}: {model}"

    @classmethod
    def get_preferred_model(cls, user) -> str | None:
        """
        Return the user's preferred model, or ``None`` if not set.

        Returns ``None`` when *user* is ``None`` or has no preference,
        signalling the caller to fall back to the pipeline default.
        """
        if user is None:
            return None
        try:
            pref = cls.objects.filter(user=user).only("preferred_model").first()
            return pref.preferred_model if pref else None
        except cls.DoesNotExist:
            return None

    @classmethod
    def get_preferred_max_tokens(cls, user) -> int | None:
        """
        Return the user's preferred ``max_tokens``, or ``None`` if unset.

        Returns ``None`` when *user* is ``None`` or has no preference,
        signalling the caller to fall back to the code-level default.
        """
        if user is None:
            return None
        try:
            pref = cls.objects.filter(user=user).only("max_tokens").first()
            return pref.max_tokens if pref and pref.max_tokens else None
        except cls.DoesNotExist:
            return None
