"""
Pipeline engine models — data-driven DAG of processing steps.

A ``PipelineDefinition`` is an ordered list of ``PipelineStep``s.  Each step
has a ``step_type`` (EXTRACT, PREPROCESS, AI_CALL, AGGREGATE) and a JSON
``config`` blob interpreted by the corresponding step executor.

A ``PipelineRun`` records a single execution of a pipeline, with
``PipelineStepRun`` children for each step's outcome.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _


class StepType(models.TextChoices):
    EXTRACT = "EXTRACT", _("Extract")
    PREPROCESS = "PREPROCESS", _("Preprocess")
    AI_CALL = "AI_CALL", _("AI Call")
    AGGREGATE = "AGGREGATE", _("Aggregate")


class RunStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class BilledTo(models.TextChoices):
    USER = "USER", _("User")
    SYSTEM = "SYSTEM", _("System")


class PipelineDefinition(models.Model):
    """A named, versioned pipeline of steps."""

    name = models.CharField(max_length=100, unique=True)
    version = models.IntegerField(default=1)
    description = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    trigger_type = models.CharField(
        max_length=50, null=True, blank=True,
        help_text=_('Grouping key, e.g. "notification_batch_summary".'),
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("Pipeline Definition")
        verbose_name_plural = _("Pipeline Definitions")

    def __str__(self):
        return f"{self.name} (v{self.version})"


class PipelineStep(models.Model):
    """A single step within a pipeline."""

    pipeline = models.ForeignKey(
        PipelineDefinition, on_delete=models.CASCADE, related_name="steps"
    )
    order = models.IntegerField()
    step_type = models.CharField(max_length=20, choices=StepType.choices)
    name = models.CharField(max_length=100)
    config = models.JSONField(default=dict)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]
        unique_together = [["pipeline", "order"]]
        verbose_name = _("Pipeline Step")
        verbose_name_plural = _("Pipeline Steps")

    def __str__(self):
        return f"{self.pipeline.name} · step {self.order}: {self.name}"


class PipelineRun(models.Model):
    """A single execution of a pipeline."""

    pipeline = models.ForeignKey(
        PipelineDefinition, on_delete=models.SET_NULL, null=True, related_name="runs"
    )
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.PENDING
    )
    triggered_by_user = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        related_name="pipeline_runs",
    )
    trigger = models.CharField(max_length=50)
    trigger_ref = models.CharField(max_length=100, null=True, blank=True)
    context = models.JSONField(null=True, blank=True, help_text="Snapshot of inputs.")
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    total_input_tokens = models.IntegerField(default=0)
    total_output_tokens = models.IntegerField(default=0)
    total_cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    billed_to = models.CharField(
        max_length=10, choices=BilledTo.choices, default=BilledTo.SYSTEM
    )
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = _("Pipeline Run")
        verbose_name_plural = _("Pipeline Runs")

    def __str__(self):
        return f"PipelineRun({self.trigger} · {self.status})"


class PipelineStepRun(models.Model):
    """Outcome of a single step within a pipeline run."""

    run = models.ForeignKey(PipelineRun, on_delete=models.CASCADE, related_name="step_runs")
    step = models.ForeignKey(
        PipelineStep, on_delete=models.SET_NULL, null=True, related_name="step_runs"
    )
    order = models.IntegerField()
    status = models.CharField(
        max_length=20, choices=RunStatus.choices, default=RunStatus.PENDING
    )
    input_preview = models.TextField(null=True, blank=True, help_text="Truncated input.")
    output_text = models.TextField(null=True, blank=True)
    input_tokens = models.IntegerField(default=0)
    output_tokens = models.IntegerField(default=0)
    cost_usd = models.DecimalField(max_digits=10, decimal_places=6, default=0)
    latency_ms = models.IntegerField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # For map-reduce: link to the item this step processed
    item_type = models.CharField(max_length=50, null=True, blank=True)
    item_id = models.IntegerField(null=True, blank=True)
    item_identifier = models.CharField(max_length=200, null=True, blank=True)

    class Meta:
        ordering = ["run", "order"]
        verbose_name = _("Pipeline Step Run")
        verbose_name_plural = _("Pipeline Step Runs")

    def __str__(self):
        return f"StepRun({self.run_id} · order {self.order} · {self.status})"
