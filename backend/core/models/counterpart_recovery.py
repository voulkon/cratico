"""
Counterpart recovery history.

When Diavgeia records the issuing organization's own VAT number as the
counterpart (``self-as-counterpart``), the recovery pipeline reads the
document text and rewrites the *current* ``DecisionEntityRelationship`` row to
the real counterpart.  That rewrite is destructive: the AFM the relationship
used to point at is gone from the live row.

This model is the ONLY place that history is preserved.  One row per attempt,
append-only:

* ``original_*`` snapshot the relationship's pre-change state (AFM, entity,
  role, path, source field, raw context, confidence);
* ``chosen_afm`` / ``confidence`` / ``candidate_afms`` record how the new
  counterpart was picked;
* ``span_start`` / ``span_end`` / ``span_text`` copy the evidence into this
  row so it survives a later OCR overwrite and a ``SET_NULL`` span deletion;
* AI attempts carry provider/model and cost columns.

Retries append another row; the live relationship always reflects the latest
applied attempt.
"""

from core.models.decisions import Decision
from django.db import models
from django.utils.translation import gettext_lazy as _


class RecoveryMethod(models.TextChoices):
    REGEX_OCR = "REGEX_OCR", _("Regex over OCR text")
    AI_TEXT = "AI_TEXT", _("AI text resolver")
    MANUAL = "MANUAL", _("Manual")


class RecoveryStatus(models.TextChoices):
    APPLIED = "APPLIED", _("Applied")
    NEEDS_REVIEW = "NEEDS_REVIEW", _("Needs review")
    NO_CANDIDATE = "NO_CANDIDATE", _("No candidate")
    REJECTED = "REJECTED", _("Rejected")
    FAILED = "FAILED", _("Failed")


class CounterpartRecoveryAttempt(models.Model):
    """One auditable attempt to recover a decision's real counterpart."""

    decision = models.ForeignKey(
        Decision,
        on_delete=models.CASCADE,
        related_name="counterpart_recovery_attempts",
    )
    extraction = models.ForeignKey(
        "core.DocumentExtraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="counterpart_recovery_attempts",
        help_text=_("Extraction whose text was used for the attempt."),
    )

    method = models.CharField(max_length=20, choices=RecoveryMethod.choices)
    status = models.CharField(
        max_length=20, choices=RecoveryStatus.choices, db_index=True
    )
    provider = models.CharField(max_length=50, null=True, blank=True)
    model = models.CharField(max_length=200, null=True, blank=True)

    # Candidate scoring — one entry per evaluated AFM with its signals.
    candidate_afms = models.JSONField(default=list, blank=True)
    chosen_afm = models.CharField(max_length=20, null=True, blank=True)
    confidence = models.FloatField(null=True, blank=True)

    # Pre-change snapshot of the live relationship row.
    original_relationship = models.ForeignKey(
        "core.DecisionEntityRelationship",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovery_attempts_as_original",
    )
    original_afm = models.CharField(max_length=20, null=True, blank=True)
    original_entity_id = models.PositiveIntegerField(null=True, blank=True)
    original_entity_name = models.TextField(null=True, blank=True)
    original_role = models.CharField(max_length=30, null=True, blank=True)
    original_parent_key_path = models.CharField(max_length=200, null=True, blank=True)
    original_source_field_name = models.CharField(
        max_length=100, null=True, blank=True
    )
    original_raw_context = models.JSONField(null=True, blank=True)
    previous_confidence = models.FloatField(null=True, blank=True)

    # The live relationship row after the attempt (same row on the in-place
    # path).  The only direction of the link, so there is no circular FK.
    new_relationship = models.ForeignKey(
        "core.DecisionEntityRelationship",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recovery_attempts_as_new",
    )

    # Evidence snapshot (survives text re-extraction / span deletion).
    span_start = models.IntegerField(null=True, blank=True)
    span_end = models.IntegerField(null=True, blank=True)
    span_text = models.TextField(null=True, blank=True)
    evidence = models.JSONField(default=dict, blank=True)

    # OCR provenance at attempt time.
    ocr_provider = models.CharField(max_length=50, null=True, blank=True)
    ocr_confidence = models.FloatField(null=True, blank=True)

    # AI accounting (null for regex attempts).
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)

    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Counterpart Recovery Attempt")
        verbose_name_plural = _("Counterpart Recovery Attempts")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["decision", "-created_at"]),
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        return (
            f"{self.decision.ada}: {self.original_afm} → "
            f"{self.chosen_afm or '—'} [{self.status}]"
        )
