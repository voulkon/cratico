"""
Feature Flag Models

Provides database-backed feature flags with environment variable fallback.
Allows runtime configuration of system features through the admin interface.
"""

from api.redis_keys import FEATURE_FLAG_PREFIX
from django.core.cache import cache
from django.db import models
from django.db.models import JSONField
from django.utils import timezone

class FeatureFlag(models.Model):
    """
    Feature flag model for controlling system functionality.

    Flags can be enabled/disabled through the admin interface with database priority.
    If a flag is not in the database, the system falls back to environment variables.

    Features support runtime updates with automatic cache invalidation.
    """

    FLAG_CATEGORIES = [
        ("authentication", "Authentication & Access"),
        ("data_indexing", "Data Indexing"),
        ("data_extraction", "Data Extraction"),
        ("data_enrichment", "Data Enrichment"),
        ("data_ingestion", "Data Ingestion"),
        ("api", "API Features"),
        ("frontend", "Frontend Features"),
        ("system", "System Features"),
    ]

    VALUE_TYPES = [
        ("boolean", "Boolean (True/False)"),
        ("list", "List (Multiple Values)"),
        ("string", "String (Text)"),
        ("choice", "Choice (String from Predefined List)"),
        ("integer", "Integer (Whole Number)"),
    ]

    # Core fields
    key = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
        help_text="Unique identifier for the feature flag (e.g., 'STEALTH_MODE')",
    )

    enabled = models.BooleanField(
        default=True, help_text="Enable or disable this feature (for boolean flags)"
    )

    # Value type and storage
    value_type = models.CharField(
        max_length=20,
        choices=VALUE_TYPES,
        default="boolean",
        help_text="Type of value this flag stores",
    )

    list_value = JSONField(
        null=True,
        blank=True,
        help_text="For list-type flags: array of values (e.g., ['Δ.1', 'Β.2.2'])",
    )

    string_value = models.TextField(
        blank=True,
        help_text="For string/choice/integer-type flags: text value (integers stored as text)",
    )

    # Metadata
    category = models.CharField(
        max_length=50,
        choices=FLAG_CATEGORIES,
        default="system",
        help_text="Category for organizing flags",
    )

    name = models.CharField(
        max_length=200, help_text="Human-readable name for this flag"
    )

    description = models.TextField(
        help_text="Detailed description of what this flag controls"
    )

    # Additional information
    default_value = models.BooleanField(
        default=False, help_text="Default value if not set in database or environment"
    )

    env_var_name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Associated environment variable name (if applicable)",
    )

    requires_restart = models.BooleanField(
        default=False, help_text="Whether changing this flag requires a service restart"
    )

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_checked_at = models.DateTimeField(
        null=True, blank=True, help_text="Last time this flag was checked"
    )

    # Safety features
    is_active = models.BooleanField(
        default=True, help_text="Whether this flag is currently active in the system"
    )

    notes = models.TextField(
        blank=True, help_text="Additional notes or warnings about this flag"
    )

    class Meta:
        db_table = "core_feature_flags"
        verbose_name = "Feature Flag"
        verbose_name_plural = "Feature Flags"
        ordering = ["category", "key"]
        indexes = [
            models.Index(fields=["key", "is_active"]),
            models.Index(fields=["category"]),
        ]

    def __str__(self):
        if self.value_type == "boolean":
            status = "[OK]" if self.enabled else "[FAIL]"
            return f"{status} {self.name} ({self.key})"
        elif self.value_type == "list" and self.list_value:
            count = len(self.list_value) if isinstance(self.list_value, list) else 0
            return f"[COPY] {self.name} ({count} items)"
        else:
            return f"{self.name} ({self.key})"

    def get_value(self):
        """Get the appropriate value based on value_type."""
        if self.value_type == "boolean":
            return self.enabled
        elif self.value_type == "list":
            return self.list_value or []
        elif self.value_type == "string":
            return self.string_value
        elif self.value_type == "choice":
            return self.string_value
        elif self.value_type == "integer":
            # Integers are stored in string_value as text; coerce on read
            try:
                return int(self.string_value)
            except (TypeError, ValueError):
                return None
        return None

    def save(self, *args, **kwargs):
        """Override save to invalidate cache and validate prerequisites when flag changes."""
        # Track if this is an update and what the old values were
        is_update = self.pk is not None
        old_enabled = None
        old_string_value = None

        if is_update:
            try:
                old_instance = FeatureFlag.objects.get(pk=self.pk)
                old_enabled = (
                    old_instance.enabled
                    if old_instance.value_type == "boolean"
                    else None
                )
                old_string_value = (
                    old_instance.string_value
                    if old_instance.value_type in ("choice", "string")
                    else None
                )
            except FeatureFlag.DoesNotExist:
                pass

        # Validate prerequisites for ENTITY_SEARCH_METHOD
        if (
            self.key == "ENTITY_SEARCH_METHOD"
            and self.string_value == "postgres_fts"
            and self.string_value != old_string_value  # only when actually changing
        ):
            from core.services.prerequisite_check_service import prerequisite_check
            from django.core.exceptions import ValidationError

            # Clear cache first to get real-time status when saving
            prerequisite_check.clear_cache()
            # Check if PostgreSQL FTS prerequisites are met
            prereq_check = prerequisite_check.check_postgres_fts_prerequisites()
            if not prereq_check["available"]:
                raise ValidationError(
                    f"Cannot set search method to 'postgres_fts': {prereq_check['reason']}"
                )

        super().save(*args, **kwargs)

        # Invalidate cache for this flag
        cache_key = f"{FEATURE_FLAG_PREFIX}:{self.key}"
        cache.delete(cache_key)
        # Also invalidate the all flags cache
        cache.delete(f"{FEATURE_FLAG_PREFIX}:all")

        # Trigger backfill when AUTO_BACKFILL_ENABLED is turned on
        if self.key == "AUTO_BACKFILL_ENABLED" and self.value_type == "boolean":
            # Check if we just enabled it (changed from False to True)
            if self.enabled and (old_enabled is False or old_enabled is None):
                # Trigger the first backfill asynchronously
                # Import here to avoid circular imports
                from core.tasks.tasks_auto_import import trigger_next_backfill
                from loguru import logger

                logger.info(
                    "AUTO_BACKFILL_ENABLED was just enabled - triggering first backfill"
                )
                trigger_next_backfill.delay()

        # Trigger company GEMI cycle when AUTO_COMPANY_GEMI_IMPORT_ENABLED is turned on
        if self.key == "AUTO_COMPANY_GEMI_IMPORT_ENABLED" and self.value_type == "boolean":
            if self.enabled and (old_enabled is False or old_enabled is None):
                from core.tasks.tasks_auto_import import trigger_next_company_gemi_batch
                from loguru import logger

                logger.info(
                    "AUTO_COMPANY_GEMI_IMPORT_ENABLED was just enabled - triggering first batch"
                )
                trigger_next_company_gemi_batch.delay()

    def delete(self, *args, **kwargs):
        """Override delete to invalidate cache."""
        cache_key = f"{FEATURE_FLAG_PREFIX}:{self.key}"
        cache.delete(cache_key)
        cache.delete(f"{FEATURE_FLAG_PREFIX}:all")
        super().delete(*args, **kwargs)

    @staticmethod
    def get_cache_key(key: str) -> str:
        """Get the cache key for a feature flag."""
        return f"{FEATURE_FLAG_PREFIX}:{key}"


class FeatureFlagAuditLog(models.Model):
    """
    Audit log for tracking feature flag changes.

    Maintains a history of all flag modifications for compliance and debugging.
    """

    feature_flag = models.ForeignKey(
        FeatureFlag, on_delete=models.CASCADE, related_name="audit_logs"
    )

    changed_by = models.CharField(
        max_length=200, help_text="User or system that made the change"
    )

    change_type = models.CharField(
        max_length=20,
        choices=[
            ("created", "Created"),
            ("enabled", "Enabled"),
            ("disabled", "Disabled"),
            ("updated", "Updated"),
        ],
    )

    old_value = models.BooleanField(null=True, blank=True)
    new_value = models.BooleanField(null=True, blank=True)

    changed_at = models.DateTimeField(default=timezone.now)

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "core_feature_flag_audit_logs"
        verbose_name = "Feature Flag Audit Log"
        verbose_name_plural = "Feature Flag Audit Logs"
        ordering = ["-changed_at"]
        indexes = [
            models.Index(fields=["feature_flag", "-changed_at"]),
        ]

    def __str__(self):
        return f"{self.feature_flag.key} - {self.change_type} at {self.changed_at}"
