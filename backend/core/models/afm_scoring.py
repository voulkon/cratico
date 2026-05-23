"""
AFM Entity Scoring and Queue Configuration Models

These models control how AFM entities are scored, filtered, and prioritized
for company data fetching from GEMI.
"""

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class NormalizationStrategy(models.TextChoices):
    """Normalization strategies for score calculation"""

    MIN_MAX = "MIN_MAX", "Min-Max (0-1 range)"
    Z_SCORE = "Z_SCORE", "Z-Score (standardization)"
    ROBUST = "ROBUST", "Robust Scaling (median/IQR)"
    LOG = "LOG", "Log Transform + Min-Max"


class FeatureImpact(models.TextChoices):
    """Whether higher values improve or decrease score"""

    POSITIVE = "POSITIVE", "Positive (higher is better)"
    NEGATIVE = "NEGATIVE", "Negative (higher is worse)"


class AFMScoringConfig(models.Model):
    """
    Configuration for AFM entity scoring algorithm.
    Only one active configuration should exist at a time.
    """

    name = models.CharField(
        max_length=100,
        help_text="Name for this scoring configuration (e.g., 'Default', 'Aggressive', 'Conservative')",
    )
    is_active = models.BooleanField(
        default=False, help_text="Only one config can be active at a time"
    )

    # === Scoring weights (must sum to 1.0) ===

    # Existing features
    frequency_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for appearance frequency (0-1)",
    )
    amount_weight = models.FloatField(
        default=0.25,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for total transaction amounts (0-1)",
    )
    organization_weight = models.FloatField(
        default=0.15,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for unique organization count (0-1)",
    )

    # New features
    direct_assignment_count_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for number of direct assignments (0-1)",
    )
    direct_assignment_percentage_weight = models.FloatField(
        default=0.20,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text="Weight for percentage of appearances that are direct assignments (0-1)",
    )

    # === Feature impact directions ===

    frequency_impact = models.CharField(
        max_length=10,
        choices=FeatureImpact.choices,
        default=FeatureImpact.POSITIVE,
        help_text="Impact direction for frequency (usually POSITIVE)",
    )
    amount_impact = models.CharField(
        max_length=10,
        choices=FeatureImpact.choices,
        default=FeatureImpact.POSITIVE,
        help_text="Impact direction for amount (usually POSITIVE)",
    )
    organization_impact = models.CharField(
        max_length=10,
        choices=FeatureImpact.choices,
        default=FeatureImpact.POSITIVE,
        help_text="Impact direction for unique organizations (usually POSITIVE)",
    )
    direct_assignment_count_impact = models.CharField(
        max_length=10,
        choices=FeatureImpact.choices,
        default=FeatureImpact.POSITIVE,
        help_text="Impact direction for direct assignment count (POSITIVE = more is better)",
    )
    direct_assignment_percentage_impact = models.CharField(
        max_length=10,
        choices=FeatureImpact.choices,
        default=FeatureImpact.POSITIVE,
        help_text="Impact direction for direct assignment percentage (POSITIVE = higher % is better)",
    )

    # === Normalization strategy ===

    use_simple_scoring = models.BooleanField(
        default=True,
        help_text="Use simple percentage-based scoring (faster) instead of sophisticated normalization",
    )

    normalization_strategy = models.CharField(
        max_length=20,
        choices=NormalizationStrategy.choices,
        default=NormalizationStrategy.ROBUST,
        help_text="Normalization method for feature scaling (only used if use_simple_scoring=False)",
    )

    # === Filtering criteria (minimum thresholds) ===

    min_appearances = models.PositiveIntegerField(
        default=3,
        help_text="Minimum number of decision appearances to be eligible for fetching",
    )
    min_total_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=5000.00,
        help_text="Minimum total transaction amount (€) to be eligible",
    )
    min_unique_organizations = models.PositiveIntegerField(
        default=2, help_text="Minimum number of unique organizations worked with"
    )
    min_direct_assignments = models.PositiveIntegerField(
        default=0, help_text="Minimum number of direct assignments (0 = no minimum)"
    )

    # === Retry configuration ===

    retry_failed_after_days = models.PositiveIntegerField(
        default=90, help_text="Days to wait before retrying a failed GEMI lookup"
    )
    never_retry_after_failures = models.PositiveIntegerField(
        default=5, help_text="Stop retrying after this many consecutive failures"
    )

    # === Recency boost (optional) ===

    enable_recency_boost = models.BooleanField(
        default=False, help_text="Boost score for entities seen recently"
    )
    recency_days_threshold = models.PositiveIntegerField(
        default=30, help_text="Days threshold for recency boost"
    )
    recency_boost_multiplier = models.FloatField(
        default=1.2,
        validators=[MinValueValidator(1.0), MaxValueValidator(3.0)],
        help_text="Multiplier for recent entities (e.g., 1.2 = 20% boost)",
    )

    # === Metadata ===

    notes = models.TextField(blank=True, help_text="Notes about this configuration")

    created_at = models.DateTimeField(
        default=timezone.now, help_text="When this configuration was created"
    )
    updated_at = models.DateTimeField(
        auto_now=True, help_text="When this configuration was last updated"
    )

    class Meta:
        verbose_name = "AFM Scoring Configuration"
        verbose_name_plural = "AFM Scoring Configurations"
        ordering = ["-is_active", "name"]

    def __str__(self):
        status = "ACTIVE" if self.is_active else "Inactive"
        return f"{self.name} ({status})"

    def clean(self):
        """Validate configuration before saving."""
        super().clean()
        self.validate_weights()

    def save(self, *args, **kwargs):
        """Ensure only one active config exists and validate weights."""
        # Validate weights
        self.validate_weights()

        if self.is_active:
            # Deactivate all other configs
            AFMScoringConfig.objects.filter(is_active=True).exclude(pk=self.pk).update(
                is_active=False
            )
        super().save(*args, **kwargs)

    def validate_weights(self):
        """Check that weights sum to approximately 1.0."""
        total = (
            self.frequency_weight
            + self.amount_weight
            + self.organization_weight
            + self.direct_assignment_count_weight
            + self.direct_assignment_percentage_weight
        )
        if not (0.99 <= total <= 1.01):  # Allow small floating point errors
            raise ValidationError(
                f"Weights must sum to 1.0, got {total:.3f}. "
                f"Current: frequency={self.frequency_weight}, "
                f"amount={self.amount_weight}, "
                f"organization={self.organization_weight}, "
                f"direct_count={self.direct_assignment_count_weight}, "
                f"direct_pct={self.direct_assignment_percentage_weight}"
            )

    def get_feature_config(self) -> dict:
        """
        Get feature configuration as a dictionary.

        Returns:
            Dict with feature names, weights, and impact directions
        """
        return {
            "frequency": {
                "weight": self.frequency_weight,
                "impact": self.frequency_impact,
            },
            "amount": {
                "weight": self.amount_weight,
                "impact": self.amount_impact,
            },
            "organization": {
                "weight": self.organization_weight,
                "impact": self.organization_impact,
            },
            "direct_assignment_count": {
                "weight": self.direct_assignment_count_weight,
                "impact": self.direct_assignment_count_impact,
            },
            "direct_assignment_percentage": {
                "weight": self.direct_assignment_percentage_weight,
                "impact": self.direct_assignment_percentage_impact,
            },
        }

    @classmethod
    def get_active(cls):
        """Get the active scoring configuration."""
        return cls.objects.filter(is_active=True).first()


class AFMEntityScore(models.Model):
    """
    Stores computed importance scores for AFM entities.
    Updated periodically by scoring service.
    """

    entity = models.OneToOneField(
        "core.AFMEntity",
        on_delete=models.CASCADE,
        related_name="score_data",
        primary_key=True,
    )

    # === Computed score components ===

    total_score = models.FloatField(
        default=0.0, db_index=True, help_text="Final weighted score (0-100)"
    )

    # Existing features
    frequency_score = models.FloatField(
        default=0.0, help_text="Normalized appearance frequency score (0-1)"
    )
    amount_score = models.FloatField(
        default=0.0, help_text="Normalized total amount score (0-1)"
    )
    organization_score = models.FloatField(
        default=0.0, help_text="Normalized unique organization score (0-1)"
    )

    # New features
    direct_assignment_count_score = models.FloatField(
        default=0.0, help_text="Normalized direct assignment count score (0-1)"
    )
    direct_assignment_percentage_score = models.FloatField(
        default=0.0, help_text="Normalized direct assignment percentage score (0-1)"
    )

    # === Raw metrics used for scoring ===

    # Existing metrics
    total_appearances = models.PositiveIntegerField(
        default=0, help_text="Total decision appearances"
    )
    total_amount = models.DecimalField(
        max_digits=20,
        decimal_places=2,
        default=0.00,
        help_text="Sum of all associated transaction amounts",
    )
    unique_organizations = models.PositiveIntegerField(
        default=0, help_text="Count of unique organizations"
    )

    # New metrics
    direct_assignment_count = models.PositiveIntegerField(
        default=0, help_text="Number of times entity appeared in direct assignments"
    )
    direct_assignment_percentage = models.FloatField(
        default=0.0,
        help_text="Percentage of appearances that are direct assignments (0-100)",
    )

    # === Normalization metadata ===

    normalization_stats = models.JSONField(
        default=dict,
        blank=True,
        help_text="Statistics used for normalization (for transparency/debugging)",
    )

    # === Queue status ===

    is_eligible = models.BooleanField(
        default=False, db_index=True, help_text="Meets minimum thresholds for fetching"
    )
    fetch_priority = models.IntegerField(
        default=0, db_index=True, help_text="Priority rank (1 = highest priority)"
    )

    # === Metadata ===

    config_used = models.ForeignKey(
        AFMScoringConfig,
        on_delete=models.SET_NULL,
        null=True,
        help_text="Configuration used to compute this score",
    )
    scored_at = models.DateTimeField(
        auto_now=True, help_text="When this score was last computed"
    )

    class Meta:
        verbose_name = "AFM Entity Score"
        verbose_name_plural = "AFM Entity Scores"
        ordering = ["-total_score"]
        indexes = [
            models.Index(fields=["-total_score"]),
            models.Index(fields=["is_eligible", "-total_score"]),
            models.Index(fields=["fetch_priority"]),
            models.Index(fields=["direct_assignment_count"]),
            models.Index(fields=["direct_assignment_percentage"]),
        ]

    def __str__(self):
        return (
            f"{self.entity.afm}: {self.total_score:.2f} (Rank #{self.fetch_priority})"
        )

    def get_score_breakdown(self) -> dict:
        """
        Get detailed breakdown of score components.

        Returns:
            Dict with raw metrics, normalized scores, and weighted contributions
        """
        config = self.config_used
        if not config:
            return {}

        return {
            "total_score": self.total_score,
            "components": {
                "frequency": {
                    "raw_value": self.total_appearances,
                    "normalized_score": self.frequency_score,
                    "weight": config.frequency_weight,
                    "weighted_contribution": self.frequency_score
                    * config.frequency_weight
                    * 100,
                },
                "amount": {
                    "raw_value": float(self.total_amount),
                    "normalized_score": self.amount_score,
                    "weight": config.amount_weight,
                    "weighted_contribution": self.amount_score
                    * config.amount_weight
                    * 100,
                },
                "organization": {
                    "raw_value": self.unique_organizations,
                    "normalized_score": self.organization_score,
                    "weight": config.organization_weight,
                    "weighted_contribution": self.organization_score
                    * config.organization_weight
                    * 100,
                },
                "direct_assignment_count": {
                    "raw_value": self.direct_assignment_count,
                    "normalized_score": self.direct_assignment_count_score,
                    "weight": config.direct_assignment_count_weight,
                    "weighted_contribution": self.direct_assignment_count_score
                    * config.direct_assignment_count_weight
                    * 100,
                },
                "direct_assignment_percentage": {
                    "raw_value": self.direct_assignment_percentage,
                    "normalized_score": self.direct_assignment_percentage_score,
                    "weight": config.direct_assignment_percentage_weight,
                    "weighted_contribution": self.direct_assignment_percentage_score
                    * config.direct_assignment_percentage_weight
                    * 100,
                },
            },
            "normalization_stats": self.normalization_stats,
        }
