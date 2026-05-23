from django.db import models
from django.utils.translation import gettext_lazy as _


class Backup(models.Model):
    class BackupType(models.TextChoices):
        POSTGRES = "postgres", _("PostgreSQL")
        OPENSEARCH = "opensearch", _("OpenSearch")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        IN_PROGRESS = "in_progress", _("In Progress")
        SUCCESS = "success", _("Success")
        FAILED = "failed", _("Failed")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    backup_type = models.CharField(max_length=20, choices=BackupType.choices)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )
    s3_key = models.CharField(max_length=255, blank=True, null=True)
    size_bytes = models.BigIntegerField(null=True, blank=True)
    logs = models.TextField(blank=True)

    # For OpenSearch snapshots
    snapshot_name = models.CharField(max_length=255, blank=True, null=True)

    # For PostgreSQL backups - streaming vs file-based
    use_streaming = models.BooleanField(
        default=True, help_text=_("Use streaming backup to avoid disk space issues")
    )

    # Celery task tracking
    celery_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text=_("Celery task ID for tracking/cancellation"),
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = _("Backup")
        verbose_name_plural = _("Backups")

    def __str__(self):
        return f"{self.get_backup_type_display()} - {self.created_at.strftime('%Y-%m-%d %H:%M')}"
