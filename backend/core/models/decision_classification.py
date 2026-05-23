from django.db import models
from django.db.models import Q


class DirectAssignmentDetectionMethod(models.TextChoices):
    """How the direct assignment was detected"""

    METADATA = "METADATA", "Metadata (Type & Amount)"
    TEXT = "TEXT", "Text Content"
    BOTH = "BOTH", "Both Methods"
    NONE = "NONE", "Not Detected"


class DecisionClassification(models.Model):
    """One-to-one storage for all classification results"""

    decision = models.OneToOneField(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="classification",
        primary_key=True,
    )

    # Direct Assignment Classification
    is_direct_assignment = models.BooleanField(
        default=False, db_index=True, help_text="Δ.1 decision below €37,200 threshold"
    )

    # Detection method tracking
    detection_method = models.CharField(
        max_length=20,
        choices=DirectAssignmentDetectionMethod.choices,
        default=DirectAssignmentDetectionMethod.NONE,
        db_index=True,
        help_text="How the direct assignment was detected",
    )

    # Metadata
    classifier_version = models.CharField(max_length=50, default="v2.0")
    classified_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            # Covering index for common filtering
            models.Index(
                fields=["is_direct_assignment", "classified_at"],
                include=["decision_id"],
                name="direct_assignment_covering_idx",
            ),
            # Partial index for unclassified decisions
            models.Index(
                fields=["decision_id"],
                condition=Q(is_direct_assignment=False)
                & Q(classified_at__isnull=False),
                name="needs_reclassification_idx",
            ),
        ]
