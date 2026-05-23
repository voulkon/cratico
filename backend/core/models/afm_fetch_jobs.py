"""
Simple tracking table to prevent duplicate AFM fetch tasks from being queued.
"""

from django.db import models
from django.utils import timezone


class AFMFetchJob(models.Model):
    """
    Tracks in-flight AFM company data fetch tasks.
    Prevents duplicate tasks from being queued for the same AFM.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        IN_PROGRESS = "in_progress", "In Progress"
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    afm = models.CharField(max_length=9, db_index=True)
    task_id = models.CharField(max_length=255, db_index=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Track which batch/parent task triggered this
    parent_task_id = models.CharField(max_length=255, null=True, blank=True)
    parent_ada = models.CharField(max_length=100, null=True, blank=True)

    error_message = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "afm_fetch_jobs"
        indexes = [
            models.Index(fields=["afm", "status"]),
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["afm"],
                condition=models.Q(status__in=["pending", "in_progress"]),
                name="unique_active_afm_fetch",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"AFM {self.afm} - {self.status} ({self.task_id})"

    @classmethod
    def is_afm_being_fetched(cls, afm: str) -> bool:
        """
        Check if an AFM is currently being fetched.
        Returns True if there's a pending or in-progress job.
        """
        return cls.objects.filter(
            afm=afm, status__in=[cls.Status.PENDING, cls.Status.IN_PROGRESS]
        ).exists()

    @classmethod
    def try_create_job(
        cls, afm: str, task_id: str, parent_task_id: str = None, parent_ada: str = None
    ):
        """
        Atomically try to create a job for this AFM.
        Returns (job, created) tuple.
        If another job is already active, returns (None, False).
        Uses database constraint to prevent race conditions.
        """
        from django.db import IntegrityError

        try:
            job = cls.objects.create(
                afm=afm,
                task_id=task_id,
                parent_task_id=parent_task_id,
                parent_ada=parent_ada,
                status=cls.Status.PENDING,
            )
            return (job, True)
        except IntegrityError:
            # Another task already created a job for this AFM
            return (None, False)

    @classmethod
    def mark_in_progress(cls, task_id: str):
        """Mark job(s) for this task as in progress."""
        cls.objects.filter(task_id=task_id, status=cls.Status.PENDING).update(
            status=cls.Status.IN_PROGRESS, updated_at=timezone.now()
        )

    @classmethod
    def mark_completed(cls, afm: str, task_id: str, success: bool, error: str = None):
        """Mark a job as completed."""
        cls.objects.filter(afm=afm, task_id=task_id).update(
            status=cls.Status.SUCCESS if success else cls.Status.FAILED,
            completed_at=timezone.now(),
            error_message=error,
            updated_at=timezone.now(),
        )

    @classmethod
    def cleanup_stale_jobs(cls, hours: int = 2):
        """
        Clean up jobs that have been pending/in-progress for too long.
        This handles cases where workers crashed.
        """
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=hours)

        stale_jobs = cls.objects.filter(
            status__in=[cls.Status.PENDING, cls.Status.IN_PROGRESS],
            created_at__lt=cutoff,
        )

        count = stale_jobs.count()
        stale_jobs.update(
            status=cls.Status.FAILED,
            error_message="Stale job - likely worker crashed",
            completed_at=timezone.now(),
        )

        return count
