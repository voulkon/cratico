"""
DecisionAIAnalysis — stores AI analysis results per decision.

Each decision can have multiple analyses (e.g. different models, re-runs).
The relationship is a ``ForeignKey`` so analyses accumulate over time rather
than overwriting each other.  The ``PipelineRun`` is kept for audit.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class AnalysisStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")
    SKIPPED = "SKIPPED", _("Skipped")


class DecisionAIAnalysis(models.Model):
    """
    AI analysis results for a decision.

    Multiple analyses may exist per decision (e.g. different models, re-runs).
    The most recent COMPLETED analysis is typically surfaced to the user.
    """

    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="ai_analyses",
    )

    # Pipeline run that produced this analysis (nullable for manual/legacy)
    pipeline_run = models.ForeignKey(
        "core.PipelineRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decision_analyses",
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=AnalysisStatus.choices,
        default=AnalysisStatus.PENDING,
    )

    # Result content
    summary = models.TextField(
        null=True,
        blank=True,
        help_text=_("AI-generated summary of the decision document."),
    )

    # Cost / metadata
    cost_usd = models.DecimalField(
        max_digits=10,
        decimal_places=6,
        null=True,
        blank=True,
    )
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    model_used = models.CharField(max_length=200, null=True, blank=True)

    # Error tracking
    error_message = models.TextField(null=True, blank=True)

    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Decision AI Analysis")
        verbose_name_plural = _("Decision AI Analyses")
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return f"AIAnalysis({self.decision.ada} · {self.status})"
