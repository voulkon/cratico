"""
Model for tracking AFM scoring batch jobs.

Allows administrators to launch, monitor, and manage scoring tasks
for large datasets without keeping terminals open.
"""

from enum import Enum

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class ScoringJobStatus(str, Enum):
    """Status of scoring job"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AFMScoringJob(models.Model):
    """
    Tracks an AFM scoring batch job.

    Supports:
    - Processing all AFM entities
    - Re-scoring with new configuration
    - Batch size control
    - Progress tracking
    - Pause/resume/cancel operations
    """

    # Job identification
    job_id = models.CharField(max_length=100, unique=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="afm_scoring_jobs"
    )

    # Job configuration
    config = models.ForeignKey(
        "core.AFMScoringConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="scoring_jobs",
        help_text="Scoring configuration to use",
    )

    batch_size = models.PositiveIntegerField(
        default=1000, help_text="Number of entities to process per batch"
    )

    exclude_already_fetched = models.BooleanField(
        default=False, help_text="Exclude entities with successful GEMI data"
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in ScoringJobStatus],
        default=ScoringJobStatus.PENDING.value,
        db_index=True,
    )

    celery_task_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="Celery task ID for tracking"
    )

    # Progress tracking
    total_entities = models.PositiveIntegerField(
        default=0, help_text="Total entities to process"
    )

    processed_count = models.PositiveIntegerField(
        default=0, help_text="Entities processed so far"
    )

    scored_count = models.PositiveIntegerField(
        default=0, help_text="Entities successfully scored"
    )

    eligible_count = models.PositiveIntegerField(
        default=0, help_text="Entities eligible for fetch"
    )

    ineligible_count = models.PositiveIntegerField(
        default=0, help_text="Entities not eligible for fetch"
    )

    error_count = models.PositiveIntegerField(default=0, help_text="Errors encountered")

    # Timing
    started_at = models.DateTimeField(
        null=True, blank=True, help_text="When processing started"
    )

    completed_at = models.DateTimeField(
        null=True, blank=True, help_text="When processing completed"
    )

    estimated_completion = models.DateTimeField(
        null=True, blank=True, help_text="Estimated completion time"
    )

    # Error handling
    last_error = models.TextField(
        null=True, blank=True, help_text="Last error message if failed"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "AFM Scoring Job"
        verbose_name_plural = "AFM Scoring Jobs"
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["created_by", "status"]),
        ]

    def __str__(self):
        return f"AFM Scoring Job {self.job_id} ({self.status})"

    @property
    def progress_percentage(self):
        """Calculate progress percentage"""
        if self.total_entities == 0:
            return 0
        return round((self.processed_count / self.total_entities) * 100, 2)

    @property
    def is_active(self):
        """Check if job is actively processing"""
        return self.status in [
            ScoringJobStatus.PENDING.value,
            ScoringJobStatus.RUNNING.value,
        ]

    @property
    def is_paused(self):
        """Check if job is paused"""
        return self.status == ScoringJobStatus.PAUSED.value

    @property
    def duration_seconds(self):
        """Calculate duration in seconds"""
        if not self.started_at:
            return 0

        end_time = self.completed_at or timezone.now()
        return (end_time - self.started_at).total_seconds()

    @property
    def entities_per_second(self):
        """Calculate processing rate"""
        duration = self.duration_seconds
        if duration == 0:
            return 0
        return round(self.processed_count / duration, 2)

    def get_estimated_time_remaining(self):
        """Estimate time remaining based on current rate"""
        if self.processed_count == 0 or self.status != ScoringJobStatus.RUNNING.value:
            return None

        remaining = self.total_entities - self.processed_count
        rate = self.entities_per_second

        if rate == 0:
            return None

        seconds_remaining = remaining / rate
        return timezone.now() + timezone.timedelta(seconds=seconds_remaining)

    def update_progress(self, processed, scored, eligible, ineligible, errors):
        """Update progress counters"""
        self.processed_count = processed
        self.scored_count = scored
        self.eligible_count = eligible
        self.ineligible_count = ineligible
        self.error_count = errors

        # Update estimated completion
        self.estimated_completion = self.get_estimated_time_remaining()

        self.save(
            update_fields=[
                "processed_count",
                "scored_count",
                "eligible_count",
                "ineligible_count",
                "error_count",
                "estimated_completion",
                "updated_at",
            ]
        )

    def mark_started(self, celery_task_id=None):
        """Mark job as started"""
        self.status = ScoringJobStatus.RUNNING.value
        self.started_at = timezone.now()
        if celery_task_id:
            self.celery_task_id = celery_task_id
        self.save(
            update_fields=["status", "started_at", "celery_task_id", "updated_at"]
        )

    def mark_completed(self):
        """Mark job as completed"""
        self.status = ScoringJobStatus.COMPLETED.value
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def mark_failed(self, error_message):
        """Mark job as failed"""
        self.status = ScoringJobStatus.FAILED.value
        self.last_error = str(error_message)[:1000]  # Truncate long errors
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "last_error", "completed_at", "updated_at"])

    def pause(self):
        """Pause the job"""
        if self.status == ScoringJobStatus.RUNNING.value:
            self.status = ScoringJobStatus.PAUSED.value
            self.save(update_fields=["status", "updated_at"])

    def resume(self):
        """Resume a paused job"""
        if self.status == ScoringJobStatus.PAUSED.value:
            self.status = ScoringJobStatus.RUNNING.value
            self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        """Cancel the job"""
        if self.status in [
            ScoringJobStatus.PENDING.value,
            ScoringJobStatus.RUNNING.value,
            ScoringJobStatus.PAUSED.value,
        ]:
            self.status = ScoringJobStatus.CANCELLED.value
            self.completed_at = timezone.now()
            self.save(update_fields=["status", "completed_at", "updated_at"])


class AFMScoringJobLog(models.Model):
    """Log entries for scoring jobs"""

    job = models.ForeignKey(
        AFMScoringJob, on_delete=models.CASCADE, related_name="logs"
    )

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=20, default="INFO")
    message = models.TextField()

    # Optional context
    batch_number = models.PositiveIntegerField(null=True, blank=True)
    entities_in_batch = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        verbose_name = "AFM Scoring Job Log"
        verbose_name_plural = "AFM Scoring Job Logs"
        indexes = [
            models.Index(fields=["job", "timestamp"]),
        ]

    def __str__(self):
        return f"[{self.timestamp}] {self.level}: {self.message[:50]}"
