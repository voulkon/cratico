"""
AIInteractionLog model — audit trail for every AI call.

Records tokens in/out, cost, latency, status, and the billing attribution
(``USER`` vs ``SYSTEM``) so users and the operator can audit spend.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AIInteractionLog(models.Model):
    """A single AI provider invocation, with cost attribution."""

    class BilledTo(models.TextChoices):
        USER = "USER", _("User")
        SYSTEM = "SYSTEM", _("System")

    class Status(models.TextChoices):
        SUCCESS = "SUCCESS", _("Success")
        FAILED = "FAILED", _("Failed")

    # Attribution
    user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="ai_interactions",
    )
    billed_to = models.CharField(
        max_length=10, choices=BilledTo.choices, default=BilledTo.SYSTEM
    )

    # Trigger context
    trigger = models.CharField(
        max_length=50,
        help_text=_('What initiated this call (e.g. "notification_batch_summary").'),
    )
    trigger_ref = models.CharField(
        max_length=100, null=True, blank=True,
        help_text=_('Opaque reference, e.g. "batch:42".'),
    )

    # Call details
    provider = models.CharField(max_length=50)
    model_name = models.CharField(max_length=200)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    latency_ms = models.IntegerField(null=True, blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SUCCESS
    )
    error_message = models.TextField(null=True, blank=True)

    # Pipeline linkage (nullable so logs can exist outside pipelines too)
    pipeline_run = models.ForeignKey(
        "core.PipelineRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interactions",
    )
    pipeline_step_run = models.ForeignKey(
        "core.PipelineStepRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interactions",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("AI Interaction Log")
        verbose_name_plural = _("AI Interaction Logs")
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["billed_to", "created_at"]),
            models.Index(fields=["provider", "model_name"]),
            models.Index(fields=["trigger", "created_at"]),
        ]

    def __str__(self):
        return f"AIInteractionLog({self.provider}/{self.model_name} · {self.cost_usd} USD · {self.status})"
