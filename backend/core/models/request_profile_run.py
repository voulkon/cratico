"""
Persisted request-profiler runs.

Celery task results expire and are not queryable as history, so each run is
also stored here. The admin page reads this row for status, the revoke action,
and the before/after comparison view.
"""

import uuid

from django.conf import settings
from django.db import models


class RequestProfileRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        STARTED = "STARTED", "Running"
        SUCCESS = "SUCCESS", "Completed"
        FAILURE = "FAILURE", "Failed"
        REVOKED = "REVOKED", "Revoked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_id = models.CharField(max_length=64, unique=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    label = models.CharField(max_length=200, blank=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    targets = models.JSONField(default=list)
    options = models.JSONField(default=dict)
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self):
        label = self.label or "request profile"
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.get_status_display()} - {label}"

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            self.Status.SUCCESS,
            self.Status.FAILURE,
            self.Status.REVOKED,
        }

    @property
    def target_count(self) -> int:
        return len(self.targets or [])

    @property
    def total_wall_ms(self) -> float:
        requests = (self.result or {}).get("requests") or []
        return sum(float(request.get("wall_ms") or 0) for request in requests)

    @property
    def total_db_ms(self) -> float:
        requests = (self.result or {}).get("requests") or []
        return sum(float(request.get("db_ms") or 0) for request in requests)
