from core.models.decisions import Decision
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class HealthStatus(models.TextChoices):
    HEALTHY = "HEALTHY", _("Healthy")
    WARNING = "WARNING", _("Warning")
    ERROR = "ERROR", _("Error")
    UNKNOWN = "UNKNOWN", _("Unknown")


class DecisionHealthCheck(models.Model):
    """
    Tracks the health status of each decision across the entire pipeline.
    This helps identify where problems occur in the ingestion flow.
    """

    decision = models.OneToOneField(
        Decision,
        on_delete=models.CASCADE,
        related_name="health_check",
        help_text="The decision being monitored",
    )

    # Denormalized field for efficient querying
    decision_issue_date = models.DateField(
        db_index=True,
        null=True,
        blank=True,
        help_text="Denormalized issue_date from Decision for efficient filtering",
    )

    # Overall health status
    overall_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        db_index=True,
        help_text="Overall pipeline health status",
    )

    # Individual component statuses
    import_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Decision imported from DTO to database with all relations",
    )

    organization_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Organization resolution completed for signers and units",
    )

    ingestion_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Decision exists in database (legacy field, use import_status)",
    )

    relations_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Signers, units, organization properly linked",
    )

    entities_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="AFM entities extracted and associated",
    )

    document_extraction_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Document downloaded and text extracted",
    )

    opensearch_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="Document indexed in OpenSearch and searchable",
    )

    coverage_status = models.CharField(
        max_length=10,
        choices=HealthStatus.choices,
        default=HealthStatus.UNKNOWN,
        help_text="DateCoverage records updated",
    )

    # Detailed findings for investigation
    findings = models.JSONField(
        default=dict,
        help_text="Detailed findings and error messages for each component",
    )

    # Check metadata
    last_checked_at = models.DateTimeField(auto_now=True)
    check_duration_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Time taken to perform the health check in milliseconds",
    )

    # Quick problem indicators for filtering
    has_errors = models.BooleanField(
        default=False, db_index=True, help_text="True if any component has ERROR status"
    )
    has_warnings = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if any component has WARNING status",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Decision Health Check")
        verbose_name_plural = _("Decision Health Checks")
        indexes = [
            models.Index(fields=["overall_status"]),
            models.Index(fields=["last_checked_at"]),
            models.Index(fields=["has_errors", "has_warnings"]),
            GinIndex(fields=["findings"]),  # For searching in JSON findings
        ]

    def __str__(self):
        return f"Health Check for {self.decision.ada} - {self.overall_status}"

    def save(self, *args, **kwargs):
        """Override save to sync denormalized fields"""
        # Sync decision_issue_date before saving
        if self.decision_id and not self.decision_issue_date:
            if hasattr(self, "decision") and self.decision:
                self.decision_issue_date = self.decision.issue_date
        super().save(*args, **kwargs)

    @property
    def is_healthy(self):
        """Returns True if all components are healthy"""
        return self.overall_status == HealthStatus.HEALTHY

    @property
    def component_statuses(self):
        """Returns a dictionary of all component statuses"""
        return {
            "ingestion": self.ingestion_status,
            "relations": self.relations_status,
            "entities": self.entities_status,
            "document_extraction": self.document_extraction_status,
            "opensearch": self.opensearch_status,
            "coverage": self.coverage_status,
        }

    @property
    def failed_components(self):
        """Returns list of components with ERROR status"""
        components = self.component_statuses
        return [
            name for name, status in components.items() if status == HealthStatus.ERROR
        ]

    @property
    def warning_components(self):
        """Returns list of components with WARNING status"""
        components = self.component_statuses
        return [
            name
            for name, status in components.items()
            if status == HealthStatus.WARNING
        ]

    def get_finding(self, component):
        """Get detailed finding for a specific component"""
        return self.findings.get(component, {})

    def set_finding(self, component, status, message=None, details=None):
        """Set finding for a specific component"""
        if not self.findings:
            self.findings = {}

        self.findings[component] = {
            "status": status,
            "message": message,
            "details": details,
            "checked_at": timezone.now().isoformat(),
        }

        # Update component status
        setattr(self, f"{component}_status", status)

        # Update overall indicators
        self._update_overall_status()

        # Sync denormalized fields
        self._sync_denormalized_fields()

    def _sync_denormalized_fields(self):
        """Sync denormalized fields from related Decision"""
        if self.decision_id and not self.decision_issue_date:
            # Only fetch if we have a decision_id and haven't set the date yet
            if hasattr(self, "decision") and self.decision:
                self.decision_issue_date = self.decision.issue_date
            else:
                # If decision isn't loaded, fetch just the issue_date
                from core.models.decisions import Decision

                decision_data = (
                    Decision.objects.filter(id=self.decision_id)
                    .values("issue_date")
                    .first()
                )
                if decision_data:
                    self.decision_issue_date = decision_data["issue_date"]

    def _update_overall_status(self):
        """Update overall status and boolean flags based on component statuses"""
        statuses = list(self.component_statuses.values())

        # Count status types
        error_count = statuses.count(HealthStatus.ERROR)
        warning_count = statuses.count(HealthStatus.WARNING)
        statuses.count(HealthStatus.HEALTHY)
        unknown_count = statuses.count(HealthStatus.UNKNOWN)

        # Update boolean flags
        self.has_errors = error_count > 0
        self.has_warnings = warning_count > 0

        # Determine overall status
        if error_count > 0:
            self.overall_status = HealthStatus.ERROR
        elif warning_count > 0:
            self.overall_status = HealthStatus.WARNING
        elif unknown_count > 0:
            self.overall_status = HealthStatus.UNKNOWN
        else:
            self.overall_status = HealthStatus.HEALTHY


class DecisionHealthSummary(models.Model):
    """
    Aggregated health statistics for monitoring dashboard.
    Updated periodically to avoid expensive queries.
    """

    # Time period for this summary
    date = models.DateField(db_index=True)
    organization = models.ForeignKey(
        "Organization", on_delete=models.CASCADE, null=True, blank=True
    )

    # Health counts
    total_decisions = models.IntegerField(default=0)
    healthy_decisions = models.IntegerField(default=0)
    warning_decisions = models.IntegerField(default=0)
    error_decisions = models.IntegerField(default=0)
    unknown_decisions = models.IntegerField(default=0)

    # Component-specific error counts
    ingestion_errors = models.IntegerField(default=0)
    relations_errors = models.IntegerField(default=0)
    entities_errors = models.IntegerField(default=0)
    document_extraction_errors = models.IntegerField(default=0)
    opensearch_errors = models.IntegerField(default=0)
    coverage_errors = models.IntegerField(default=0)

    # Metadata
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("Decision Health Summary")
        verbose_name_plural = _("Decision Health Summaries")
        unique_together = [["date", "organization"]]
        indexes = [
            models.Index(fields=["date"]),
            models.Index(fields=["last_updated"]),
        ]

    def __str__(self):
        org_str = f" ({self.organization})" if self.organization else ""
        return f"Health Summary for {self.date}{org_str}"

    @property
    def health_percentage(self):
        """Returns percentage of healthy decisions"""
        if self.total_decisions == 0:
            return 0
        return round((self.healthy_decisions / self.total_decisions) * 100, 1)
