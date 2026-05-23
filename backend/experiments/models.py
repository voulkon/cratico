from core.models.decisions import Decision
from core.models.types import ActType
from django.db import models


class ExperimentRun(models.Model):
    """
    Tracks a complete experiment run with a specific strategy on a dataset.
    """

    strategy_name = models.CharField(max_length=255, db_index=True)
    strategy_version = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        help_text="Version/commit hash of the strategy",
    )

    # Dataset definition
    decision_type = models.ForeignKey(
        ActType, on_delete=models.SET_NULL, null=True, blank=True
    )
    dataset_filter = models.JSONField(
        help_text="JSON representation of the queryset filters used"
    )
    total_decisions = models.IntegerField()

    # Results summary
    successful_count = models.IntegerField(default=0)
    failed_count = models.IntegerField(default=0)
    success_rate = models.FloatField(
        null=True, blank=True, help_text="Percentage 0-100"
    )

    # Timing
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)

    # Metadata
    notes = models.TextField(blank=True, help_text="Manual notes about this experiment")
    config = models.JSONField(default=dict, help_text="Strategy-specific configuration")

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(fields=["strategy_name", "-started_at"]),
            models.Index(fields=["decision_type", "-started_at"]),
            models.Index(fields=["-success_rate"]),
        ]

    def __str__(self):
        return f"{self.strategy_name} - {self.started_at.strftime('%Y-%m-%d %H:%M')}"

    def calculate_metrics(self):
        """Recalculate summary metrics from results"""
        results = self.results.all()
        self.total_decisions = results.count()
        self.successful_count = results.filter(success=True).count()
        self.failed_count = results.filter(success=False).count()
        if self.total_decisions > 0:
            self.success_rate = (self.successful_count / self.total_decisions) * 100
        self.save()


class ExperimentResult(models.Model):
    """
    Individual result for one decision within an experiment run.
    """

    run = models.ForeignKey(
        ExperimentRun, on_delete=models.CASCADE, related_name="results"
    )
    decision = models.ForeignKey(Decision, on_delete=models.CASCADE)

    success = models.BooleanField()
    error_message = models.TextField(null=True, blank=True)

    # Extracted data (strategy-specific)
    extracted_data = models.JSONField(
        default=dict, help_text="Successfully extracted structured data"
    )

    # Performance
    processing_time_ms = models.IntegerField(null=True, blank=True)

    # Quality metrics (optional, strategy-specific)
    confidence_score = models.FloatField(
        null=True, blank=True, help_text="0-1 confidence in the extraction"
    )
    validation_errors = models.JSONField(
        default=list, help_text="List of validation issues found"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["run", "success"]),
            models.Index(fields=["decision"]),
        ]
        unique_together = [["run", "decision"]]

    def __str__(self):
        status = "[OK]" if self.success else "[FAIL]"
        return f"{status} {self.decision.ada} - {self.run.strategy_name}"


class StrategyConfiguration(models.Model):
    """
    Stores validated strategy configurations that work well for specific decision types.
    This is what you "graduate" from experiments to production use.
    """

    decision_type = models.ForeignKey(
        ActType, on_delete=models.CASCADE, related_name="strategy_configs"
    )
    strategy_name = models.CharField(
        max_length=255, db_index=True, help_text="Reference to the Strategy class"
    )
    name = models.CharField(
        max_length=255, help_text="Human-readable name for this configuration"
    )
    description = models.TextField(blank=True)

    # Configuration that makes this strategy work well
    config = models.JSONField(
        default=dict,
        help_text="Strategy-specific parameters, thresholds, regex patterns, model paths, etc.",
    )

    # What this config can extract
    extracted_fields = models.JSONField(
        default=list,
        help_text="List of field names this extracts (e.g., ['amount', 'beneficiary', 'date'])",
    )

    # Performance tracking (from best ExperimentRun)
    best_experiment_run = models.ForeignKey(
        "ExperimentRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="The experiment run that validated this config",
    )
    validated_on_count = models.IntegerField(default=0)
    success_rate = models.FloatField(null=True, blank=True)
    avg_processing_time_ms = models.IntegerField(null=True, blank=True)

    # Lifecycle
    is_active = models.BooleanField(default=True)
    is_production_ready = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.CharField(
        max_length=255, blank=True, help_text="Who created/approved this"
    )

    class Meta:
        ordering = ["-success_rate", "-validated_on_count"]
        indexes = [
            models.Index(fields=["decision_type", "is_active"]),
            models.Index(fields=["strategy_name", "is_production_ready"]),
            models.Index(fields=["-success_rate"]),
        ]
        unique_together = [["decision_type", "strategy_name", "name"]]

    def __str__(self):
        return f"{self.strategy_name}/{self.name} for {self.decision_type.label} ({self.success_rate or 0:.1f}%)"
