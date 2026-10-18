"""
DecisionOneLiner — one *attempt* at generating a per-decision one-liner.

Every attempt is a stored row with its circumstances as plain readable
columns (via ``OneLinerConfig``), judgeable and comparable without decoding
anything.  The cache key IS the column tuple (decision, extraction, config,
attempt) — the DB constraint enforces it.

Semantics:
- First generation → attempt 1.  Every deliberate identical re-attempt
  (failed-then-retry, user "Regenerate") → a NEW row with ``attempt = max+1``;
  prior rows are kept as history.
- Internal Celery retries must overwrite the same row in place (retry noise
  must not mint attempts) — callers adopt rows via
  ``context.metadata["adopt_one_liner_rows"]``.
- Default one-liner for display = the latest-COMPLETED row across all
  lineages (a newer FAILED attempt never hides an older COMPLETED one).
"""

from django.db import models, transaction
from django.utils.translation import gettext_lazy as _

from core.models.pipeline import BilledTo


class OneLinerStatus(models.TextChoices):
    PENDING = "PENDING", _("Pending")
    RUNNING = "RUNNING", _("Running")
    COMPLETED = "COMPLETED", _("Completed")
    FAILED = "FAILED", _("Failed")


class DecisionOneLiner(models.Model):
    """A single one-liner generation attempt for a decision."""

    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="one_liners",
    )
    # Provenance: the exact extraction snapshot the text was generated from.
    # NULL = subject-fallback run (no document text existed).
    extraction = models.ForeignKey(
        "core.DocumentExtraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="one_liners",
    )
    config = models.ForeignKey(
        "core.OneLinerConfig",
        on_delete=models.PROTECT,
        related_name="attempts",
    )
    attempt = models.PositiveIntegerField(
        help_text=_("1-based, scoped per (decision, extraction, config) lineage"),
    )

    # Result content
    one_liner = models.TextField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=OneLinerStatus.choices,
        default=OneLinerStatus.PENDING,
        db_index=True,
    )
    error_message = models.TextField(null=True, blank=True)

    # Metrics (null for cache hits — they cost nothing)
    input_tokens = models.IntegerField(null=True, blank=True)
    output_tokens = models.IntegerField(null=True, blank=True)
    cost_usd = models.DecimalField(
        max_digits=10, decimal_places=6, null=True, blank=True
    )
    latency_ms = models.IntegerField(null=True, blank=True)
    billed_to = models.CharField(
        max_length=10,
        choices=BilledTo.choices,
        default=BilledTo.SYSTEM,
        help_text=_("Whose API key paid for this attempt (null-cost hits keep the fill's value)"),
    )

    pipeline_run = models.ForeignKey(
        "core.PipelineRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="one_liner_attempts",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("Decision One Liner")
        verbose_name_plural = _("Decision One Liners")
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["decision", "extraction", "config", "attempt"],
                nulls_distinct=False,
                name="unique_one_liner_attempt",
            ),
        ]
        indexes = [
            models.Index(fields=["decision", "status"]),
            models.Index(fields=["decision", "config", "attempt"]),
        ]

    def __str__(self):
        return (
            f"{self.decision_id} · {self.config_id} · attempt {self.attempt} "
            f"({self.status})"
        )

    # ------------------------------------------------------------------
    # Lineage helpers
    # ------------------------------------------------------------------
    @classmethod
    def new_attempt(cls, decision, config, extraction_id=None, status=None):
        """Create the next attempt row for a (decision, extraction, config)
        lineage: ``attempt = max + 1``."""
        last = (
            cls.objects.filter(
                decision=decision,
                extraction_id=extraction_id,
                config=config,
            )
            .aggregate(models.Max("attempt"))
            ["attempt__max"]
            or 0
        )
        return cls.objects.create(
            decision=decision,
            config=config,
            extraction_id=extraction_id,
            attempt=last + 1,
            status=status or OneLinerStatus.PENDING,
        )

    @classmethod
    def claim_pending(cls, decision, config, extraction_id=None):
        """Atomically claim (PENDING → RUNNING) the oldest leftover PENDING
        row of this lineage.  Returns the claimed row or ``None``.

        A concurrent worker that loses the claim sees ``None`` and mints its
        own attempt instead of blocking (batch runs must not wait on each
        other)."""
        with transaction.atomic():
            row = (
                cls.objects.select_for_update(skip_locked=True)
                .filter(
                    decision=decision,
                    extraction_id=extraction_id,
                    config=config,
                    status=OneLinerStatus.PENDING,
                )
                .order_by("attempt")
                .first()
            )
            if row is None:
                return None
            row.status = OneLinerStatus.RUNNING
            row.save(update_fields=["status", "updated_at"])
            return row

    @classmethod
    def latest_completed(cls, decision, config, extraction_id=None):
        """The max-attempt COMPLETED row of this lineage (cache hit), or
        ``None``."""
        return (
            cls.objects.filter(
                decision=decision,
                extraction_id=extraction_id,
                config=config,
                status=OneLinerStatus.COMPLETED,
                one_liner__isnull=False,
            )
            .exclude(one_liner__exact="")
            .order_by("-attempt")
            .first()
        )

    @classmethod
    def default_for_decision(cls, decision_id):
        """Latest COMPLETED attempt across all lineages — the display value."""
        return (
            cls.objects.filter(
                decision_id=decision_id,
                status=OneLinerStatus.COMPLETED,
                one_liner__isnull=False,
            )
            .exclude(one_liner__exact="")
            .order_by("-completed_at", "-attempt", "-id")
            .first()
        )
