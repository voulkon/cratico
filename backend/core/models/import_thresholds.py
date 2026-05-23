"""
Model for configurable decision import thresholds.

This allows administrators to adjust expected decision counts per day-of-week
based on observed patterns from the coverage explorer.
"""

from django.db import models
from loguru import logger


class ImportThreshold(models.Model):
    """
    Singleton model storing expected decision count thresholds by day-of-week.

    These thresholds are used by the import validation system to determine
    if a given day was fetched completely. Adjust values based on actual
    patterns observed in the coverage explorer.
    """

    enabled = models.BooleanField(
        default=False,
        help_text="Enable/disable the import validation system. Disable temporarily during maintenance or expected incomplete periods.",
    )

    weekday_threshold = models.PositiveIntegerField(
        default=5000,
        help_text="Minimum expected decisions for Monday-Friday (normal weekdays)",
    )

    saturday_threshold = models.PositiveIntegerField(
        default=300, help_text="Minimum expected decisions for Saturday"
    )

    sunday_threshold = models.PositiveIntegerField(
        default=100, help_text="Minimum expected decisions for Sunday"
    )

    # Metadata fields
    last_updated = models.DateTimeField(auto_now=True)
    notes = models.TextField(
        blank=True,
        help_text="Notes about threshold adjustments (e.g., data range analyzed)",
    )

    class Meta:
        db_table = "core_import_threshold"
        verbose_name = "Import Threshold Configuration"
        verbose_name_plural = "Import Threshold Configuration"

    def __str__(self):
        status = "ENABLED" if self.enabled else "DISABLED"
        return f"Import Validation: {status} | Weekday={self.weekday_threshold}, Sat={self.saturday_threshold}, Sun={self.sunday_threshold}"

    def save(self, *args, **kwargs):
        """Ensure only one instance exists (singleton pattern)"""
        if not self.pk and ImportThreshold.objects.exists():
            # If no PK and instance exists, update the existing one
            existing = ImportThreshold.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_instance(cls):
        """Get or create the singleton instance"""
        instance, created = cls.objects.get_or_create(pk=1)
        if created:
            logger.info("Created ImportThreshold instance with default values")
        return instance

    @classmethod
    def get_threshold_for_weekday(cls, day_of_week: int) -> int:
        """
        Get threshold for a specific day of week (0=Monday, 6=Sunday).

        Args:
            day_of_week: Integer 0-6 where 0=Monday, 6=Sunday

        Returns:
            Expected minimum decision count for that day
        """
        instance = cls.get_instance()

        if day_of_week == 5:  # Saturday
            return instance.saturday_threshold
        elif day_of_week == 6:  # Sunday
            return instance.sunday_threshold
        else:  # Monday-Friday
            return instance.weekday_threshold
