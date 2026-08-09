"""
Models for tracking Diavgeia feedback-reporting batch jobs.

When the amount-correction pipeline detects wrong amounts
(``DecisionAmountField.verified_amount``), those decisions are candidates to
be reported to the Diavgeia admins via the feedback API
(``POST /luminapi/api/feedback/new``).  Reporting is a network call per
decision, so it runs on a Celery worker and persists progress + per-decision
outcomes here for the admin UI to poll — mirroring ``AmountCorrectionJob``.
"""

import uuid

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class FeedbackJobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class DiavgeiaFeedbackJob(models.Model):
    """Tracks a single batch feedback-reporting run."""

    job_id = models.UUIDField(
        default=uuid.uuid4, unique=True, editable=False, db_index=True
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="diavgeia_feedback_jobs",
    )

    # ── Configuration ──────────────────────────────────────────────
    reporter_email = models.EmailField(
        blank=True,
        default="",
        help_text=(
            "Email passed to the Diavgeia feedback API (reporterEmail). "
            "Blank uses the configured default."
        ),
    )
    feedback_errors = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Diavgeia feedback error codes sent as feedBackErrors "
            "(e.g. ['FE_1'])."
        ),
    )
    limit = models.PositiveIntegerField(null=True, blank=True)
    dry_run = models.BooleanField(
        default=False,
        help_text="If True, only report what WOULD be sent (no API calls).",
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)

    # ── Status / progress ─────────────────────────────────────────
    status = models.CharField(
        max_length=20,
        choices=FeedbackJobStatus.choices,
        default=FeedbackJobStatus.PENDING,
        db_index=True,
    )
    celery_task_id = models.CharField(max_length=255, null=True, blank=True)

    total_candidates = models.PositiveIntegerField(default=0)
    processed_count = models.PositiveIntegerField(default=0)
    reported = models.PositiveIntegerField(default=0)
    already_reported = models.PositiveIntegerField(default=0)
    skipped = models.PositiveIntegerField(default=0)
    errors = models.PositiveIntegerField(default=0)

    # ── Timing ────────────────────────────────────────────────────
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"DiavgeiaFeedbackJob {self.job_id} ({self.status})"

    @property
    def progress_percentage(self):
        if not self.total_candidates:
            return 0
        return round((self.processed_count / self.total_candidates) * 100, 1)

    @property
    def is_active(self):
        return self.status in (
            FeedbackJobStatus.PENDING,
            FeedbackJobStatus.RUNNING,
        )

    def mark_started(self, celery_task_id=None):
        self.status = FeedbackJobStatus.RUNNING
        self.started_at = timezone.now()
        if celery_task_id:
            self.celery_task_id = celery_task_id
        self.save(
            update_fields=["status", "started_at", "celery_task_id", "updated_at"]
        )

    def mark_completed(self):
        self.status = FeedbackJobStatus.COMPLETED
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def mark_failed(self, error_message):
        self.status = FeedbackJobStatus.FAILED
        self.last_error = str(error_message)[:1000]
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "last_error", "completed_at", "updated_at"])

    def finalize_if_done(self):
        """If all per-decision results are settled, mark completed."""
        if self.status != FeedbackJobStatus.RUNNING:
            return
        if self.total_candidates and self.processed_count >= self.total_candidates:
            self.mark_completed()


class DiavgeiaFeedbackJobResult(models.Model):
    """Per-decision outcome for a feedback-reporting job."""

    job = models.ForeignKey(
        DiavgeiaFeedbackJob, on_delete=models.CASCADE, related_name="results"
    )
    decision = models.ForeignKey(
        "core.Decision",
        on_delete=models.CASCADE,
        related_name="feedback_job_results",
    )

    status = models.CharField(max_length=30)  # reported / already_reported / error
    reason = models.CharField(max_length=255, blank=True, default="")
    reference = models.CharField(max_length=64, blank=True, default="")
    response = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["job", "status"])]

    def __str__(self):
        return f"{self.decision.ada}: {self.status}"
