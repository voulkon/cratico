"""
Model for tracking classification batch jobs.

Allows administrators to launch, monitor, and manage classification tasks
for large datasets without keeping terminals open.
"""

from enum import Enum

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

User = get_user_model()


class JobStatus(str, Enum):
    """Status of classification job"""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ClassificationJob(models.Model):
    """
    Tracks a classification batch job for decisions.

    Supports:
    - Processing specific date ranges
    - Processing unclassified decisions
    - Re-classifying with new algorithm versions
    - Batch size control
    - Progress tracking
    - Pause/resume/cancel operations
    """

    # Job identification
    job_id = models.CharField(max_length=100, unique=True, db_index=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="classification_jobs"
    )

    # Job configuration
    PROCESSING_MODE_CHOICES = [
        ("unclassified", "Unclassified Decisions"),
        ("date_range", "Date Range"),
        ("reclassify", "Re-classify (Algorithm Update)"),
        ("outdated", "Outdated Classifier Version"),
        ("all", "All Decisions"),
    ]

    processing_mode = models.CharField(
        max_length=20,
        choices=PROCESSING_MODE_CHOICES,
        default="unclassified",
        help_text="Which decisions to classify",
    )

    start_date = models.DateField(
        null=True, blank=True, help_text="Start date for date_range mode"
    )

    end_date = models.DateField(
        null=True, blank=True, help_text="End date for date_range mode"
    )

    batch_size = models.PositiveIntegerField(
        default=1000, help_text="Number of decisions to process per batch"
    )

    max_decisions = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Maximum number of decisions to process (leave empty for unlimited)",
    )

    reclassify = models.BooleanField(
        default=False, help_text="Re-classify even if already classified"
    )

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=[(s.value, s.name) for s in JobStatus],
        default=JobStatus.PENDING.value,
        db_index=True,
    )

    celery_task_id = models.CharField(
        max_length=255, null=True, blank=True, help_text="Celery task ID for tracking"
    )

    # Progress tracking
    total_decisions = models.PositiveIntegerField(
        default=0, help_text="Total decisions to process"
    )

    processed_count = models.PositiveIntegerField(
        default=0, help_text="Decisions processed so far"
    )

    direct_assignments_found = models.PositiveIntegerField(
        default=0, help_text="Direct assignments identified"
    )

    non_direct_assignments = models.PositiveIntegerField(
        default=0, help_text="Non-direct assignments"
    )

    created_count = models.PositiveIntegerField(
        default=0, help_text="New classifications created"
    )

    updated_count = models.PositiveIntegerField(
        default=0, help_text="Existing classifications updated"
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
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["created_by", "status"]),
        ]

    def __str__(self):
        return f"Classification Job {self.job_id} ({self.status})"

    @property
    def progress_percentage(self):
        """Calculate progress percentage"""
        if self.total_decisions == 0:
            return 0
        return round((self.processed_count / self.total_decisions) * 100, 2)

    @property
    def is_active(self):
        """Check if job is actively processing"""
        return self.status in [JobStatus.PENDING.value, JobStatus.RUNNING.value]

    @property
    def is_paused(self):
        """Check if job is paused"""
        return self.status == JobStatus.PAUSED.value

    @property
    def duration_seconds(self):
        """Calculate duration in seconds"""
        if not self.started_at:
            return 0

        end_time = self.completed_at or timezone.now()
        return (end_time - self.started_at).total_seconds()

    @property
    def decisions_per_second(self):
        """Calculate processing rate"""
        duration = self.duration_seconds
        if duration == 0:
            return 0
        return round(self.processed_count / duration, 2)

    def get_estimated_time_remaining(self):
        """Estimate time remaining based on current rate"""
        if self.processed_count == 0 or self.status != JobStatus.RUNNING.value:
            return None

        remaining = self.total_decisions - self.processed_count
        rate = self.decisions_per_second

        if rate == 0:
            return None

        seconds_remaining = remaining / rate
        return timezone.now() + timezone.timedelta(seconds=seconds_remaining)

    def update_progress(
        self, processed, direct_assignments, non_direct, created, updated, errors
    ):
        """Update progress counters"""
        self.processed_count = processed
        self.direct_assignments_found = direct_assignments
        self.non_direct_assignments = non_direct
        self.created_count = created
        self.updated_count = updated
        self.error_count = errors

        # Update estimated completion
        self.estimated_completion = self.get_estimated_time_remaining()

        self.save(
            update_fields=[
                "processed_count",
                "direct_assignments_found",
                "non_direct_assignments",
                "created_count",
                "updated_count",
                "error_count",
                "estimated_completion",
                "updated_at",
            ]
        )

    def mark_started(self, celery_task_id=None):
        """Mark job as started"""
        self.status = JobStatus.RUNNING.value
        self.started_at = timezone.now()
        if celery_task_id:
            self.celery_task_id = celery_task_id
        self.save(
            update_fields=["status", "started_at", "celery_task_id", "updated_at"]
        )

    def mark_completed(self):
        """Mark job as completed"""
        self.status = JobStatus.COMPLETED.value
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "completed_at", "updated_at"])

    def mark_failed(self, error_message):
        """Mark job as failed"""
        self.status = JobStatus.FAILED.value
        self.last_error = str(error_message)[:1000]  # Truncate long errors
        self.completed_at = timezone.now()
        self.save(update_fields=["status", "last_error", "completed_at", "updated_at"])

    def pause(self):
        """Pause the job"""
        if self.status == JobStatus.RUNNING.value:
            self.status = JobStatus.PAUSED.value
            self.save(update_fields=["status", "updated_at"])

    def resume(self):
        """Resume a paused job"""
        if self.status == JobStatus.PAUSED.value:
            self.status = JobStatus.RUNNING.value
            self.save(update_fields=["status", "updated_at"])

    def cancel(self):
        """Cancel the job"""
        if self.status in [
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
        ]:
            self.status = JobStatus.CANCELLED.value
            self.completed_at = timezone.now()
            self.save(update_fields=["status", "completed_at", "updated_at"])


class ClassificationJobLog(models.Model):
    """Log entries for classification jobs"""

    job = models.ForeignKey(
        ClassificationJob, on_delete=models.CASCADE, related_name="logs"
    )

    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=20, default="INFO")
    message = models.TextField()

    # Optional context
    batch_number = models.PositiveIntegerField(null=True, blank=True)
    decisions_in_batch = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["job", "timestamp"]),
        ]

    def __str__(self):
        return f"[{self.timestamp}] {self.level}: {self.message[:50]}"
