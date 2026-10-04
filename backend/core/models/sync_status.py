from django.db import models
from django.utils import timezone

from core.constants.decision_import_constants import HOURLY_IMPORT_SYNC_TYPE


class SyncStatus(models.Model):
    """Track the last sync timestamp for different data types"""

    SYNC_TYPES = [
        ("decisions", "Decisions"),
        ("decisions_hourly", "Decisions (hourly)"),
        ("organizations", "Organizations"),
        ("signers", "Signers"),
    ]

    sync_type = models.CharField(max_length=50, choices=SYNC_TYPES, unique=True)
    last_sync_timestamp = models.DateTimeField()
    last_sync_date = models.DateField(null=True, blank=True)  # For daily tracking
    total_processed = models.IntegerField(default=0)
    last_run_status = models.CharField(max_length=20, default="pending")
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "core_sync_status"

    def __str__(self):
        return f"{self.sync_type} - Last sync: {self.last_sync_timestamp}"

    @classmethod
    def get_last_decisions_sync(cls):
        """Get the last decisions sync timestamp"""
        try:
            sync_status = cls.objects.get(sync_type="decisions")
            return sync_status.last_sync_timestamp
        except cls.DoesNotExist:
            # Default to 30 days ago if no previous sync
            return timezone.now() - timezone.timedelta(days=30)

    @classmethod
    def update_decisions_sync(
        cls, timestamp, processed_count=0, status="completed", error=None
    ):
        """Update the decisions sync status"""
        obj, created = cls.objects.get_or_create(
            sync_type="decisions",
            defaults={
                "last_sync_timestamp": timestamp,
                "last_sync_date": timestamp.date(),
                "total_processed": processed_count,
                "last_run_status": status,
                "error_message": error or "",
            },
        )
        if not created:
            obj.last_sync_timestamp = timestamp
            obj.last_sync_date = timestamp.date()
            obj.total_processed += processed_count
            obj.last_run_status = status
            obj.error_message = error or ""
            obj.save()
        return obj

    @classmethod
    def get_last_hourly_sync(cls):
        """Get the hourly import watermark (start of the next window).

        Returns the stored ``decisions_hourly`` timestamp, which the
        importer treats as the start of the next window minus any overlap
        it applies when querying. When no row exists (fresh deployment),
        defaults to one hour ago — never the 30-day default of
        ``get_last_decisions_sync`` — so a first run never attempts a
        30-day hourly catch-up.
        """
        try:
            return cls.objects.get(sync_type=HOURLY_IMPORT_SYNC_TYPE).last_sync_timestamp
        except cls.DoesNotExist:
            # Default to 1 hour ago if no previous hourly sync
            return timezone.now() - timezone.timedelta(hours=1)

    @classmethod
    def update_hourly_sync(
        cls, timestamp, processed_count=0, status="completed", error=None
    ):
        """Advance the hourly import watermark.

        Must only be called after a successful run: ``timestamp`` is the
        end of the just-processed window, which becomes the start of the
        next window (the importer subtracts its overlap when reading).
        On subsequent calls the watermark is overwritten and
        ``total_processed`` accumulates.
        """
        obj, created = cls.objects.get_or_create(
            sync_type=HOURLY_IMPORT_SYNC_TYPE,
            defaults={
                "last_sync_timestamp": timestamp,
                "last_sync_date": timestamp.date(),
                "total_processed": processed_count,
                "last_run_status": status,
                "error_message": error or "",
            },
        )
        if not created:
            obj.last_sync_timestamp = timestamp
            obj.last_sync_date = timestamp.date()
            obj.total_processed += processed_count
            obj.last_run_status = status
            obj.error_message = error or ""
            obj.save()
        return obj
