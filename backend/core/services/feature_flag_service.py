"""
Feature Flag Service

Provides a centralized service for checking feature flags with a fallback mechanism:
1. Check database for flag value (highest priority)
2. Check environment variable if not in database
3. Use default value as last resort

This service includes caching for performance and supports runtime updates.
"""

import os
from typing import Any, Dict, Optional

from django.core.cache import cache
from django.db import DatabaseError
from django.utils import timezone
from loguru import logger


class FeatureFlagService:
    """
    Service for managing and checking feature flags.

    Usage:
        from core.services.feature_flag_service import feature_flags

        if feature_flags.is_enabled('STEALTH_MODE'):
            # Apply stealth mode logic
            pass
    """

    # Cache timeout in seconds (5 minutes)
    CACHE_TIMEOUT = 300

    # Known feature flags with their default values and env var names
    KNOWN_FLAGS = {
        "STEALTH_MODE": {
            "name": "Stealth Mode",
            "description": "Require authentication for all API endpoints",
            "default": False,
            "env_var": "STEALTH_MODE",
            "category": "authentication",
            "requires_restart": False,
        },
        "STEALTH_ALLOWLIST": {
            "name": "Stealth Allowlist",
            "description": "When enabled with STEALTH_MODE, only users with emails in this list can access the system. "
            "Select existing users or add email addresses manually.",
            "default": [],  # Empty list means no allowlist (all authenticated users allowed)
            "env_var": "",  # No environment variable for this flag
            "category": "authentication",
            "requires_restart": False,
            "value_type": "list",
        },
        "INDEX_THE_OPENSEARCH": {
            "name": "Index to OpenSearch",
            "description": "Enable document indexing to OpenSearch for full-text search. "
            "If disabled, search functionality will be limited. "
            "Requires backfill task when re-enabled.",
            "default": True,
            "env_var": "INDEX_THE_OPENSEARCH",
            "category": "data_indexing",
            "requires_restart": False,
        },
        "INDEX_THE_POSTGRES": {
            "name": "Index to PostgreSQL",
            "description": "Enable advanced indexing features in PostgreSQL database. "
            "Improves query performance for complex searches.",
            "default": True,
            "env_var": "INDEX_THE_POSTGRES",
            "category": "data_indexing",
            "requires_restart": False,
        },
        "ENTITY_SEARCH_METHOD": {
            "name": "Entity Search Method",
            "description": "Search method for entities (organizations, signers, units, companies, company persons). "
            "Options: postgres_simple (basic ILIKE, always available), "
            "postgres_fts (full-text search, requires INDEX_THE_POSTGRES), "
            "opensearch (advanced search, requires INDEX_THE_OPENSEARCH, not yet fully implemented). "
            "Automatically falls back to postgres_simple if prerequisites are not met.",
            "default": "postgres_simple",
            "env_var": "ENTITY_SEARCH_METHOD",
            "category": "data_indexing",
            "requires_restart": False,
            "value_type": "choice",
            "choices": ["postgres_simple", "postgres_fts", "opensearch"],
            "validate_prerequisites": True,  # Special flag to check prerequisites
        },
        "HAVE_AFM_FETCH_JOB": {
            "name": "Company Data Fetching",
            "description": "Enable automatic fetching of company information from GEMI/AFM registry. "
            "If disabled, company enrichment will not occur. "
            "Requires backfill task when re-enabled.",
            "default": True,
            "env_var": "HAVE_AFM_FETCH_JOB",
            "category": "data_enrichment",
            "requires_restart": False,
        },
        "EXTRACT_THE_DOCS_FROM_PDFS": {
            "name": "PDF Text Extraction",
            "description": "Enable text extraction from PDF attachments. "
            "If disabled, document content analysis will be limited. "
            "Requires backfill task when re-enabled.",
            "default": True,
            "env_var": "EXTRACT_THE_DOCS_FROM_PDFS",
            "category": "data_extraction",
            "requires_restart": False,
        },
        "TRANSMIT_TO_JAEGER": {
            "name": "Jaeger Tracing",
            "description": "Enable OpenTelemetry tracing to Jaeger for distributed tracing. "
            "If disabled, no spans will be sent to Jaeger. "
            "Requires service restart to take effect.",
            "default": False,
            "env_var": "TRANSMIT_TO_JAEGER",
            "category": "system",
            "requires_restart": True,
        },
        "LIGHT_WORKER": {
            "name": "Light Worker Mode",
            "description": "Use lightweight Celery worker without PDF processing dependencies (Docling). "
            "Only PyMuPDF extractor is available, reducing Docker image size and memory footprint. "
            "Requires worker restart to take effect.",
            "default": False,
            "env_var": "LIGHT_WORKER",
            "category": "system",
            "requires_restart": True,
        },
        "FILTER_DECISION_TYPES": {
            "name": "Filter Decision Types",
            "description": "Limit decision imports to specific decision types. "
            "When empty/disabled, all types are imported. "
            "When configured with types (e.g., Δ.1, Β.2.2), only those types are fetched. "
            "Uses semicolon separator for multiple types in API calls.",
            "default": [],  # Empty list means no filter (import all types)
            "env_var": "",  # No environment variable for this flag
            "category": "data_ingestion",
            "requires_restart": False,
            "value_type": "list",
        },
        "STEALTH_EXEMPT_PREFIXES": {
            "name": "Stealth Mode Exempt Paths",
            "description": "URL path prefixes that are exempt from stealth mode authentication. "
            "Useful for keeping certain endpoints public (e.g., health checks, docs). "
            "Default exempts: /api/health, /api/v1/health, /api/admin",
            "default": ["/api/health", "/api/v1/health", "/api/admin"],
            "env_var": "",  # No environment variable for this flag
            "category": "authentication",
            "requires_restart": False,
            "value_type": "list",
        },
        "USE_CLERK_AUTH": {
            "name": "Use Clerk Authentication",
            "description": "Enable Clerk JWT authentication for API endpoints. "
            "When enabled, requires CLERK_JWT_PUBLIC_KEY and CLERK_SECRET_KEY environment variables. "
            "When disabled, falls back to Django default authentication. "
            "Requires service restart to take effect.",
            "default": False,
            "env_var": "USE_CLERK_AUTH",
            "category": "authentication",
            "requires_restart": True,
        },
        "SEARCH_HISTORY_RECORDING_MODE": {
            "name": "Search History Recording Mode",
            "description": "Controls how search queries are recorded in user search history. "
            "Options: none (no recording), selections_only (only when user selects a result), "
            "filtered (smart filtering - skip short queries and rapid duplicates), "
            "all (record everything including partial typing). "
            "Default is filtered for optimal UX and storage.",
            "default": "filtered",
            "env_var": "SEARCH_HISTORY_RECORDING_MODE",
            "category": "api",
            "requires_restart": False,
            "value_type": "choice",
            "choices": ["none", "selections_only", "filtered", "all"],
        },
        "AUTO_DAILY_IMPORT_ENABLED": {
            "name": "Auto Daily Import (Fresh Data)",
            "description": "Automatically import decisions for the previous day at scheduled time. "
            "Runs daily at the time specified in AUTO_DAILY_IMPORT_TIME. "
            "This task will eventually include summary generation and email notifications.",
            "default": False,
            "env_var": "AUTO_DAILY_IMPORT_ENABLED",
            "category": "data_ingestion",
            "requires_restart": False,
        },
        "AUTO_DAILY_IMPORT_TIME": {
            "name": "Auto Daily Import Time",
            "description": "Time (HH:MM format) when the daily import task runs. "
            'Default is "00:30" (12:30 AM). '
            "Must be set via environment variable AUTO_DAILY_IMPORT_TIME "
            "(cannot use database value because Celery beat schedule is "
            "defined before Django apps are loaded). "
            "Requires worker/beat restart to take effect.",
            "default": "00:30",
            "env_var": "AUTO_DAILY_IMPORT_TIME",
            "category": "data_ingestion",
            "requires_restart": True,
            "value_type": "string",
        },
        "AUTO_BACKFILL_ENABLED": {
            "name": "Auto Backfill (Continuous Autofarming)",
            "description": "Continuously import historical data by finding the next oldest missing day. "
            "When enabled, after each import job completes, automatically finds and queues "
            "the next oldest day with missing data. This runs continuously until all historical "
            "gaps are filled. Uses actual Decision records to verify coverage. "
            "Enabling this flag will immediately trigger the first backfill task.",
            "default": False,
            "env_var": "AUTO_BACKFILL_ENABLED",
            "category": "data_ingestion",
            "requires_restart": False,
        },
        "AUTO_COMPANY_GEMI_IMPORT_ENABLED": {
            "name": "Auto Company GEMI Import",
            "description": "Automatically populate the AFM fetch queue from scored entities and start processing "
            "at a scheduled time each day. Mirrors the 'Populate Queue' + 'Start Processing' "
            "actions in the AFM Scoring cockpit. "
            "Runs daily at the time specified in AUTO_COMPANY_GEMI_IMPORT_TIME.",
            "default": False,
            "env_var": "AUTO_COMPANY_GEMI_IMPORT_ENABLED",
            "category": "data_enrichment",
            "requires_restart": False,
        },
        # ── Date-Mode Alignment (fetch ↔ coverage) ───────────────────
        "COVERAGE_DATE_MODE": {
            "name": "Coverage Date Mode",
            "description": "Controls which date field is used for both fetching from the Diavgeia API "
            "AND counting decisions for coverage/backfill. "
            "Options: submission (from_date/to_date & publish_date_day — when uploaded), "
            "issue (from_issue_date/to_issue_date & issue_date_day — when issued). "
            "WARNING: Changing this mid-backfill will cause coverage mismatches. "
            "Only toggle for short experiments on low-traffic days.",
            "default": "submission",
            "env_var": "COVERAGE_DATE_MODE",
            "category": "data_ingestion",
            "requires_restart": False,
            "value_type": "choice",
            "choices": ["submission", "issue"],
        },
        # ── Post-Import Pipeline ──────────────────────────────────────
        "POST_IMPORT_ORCHESTRATOR_ENABLED": {
            "name": "Post-Import Orchestrator",
            "description": "Master switch for the post-import task pipeline (analytics, "
            "cache warming, notifications, amount verification).  When enabled, fires "
            "automatically after a global daily import completes.  Individual sub-tasks "
            "can be toggled independently via their own flags.",
            "default": False,
            "env_var": "POST_IMPORT_ORCHESTRATOR_ENABLED",
            "category": "data_ingestion",
            "requires_restart": False,
        },
        "ANALYTICS_PRECALC_ENABLED": {
            "name": "Analytics Pre-calculation (Entity Rankings)",
            "description": "Pre-compute per-entity statistics (amounts, counts, rankings) "
            "for daily/weekly/monthly/yearly windows after each global daily import. "
            "Stores results in AnalyticsSnapshotRun + EntityAnalyticsSnapshot models. "
            "Requires POST_IMPORT_ORCHESTRATOR_ENABLED.",
            "default": False,
            "env_var": "ANALYTICS_PRECALC_ENABLED",
            "category": "analytics",
            "requires_restart": False,
        },
        "ANALYTICS_WARMUP_ENABLED": {
            "name": "Analytics Cache Warming",
            "description": "Pre-populate Redis cache keys for heavy analytics views "
            "(top pairs, top organizations, recent high-value decisions) so the "
            "first real user request is always a cache hit. "
            "Requires POST_IMPORT_ORCHESTRATOR_ENABLED.",
            "default": False,
            "env_var": "ANALYTICS_WARMUP_ENABLED",
            "category": "analytics",
            "requires_restart": False,
        },
        "POST_IMPORT_NOTIFICATIONS_ENABLED": {
            "name": "Post-Import Notification Checks",
            "description": "After a global daily import, fan out and check all active "
            "notification subscriptions for new matching decisions. "
            "Requires POST_IMPORT_ORCHESTRATOR_ENABLED.",
            "default": False,
            "env_var": "POST_IMPORT_NOTIFICATIONS_ENABLED",
            "category": "notifications",
            "requires_restart": False,
        },
        "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED": {
            "name": "Post-Import Amount Verification",
            "description": "After a global daily import, verify monetary amounts in "
            "high-value decisions (≥€1M) by reading the document text (regex-first, "
            "optional AI). Catches data-entry errors like misplaced decimal "
            "separators. Requires POST_IMPORT_ORCHESTRATOR_ENABLED.",
            "default": True,
            "env_var": "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED",
            "category": "data_quality",
            "requires_restart": False,
        },
        # ── User-Triggered GEMI Fetch ─────────────────────────────────
        "GEMI_FETCH_REQUEST_PUBLIC_ACCESS": {
            "name": "GEMI Fetch Request — Public Access",
            "description": "Allow unauthenticated (not logged-in) users to request company data "
            "fetching from the GEMI registry via the public API button. "
            "When disabled, only authenticated users can trigger a fetch.",
            "default": True,
            "env_var": "GEMI_FETCH_REQUEST_PUBLIC_ACCESS",
            "category": "data_enrichment",
            "requires_restart": False,
        },
        "GEMI_FETCH_REQUEST_DAILY_LIMIT": {
            "name": "GEMI Fetch Request — Daily Limit per IP",
            "description": "Maximum number of user-triggered GEMI company fetch requests "
            "allowed per IP address per UTC day. "
            "Applies to both authenticated and unauthenticated users.",
            "default": 10,
            "env_var": "GEMI_FETCH_REQUEST_DAILY_LIMIT",
            "category": "data_enrichment",
            "requires_restart": False,
            "value_type": "integer",
        },
        # ── Security & Threat Detection ───────────────────────────────
        "SECURITY_MONITORING_ENABLED": {
            "name": "Security Monitoring",
            "description": "Master switch for the security/threat-detection layer. "
            "When enabled, tracks per-IP velocity, 4xx/5xx ratios, endpoint-scanning "
            "behavior, and security-event strikes in Redis. "
            "Does NOT enforce anything by itself — pair with SECURITY_AUTO_BAN "
            "for enforcement. Safe to leave on in production (Redis-only, no DB writes).",
            "default": False,
            "env_var": "SECURITY_MONITORING_ENABLED",
            "category": "security",
            "requires_restart": False,
        },
        "SECURITY_FORENSIC_LOGGING_ENABLED": {
            "name": "Forensic Request Logging",
            "description": "When enabled, writes every API request (IP, endpoint, method, "
            "query params, user agent, status code, response time) to the EndpointAccessLog "
            "table. WARNING: high DB write volume — only enable for short investigation "
            "windows or on low-traffic deployments. When disabled, only requests from "
            "flagged IPs are logged (see SECURITY_MONITORING_ENABLED).",
            "default": False,
            "env_var": "SECURITY_FORENSIC_LOGGING_ENABLED",
            "category": "security",
            "requires_restart": False,
        },
        "SECURITY_AUTO_BAN_ENABLED": {
            "name": "Automatic IP Banning",
            "description": "When enabled, IPs that exceed the velocity/strike thresholds "
            "are automatically added to the Redis ban set and blocked at the middleware "
            "layer (HTTP 403). When disabled, threats are only recorded for review. "
            "Requires SECURITY_MONITORING_ENABLED.",
            "default": False,
            "env_var": "SECURITY_AUTO_BAN_ENABLED",
            "category": "security",
            "requires_restart": False,
        },
        "SECURITY_VELOCITY_THRESHOLD": {
            "name": "Velocity Threshold (req/min)",
            "description": "Number of requests per minute from a single IP that triggers "
            "a velocity flag. Default 300 (5 req/sec sustained). "
            "Tune based on legitimate traffic patterns.",
            "default": 300,
            "env_var": "SECURITY_VELOCITY_THRESHOLD",
            "category": "security",
            "requires_restart": False,
            "value_type": "integer",
        },
        "SECURITY_STRIKE_THRESHOLD": {
            "name": "Security Strike Threshold",
            "description": "Number of security events (SQLi/XSS/path-traversal attempts "
            "from security.py middleware) from a single IP within the strike window "
            "(default 1 hour) that triggers an automatic ban. Default 5.",
            "default": 5,
            "env_var": "SECURITY_STRIKE_THRESHOLD",
            "category": "security",
            "requires_restart": False,
            "value_type": "integer",
        },
        "SECURITY_BAN_DURATION_HOURS": {
            "name": "Ban Duration (hours)",
            "description": "How long an automatically-banned IP stays blocked. "
            "Default 24 hours. Set to 0 for permanent ban (requires manual unban).",
            "default": 24,
            "env_var": "SECURITY_BAN_DURATION_HOURS",
            "category": "security",
            "requires_restart": False,
            "value_type": "integer",
        },
        "SECURITY_SCAN_THRESHOLD": {
            "name": "Scan Detection Threshold",
            "description": "Number of distinct endpoints hit by a single IP within "
            "the scan window (default 5 minutes) that triggers a scan flag. "
            "Default 80. Endpoints are normalized (numeric IDs collapsed) before "
            "counting, so /api/decisions/123/ and /api/decisions/456/ count as one.",
            "default": 80,
            "env_var": "SECURITY_SCAN_THRESHOLD",
            "category": "security",
            "requires_restart": False,
            "value_type": "integer",
        },
        "SECURITY_ERROR_THRESHOLD": {
            "name": "Error Rate Threshold",
            "description": "Number of 4xx/5xx responses from a single IP within "
            "the error window (default 5 minutes) that triggers an error-rate flag. "
            "Default 60.",
            "default": 60,
            "env_var": "SECURITY_ERROR_THRESHOLD",
            "category": "security",
            "requires_restart": False,
            "value_type": "integer",
        },
    }

    def __init__(self):
        """Initialize the feature flag service."""
        self._db_available = True

    def is_enabled(self, flag_key: str, default: Optional[bool] = None) -> bool:
        """
        Check if a feature flag is enabled (for boolean flags).

        Args:
            flag_key: The feature flag key (e.g., 'STEALTH_MODE')
            default: Optional default value to use if flag is not found

        Returns:
            bool: True if the flag is enabled, False otherwise

        Resolution order:
            1. Database value (if exists and is_active=True)
            2. Environment variable (if exists)
            3. Provided default parameter
            4. KNOWN_FLAGS default value
            5. False (safe default)
        """
        value = self.get_value(flag_key, default=default)
        # Convert to boolean for backward compatibility
        if isinstance(value, bool):
            return value
        elif isinstance(value, list):
            return len(value) > 0  # Non-empty list is truthy
        elif isinstance(value, str):
            return value.lower() in ("true", "1", "t", "yes", "on")
        return False

    def get_value(self, flag_key: str, default: Any = None) -> Any:
        """
        Get the value of a feature flag (supports boolean, list, string types).

        Args:
            flag_key: The feature flag key
            default: Optional default value to use if flag is not found

        Returns:
            The flag value (bool, list, str, etc.) based on its type

        Resolution order:
            1. Database value (if exists and is_active=True)
            2. Environment variable (if exists)
            3. Provided default parameter
            4. KNOWN_FLAGS default value
            5. Type-appropriate default (False for bool, [] for list, '' for string)
        """
        # Try cache first
        cache_key = f"feature_flag:{flag_key}"
        cached_value = cache.get(cache_key)
        if cached_value is not None:
            return cached_value

        # Try database
        db_value = self._get_from_database(flag_key)
        if db_value is not None:
            # Cache the result
            cache.set(cache_key, db_value, self.CACHE_TIMEOUT)
            return db_value

        # Try environment variable
        env_value = self._get_from_environment(flag_key)
        if env_value is not None:
            # Cache the result (shorter timeout for env vars)
            cache.set(cache_key, env_value, 60)
            return env_value

        # Use provided default
        if default is not None:
            return default

        # Use KNOWN_FLAGS default
        if flag_key in self.KNOWN_FLAGS:
            return self.KNOWN_FLAGS[flag_key]["default"]

        # Type-appropriate default
        logger.warning(
            f"Feature flag '{flag_key}' not found in DB, env, or defaults. Returning False."
        )
        return False

    def _get_from_database(self, flag_key: str) -> Optional[Any]:
        """
        Get feature flag value from database.

        Args:
            flag_key: The feature flag key

        Returns:
            The flag value (type depends on value_type field), or None if not found
        """
        if not self._db_available:
            return None

        try:
            from datetime import timedelta

            from core.models.feature_flags import FeatureFlag

            flag = FeatureFlag.objects.filter(key=flag_key, is_active=True).first()

            if flag:
                # Update last_checked_at only if it's been more than 1 hour
                # This reduces DB writes while still tracking usage
                now = timezone.now()
                if not flag.last_checked_at or (now - flag.last_checked_at) > timedelta(
                    hours=1
                ):
                    flag.last_checked_at = now
                    flag.save(update_fields=["last_checked_at"])

                # Return value based on type
                return flag.get_value()

            return None

        except DatabaseError as e:
            logger.warning(
                f"Database error while checking feature flag '{flag_key}': {e}"
            )
            self._db_available = False
            return None
        except Exception as e:
            logger.error(f"Unexpected error checking feature flag '{flag_key}': {e}")
            return None

    def _get_from_environment(self, flag_key: str) -> Optional[Any]:
        """
        Get feature flag value from environment variable.

        Args:
            flag_key: The feature flag key (or env var name)

        Returns:
            The flag value coerced to the correct type, or None if not set
        """
        # First try the flag_key directly
        env_value = os.getenv(flag_key)

        # If not found and we know the env var name, try that
        if env_value is None and flag_key in self.KNOWN_FLAGS:
            env_var_name = self.KNOWN_FLAGS[flag_key].get("env_var")
            if env_var_name:
                env_value = os.getenv(env_var_name)

        if env_value is not None:
            value_type = self.KNOWN_FLAGS.get(flag_key, {}).get("value_type", "boolean")
            if value_type == "integer":
                try:
                    return int(env_value)
                except (ValueError, TypeError):
                    logger.warning(
                        f"Could not parse env var for '{flag_key}' as integer: {env_value!r}"
                    )
                    return None
            # Default: convert to boolean
            return env_value.lower() in ("true", "1", "t", "yes", "on")

        return None

    def get_all_flags(self) -> Dict[str, bool]:
        """
        Get all feature flags and their current values.

        Returns:
            Dict[str, bool]: Dictionary of flag keys to their current values
        """
        # Try cache first
        cache_key = "feature_flags:all"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        result = {}

        # Get all known flags
        for flag_key in self.KNOWN_FLAGS:
            result[flag_key] = self.is_enabled(flag_key)

        # Get any additional flags from database
        try:
            from core.models.feature_flags import FeatureFlag

            db_flags = FeatureFlag.objects.filter(is_active=True)
            for flag in db_flags:
                if flag.key not in result:
                    result[flag.key] = flag.enabled
        except Exception as e:
            logger.error(f"Error fetching all flags from database: {e}")

        # Cache for 1 minute
        cache.set(cache_key, result, 60)

        return result

    def get_flag_info(self, flag_key: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a feature flag.

        Args:
            flag_key: The feature flag key

        Returns:
            Optional[Dict]: Flag information including current value, source, etc.
        """
        info = {
            "key": flag_key,
            "enabled": self.is_enabled(flag_key),
            "source": "default",
            "db_override": False,
            "env_override": False,
        }

        # Check if it's in known flags
        if flag_key in self.KNOWN_FLAGS:
            info.update(self.KNOWN_FLAGS[flag_key])

        # Check database
        try:
            from core.models.feature_flags import FeatureFlag

            flag = FeatureFlag.objects.filter(key=flag_key, is_active=True).first()

            if flag:
                info["source"] = "database"
                info["db_override"] = True
                info["name"] = flag.name
                info["description"] = flag.description
                info["category"] = flag.category
                info["requires_restart"] = flag.requires_restart
                info["updated_at"] = flag.updated_at
        except Exception:
            pass

        # Check environment
        env_value = self._get_from_environment(flag_key)
        if env_value is not None and info["source"] == "default":
            info["source"] = "environment"
            info["env_override"] = True

        return info

    def clear_cache(self, flag_key: Optional[str] = None):
        """
        Clear cached feature flag values.

        Args:
            flag_key: Specific flag to clear, or None to clear all
        """
        if flag_key:
            cache_key = f"feature_flag:{flag_key}"
            cache.delete(cache_key)
            logger.info(f"Cleared cache for feature flag: {flag_key}")
        else:
            # Clear all feature flag caches
            cache.delete("feature_flags:all")
            for key in self.KNOWN_FLAGS:
                cache_key = f"feature_flag:{key}"
                cache.delete(cache_key)
            logger.info("Cleared all feature flag caches")

    def initialize_flags_in_db(self):
        """
        Initialize all known flags in the database if they don't exist.

        Uses environment variables for initial values, then respects DB as source of truth.
        This allows manual changes via admin interface to persist across restarts.

        Note: Only creates missing flags. Existing flags are never modified automatically.
        Use sync_feature_flags management command to explicitly sync with env vars.
        """
        try:
            from core.models.feature_flags import FeatureFlag

            created_count = 0

            for flag_key, flag_data in self.KNOWN_FLAGS.items():
                # Determine value type
                value_type = flag_data.get("value_type", "boolean")

                # Prepare defaults based on value type
                defaults = {
                    "name": flag_data["name"],
                    "description": flag_data["description"],
                    "default_value": (
                        flag_data.get("default", False)
                        if value_type == "boolean"
                        else False
                    ),
                    "env_var_name": flag_data.get("env_var", ""),
                    "category": flag_data.get("category", "system"),
                    "requires_restart": flag_data.get("requires_restart", False),
                    "value_type": value_type,
                }

                # Set value based on type
                if value_type == "boolean":
                    # Check if environment variable is set
                    env_value = self._get_from_environment(flag_key)
                    # Use env value if set, otherwise use default
                    initial_enabled = (
                        env_value if env_value is not None else flag_data["default"]
                    )
                    defaults["enabled"] = initial_enabled
                elif value_type == "list":
                    defaults["list_value"] = flag_data.get("default", [])
                elif value_type == "string":
                    defaults["string_value"] = flag_data.get("default", "")
                elif value_type == "choice":
                    # Choice is a string from a predefined list
                    defaults["string_value"] = flag_data.get("default", "")

                flag, created = FeatureFlag.objects.get_or_create(
                    key=flag_key, defaults=defaults
                )

                if created:
                    created_count += 1
                    if value_type == "boolean":
                        env_value = self._get_from_environment(flag_key)
                        source = "environment" if env_value is not None else "default"
                        logger.info(
                            f"Created feature flag: {flag_key} = {defaults['enabled']} (from {source})"
                        )
                    elif value_type == "list":
                        count = (
                            len(defaults["list_value"]) if defaults["list_value"] else 0
                        )
                        logger.info(
                            f"Created feature flag: {flag_key} (list with {count} items)"
                        )
                    elif value_type in ("string", "choice"):
                        value_display = defaults["string_value"] or "(empty)"
                        type_label = "choice" if value_type == "choice" else "string"
                        logger.info(
                            f"Created feature flag: {flag_key} = {value_display} ({type_label})"
                        )

            if created_count > 0:
                logger.info(
                    f"Initialized {created_count} new feature flags in database"
                )

            return created_count

        except Exception as e:
            logger.error(f"Error initializing feature flags: {e}")
            return 0


# Global singleton instance
feature_flags = FeatureFlagService()
