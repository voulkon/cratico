"""
Prerequisite Check Service

Provides cached prerequisite checks for search methods and other features.
This service is independent to avoid circular dependencies between SearchService and FeatureFlagService.
"""

from api.redis_keys import (
    PREREQUISITE_CHECK_CACHE_MIGRATION,
    PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS,  
    PREREQUISITE_CHECK_CACHE_FULL_CHECK
)
from typing import Any, Dict

from core.constants.search_service import (
    POSTGRES_FTS_MIGRATION, POSTGRES_FTS_MODELS
    )
from django.core.cache import cache
from django.db import connection
from loguru import logger


class PrerequisiteCheckService:
    """
    Service for checking feature prerequisites with caching.

    This service is independent to avoid circular dependencies:
    - SearchService uses it to validate search methods
    - FeatureFlagService uses it to validate flag values
    - Can be used anywhere without import issues
    """

    # Cache timeout in seconds (10 minutes - infrequent changes)
    CACHE_TIMEOUT = 600

    @staticmethod
    def check_postgres_fts_migration() -> bool:
        """
        Check if the PostgreSQL FTS migration has been applied.

        Returns:
            bool: True if migration exists, False otherwise
        """
        cache_key = PREREQUISITE_CHECK_CACHE_MIGRATION
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        from django.db.migrations.recorder import MigrationRecorder

        try:
            result = MigrationRecorder.Migration.objects.filter(
                app="core", name=POSTGRES_FTS_MIGRATION
            ).exists()

            # Cache result (migrations don't change often)
            cache.set(cache_key, result, PrerequisiteCheckService.CACHE_TIMEOUT)
            return result

        except Exception as e:
            logger.warning(f"Could not check migration status: {e}")
            return False

    @staticmethod
    def check_postgres_fts_backfill_status() -> Dict[str, Any]:
        """
        Check if required search_vector fields are backfilled.

        Returns:
            Dict with:
                - 'ready': bool - True if all required models are backfilled
                - 'details': dict - Per-model backfill status
                - 'missing_models': list - Models that need backfilling
                - 'summary': str - Human-readable summary
        """
        cache_key = PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        details = {}
        missing_models = []

        with connection.cursor() as cursor:
            for model_key, config in POSTGRES_FTS_MODELS.items():
                # Skip models not required for FTS
                if not config.get("required_for_fts", True):
                    continue

                table = config["table"]
                quoted_table = connection.ops.quote_name(table)

                try:
                    # Count NULL search vectors
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(*) FILTER (WHERE search_vector IS NULL) as null_count,
                            COUNT(*) as total_count
                        FROM {quoted_table}
                    """,  # nosec: B608 - Using Django's quote_name() for identifier safety
                    )
                    null_count, total_count = cursor.fetchone()

                    backfilled = total_count - null_count
                    percentage = (
                        (backfilled / total_count * 100) if total_count > 0 else 100
                    )

                    details[model_key] = {
                        "table": table,
                        "total": total_count,
                        "null": null_count,
                        "backfilled": backfilled,
                        "percentage": percentage,
                    }

                    # Consider backfilled if >95% have search_vector (allows for edge cases)
                    if total_count > 0 and null_count > total_count * 0.05:
                        missing_models.append(model_key)

                except Exception as e:
                    logger.warning(
                        f"Could not check backfill status for {model_key}: {e}"
                    )
                    details[model_key] = {"error": str(e)}
                    missing_models.append(model_key)

        ready = len(missing_models) == 0

        # Build human-readable summary
        if ready:
            total_records = sum(d.get("backfilled", 0) for d in details.values())
            summary = (
                f"[OK] All required models backfilled ({total_records:,} total records)"
            )
        else:
            summary = f"[FAIL] Missing backfill for: {', '.join(missing_models)}"

        result = {
            "ready": ready,
            "details": details,
            "missing_models": missing_models,
            "summary": summary,
        }

        # Cache for 10 minutes
        cache.set(cache_key, result, PrerequisiteCheckService.CACHE_TIMEOUT)

        return result

    @staticmethod
    def check_postgres_fts_prerequisites() -> Dict[str, Any]:
        """
        Check all PostgreSQL FTS prerequisites (migration + backfill).

        Returns:
            Dict with:
                - 'available': bool - True if all prerequisites are met
                - 'reason': str - Human-readable explanation
                - 'details': dict - Detailed status information
                - 'migration_applied': bool - Migration status
                - 'backfill_ready': bool - Backfill status
        """
        # TODO: Replace with centralized value
        cache_key = PREREQUISITE_CHECK_CACHE_FULL_CHECK
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        # Check migration
        migration_applied = PrerequisiteCheckService.check_postgres_fts_migration()

        if not migration_applied:
            result = {
                "available": False,
                "reason": f"Migration {POSTGRES_FTS_MIGRATION} not applied. Run migrations first.",
                "migration_applied": False,
                "backfill_ready": False,
                "details": {},
            }
            cache.set(cache_key, result, PrerequisiteCheckService.CACHE_TIMEOUT)
            return result

        # Check backfill status
        backfill_status = PrerequisiteCheckService.check_postgres_fts_backfill_status()

        if not backfill_status["ready"]:
            missing = ", ".join(backfill_status["missing_models"])
            result = {
                "available": False,
                "reason": f"Search vectors not backfilled for: {missing}. Run: python manage.py backfill_search_vectors --others-only",
                "migration_applied": True,
                "backfill_ready": False,
                "details": backfill_status["details"],
                "missing_models": backfill_status["missing_models"],
            }
            cache.set(cache_key, result, PrerequisiteCheckService.CACHE_TIMEOUT)
            return result

        # All good!
        result = {
            "available": True,
            "reason": "PostgreSQL FTS migration applied and search vectors backfilled",
            "migration_applied": True,
            "backfill_ready": True,
            "details": backfill_status["details"],
        }

        cache.set(cache_key, result, PrerequisiteCheckService.CACHE_TIMEOUT)
        return result

    @staticmethod
    def clear_cache():
        """Clear all prerequisite check caches."""
        cache.delete(PREREQUISITE_CHECK_CACHE_MIGRATION)
        cache.delete(PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS)
        cache.delete(PREREQUISITE_CHECK_CACHE_FULL_CHECK)
        logger.info("Cleared all prerequisite check caches")


# Global singleton instance
prerequisite_check = PrerequisiteCheckService()
