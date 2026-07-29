"""
DecisionAIAnalysis — derivative model storing AI analysis results per decision.

Follows the same pattern as ``DecisionClassification``: a ``OneToOneField``
to ``Decision`` with ``primary_key=True`` so the decision PK is the analysis PK.

Each decision can have at most one "current" analysis.  Re-running an analysis
overwrites the previous result (the old ``PipelineRun`` is kept for audit).
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
    One-to-one storage for AI analysis results on a decision.

    Currently supports a "summary" analysis type.  Future types (extraction,
    entity checks, etc.) can share this model by adding a discriminator field
    or by creating additional derivative models.
    """

    decision = models.OneToOneField(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="ai_analysis",
        primary_key=True,
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
        db_index=True,
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
