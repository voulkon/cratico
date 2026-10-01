"""
Model for tracking amount-correction batch jobs.

The batch correction can take a long time (it may download + extract the
document for every candidate), so it runs on a Celery worker and persists
progress + per-decision results here for the admin UI to poll.

``mode`` selects which data-quality detector(s) the job runs — see
``core.services.data_quality``.  ``decimal_shift`` (default) is the historical
behaviour: the cents-based ×100/÷100 correction.  ``non_monetary`` runs the
DB-only AFM/KAE guard instead (no document read), and ``both`` runs every
registered detector.  Adding a detector therefore needs no job-model change.
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class CorrectionJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class CorrectionJobMode(models.TextChoices):
    """Which detector(s) a job runs.  Mirrors ``data_quality.MODES``."""

    DECIMAL_SHIFT = "decimal_shift", "Decimal separator shift (×100 / ÷100)"
    NON_MONETARY = "non_monetary", "Non-monetary value as amount (AFM/KAE)"
    BOTH = "both", "Every registered detector"


class AmountCorrectionJob(models.Model):
    """Tracks a single batch amount-correction run."""

    job_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="amount_correction_jobs",
    )

    # ── Configuration ──────────────────────────────────────────────
    #: which detector(s) to run — see ``core.services.data_quality``
    mode = models.CharField(
        max_length=20,
        choices=CorrectionJobMode.choices,
        default=CorrectionJobMode.DECIMAL_SHIFT,
        db_index=True,
    )
    #: Lower bound.  For the decimal-shift detector it filters the decision's
    #: computed total; for the non-monetary detector the individual field value.
    threshold = models.DecimalField(max_digits=15, decimal_places=2, default=100000)
    #: Optional upper bound (same target as ``threshold``) — lets an operator
    #: scan a band, e.g. only amounts between €100k and €1M.
    max_amount = models.DecimalField(
        max_digits=15, decimal_places=2, null=True, blank=True
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    limit = models.PositiveIntegerField(null=True, blank=True)
    dry_run = models.BooleanField(default=False)
    read_if_missing = models.BooleanField(default=True)
    imported_since = models.DateTimeField(
        null=True,
        blank=True,
        help_text=(
            "Only process decisions imported (Decision.created_at) at/after "
            "this point — scopes the job to recent imports instead of the "
            "whole historical backlog."
        ),
    )

    # ── Status / progress ─────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=CorrectionJobStatus.choices,
        default=CorrectionJobStatus.PENDING,
        db_index=True,
    )
    celery_task_id = models.CharField(max_length=255, null=True, blank=True)

    total_candidates = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    corrected = models.PositiveIntegerField(default=0)
    consistent = models.PositiveIntegerField(default=0)
    no_text = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)
    #: Decisions whose value could not be repaired and was flagged instead
    #: (non-monetary value recorded as an amount).
    flagged = models.PositiveIntegerField(default=0)

    # ── Timing ────────────────────────────────────────────────────
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"AmountCorrectionJob {self.job_id} ({self.status})"

    @property
    def progress_percentage(self):
        if not self.total_candidates:
            return 0
        return round((self.processed_count / self.total_candidates) * 100, 1)

    @property
    def is_active(self):
        return self.status in (
            CorrectionJobStatus.PENDING,
            CorrectionJobStatus.RUNNING,
        )

    def mark_started(self, celery_task_id=None):
        self.status = CorrectionJobStatus.RUNNING
        self.started_at = timezone.now()
        if celery_task_id:
            self.celery_task_id = celery_task_id
        self.save(update_fields=["status", "started_at", "celery_task_id", "updated_at"])

    def mark_completed(self):
        self.status = CorrectionJobStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def mark_failed(self, error_message):
        self.status = CorrectionJobStatus.FAILED
        self.last_error = str(error_message)[:1000]
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "last_error", "completed_at", "updated_at"])

    def finalize_if_done(self):
        """
        If all per-decision results are settled, mark completed and invalidate
        caches (when not a dry-run and something was corrected).  Called
        on-demand when the admin polls job status.
        """
        if self.status != CorrectionJobStatus.RUNNING:
            return
        if self.total_candidates and self.processed_count >= self.total_candidates:
            self.mark_completed()
            if (self.corrected or self.flagged) and not self.dry_run:
                from core.services.response_cache_service import response_cache
                response_cache.invalidate_prefix("top_")


class AmountCorrectionJobResult(models.Model):
    """Per-decision outcome for a batch amount-correction job."""

    job = models.ForeignKey(
        AmountCorrectionJob, on_delete=models.CASCADE, related_name="results"
    )
    decision = models.ForeignKey(
        "core.Decision", on_delete=models.CASCADE,
        related_name="correction_job_results",
    )

    status = models.CharField(max_length=30)  # corrected / consistent / etc.
    reason = models.CharField(max_length=255, blank=True, default="")
    group_correction = models.BooleanField(default=False)

    # [{source_field, db_amount, corrected_to, clone_factor}, ...]
    corrections = models.JSONField(default=list, blank=True)
    # [{detector, kind, reason, field_id, source_field, recorded, note, ...}, ...]
    # Values that could NOT be repaired (the real amount is unknown) and were
    # flagged instead — rendered alongside the corrections in the job page.
    flagged = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["job", "status"])]

    def __str__(self):
        return f"{self.decision.ada}: {self.status}"
