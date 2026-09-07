"""
Prerequisite Check Service

Provides cached prerequisite checks for search methods and other features.
This service is independent to avoid circular dependencies between SearchService and FeatureFlagService.
"""

from api.redis_keys import (
    PREREQUISITE_CHECK_CACHE_MIGRATION,
    PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS_PREFIX,
    PREREQUISITE_CHECK_CACHE_FULL_CHECK_PREFIX,
)
from typing import Any, Dict

from core.constants.search_service import (
    POSTGRES_FTS_MIGRATION, POSTGRES_FTS_MODELS
    )
import time

from django.core.cache import cache
from django.db import connection
from loguru import logger

from core.utils.search_trace import get_current_trace

# Log a warning if a single table probe takes longer than this (seconds).
# A healthy probe against a fully-backfilled table with a partial NULL-index
# is sub-millisecond; a seq scan over a big table is seconds.
SLOW_TABLE_PROBE_SECONDS = 1.0

# Search scopes. Each scope probes only the tables it actually searches,
# so entity searches never pay for the huge document tables.
SCOPE_ENTITY = "entity"
SCOPE_DOCUMENT = "document"

# Tables that only matter for document-content search (raw text extraction).
# These are the multi-million-row tables whose `search_vector IS NULL` probe
# is a 35-70s seq scan when fully backfilled.
DOCUMENT_ONLY_MODELS = {"extraction", "decision"}


def _trace_prereq(event_type: str, **data) -> None:
    """Record a prerequisite-check event in the active SearchTrace (if any).

    The prerequisite check runs inside search requests, so its events land in
    the same SEARCH_TRACE line as the type_search timings — making it directly
    visible when a slow search is actually a slow prerequisite recompute.
    """
    trace = get_current_trace()
    if trace is not None:
        trace.add(event_type, **data)


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
    def check_postgres_fts_backfill_status(scope: str = SCOPE_DOCUMENT) -> Dict[str, Any]:
        """
        Check if required search_vector fields are backfilled for a scope.

        Args:
            scope: 'entity' probes only entity tables (fast); 'document' probes
                all tables including core_decision/core_documentextraction.

        Returns:
            Dict with:
                - 'ready': bool - True if all required models are backfilled
                - 'details': dict - Per-model backfill status
                - 'missing_models': list - Models that need backfilling
                - 'summary': str - Human-readable summary
        """
        cache_key = f"{PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS_PREFIX}:{scope}"
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        details = {}
        missing_models = []

        # Scope filtering: entity search never touches document tables, so
        # it must not pay for their (very expensive) probes.
        models_to_check = {
            key: config
            for key, config in POSTGRES_FTS_MODELS.items()
            if config.get("required_for_fts", True)
            and not (scope == SCOPE_ENTITY and key in DOCUMENT_ONLY_MODELS)
        }

        # IMPORTANT: We use EXISTS (LIMIT 1) instead of COUNT(*) because
        # counting NULLs across millions of rows (e.g. core_documentextraction,
        # core_decision) takes ~30s on a cold cache. We only need to know
        # WHETHER backfill is incomplete, not the exact count, so a single
        # row probe is enough and short-circuits in milliseconds.
        with connection.cursor() as cursor:
            for model_key, config in models_to_check.items():
                table = config["table"]
                quoted_table = connection.ops.quote_name(table)

                probe_start = time.perf_counter()
                try:
                    # Fast probe: does at least one row have a NULL search_vector?
                    # LIMIT 1 lets the planner stop scanning as soon as it finds one.
                    cursor.execute(
                        f"""
                        SELECT EXISTS (
                            SELECT 1 FROM {quoted_table}
                            WHERE search_vector IS NULL
                            LIMIT 1
                        ) AS has_null,
                        EXISTS (
                            SELECT 1 FROM {quoted_table}
                            WHERE search_vector IS NOT NULL
                            LIMIT 1
                        ) AS has_any
                    """,  # nosec: B608 - Using Django's quote_name() for identifier safety
                    )
                    has_null, has_any = cursor.fetchone()
                    probe_ms = round((time.perf_counter() - probe_start) * 1000, 1)

                    # Same info into the per-request search trace.
                    _trace_prereq(
                        "prereq_probe",
                        table=table,
                        probe_ms=probe_ms,
                        has_null=has_null,
                    )

                    # Make cold-cache probe cost visible: these probes seq-scan
                    # the whole table when fully backfilled (no index can serve
                    # `search_vector IS NULL` without a partial index).
                    if probe_ms > SLOW_TABLE_PROBE_SECONDS * 1000:
                        logger.warning(
                            "FTS prerequisite probe SLOW table={table} "
                            "probe_ms={probe_ms} has_null={has_null} "
                            "(consider partial index on (search_vector) "
                            "WHERE search_vector IS NULL)",
                            table=table,
                            probe_ms=probe_ms,
                            has_null=has_null,
                        )
                    else:
                        logger.info(
                            "FTS prerequisite probe table={table} "
                            "probe_ms={probe_ms} has_null={has_null} "
                            "has_any={has_any}",
                            table=table,
                            probe_ms=probe_ms,
                            has_null=has_null,
                            has_any=has_any,
                        )

                    # A table is considered backfilled if it has at least one
                    # populated row and no NULL rows (has_null is False).
                    # Empty tables are treated as backfilled (nothing to do).
                    backfilled = has_any and not has_null
                    is_empty = not has_any

                    details[model_key] = {
                        "table": table,
                        "backfilled": backfilled,
                        "is_empty": is_empty,
                        "has_null_rows": has_null,
                    }

                    # Only flag as missing if there are NULL rows alongside
                    # populated ones (i.e. partial backfill).
                    if has_null and has_any:
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
            backfilled_tables = sum(
                1 for d in details.values() if d.get("backfilled", False)
            )
            summary = (
                f"[OK] All required models backfilled "
                f"({backfilled_tables}/{len(details)} tables ready)"
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

    # How long a waiter waits for the recompute lock holder before falling
    # back to "assume available" (avoids cascading slow requests during a
    # genuinely long recompute).
    LOCK_WAIT_SECONDS = 30

    @staticmethod
    def check_postgres_fts_prerequisites(scope: str = SCOPE_DOCUMENT) -> Dict[str, Any]:
        """
        Check PostgreSQL FTS prerequisites (migration + backfill) for a scope.

        Args:
            scope: 'entity' checks only entity tables (fast, no document
                tables); 'document' checks everything.

        Returns:
            Dict with:
                - 'available': bool - True if all prerequisites are met
                - 'reason': str - Human-readable explanation
                - 'details': dict - Detailed status information
                - 'migration_applied': bool - Migration status
                - 'backfill_ready': bool - Backfill status
        """
        # TODO: Replace with centralized value
        cache_key = f"{PREREQUISITE_CHECK_CACHE_FULL_CHECK_PREFIX}:{scope}"
        cached_result = cache.get(cache_key)

        if cached_result is not None:
            return cached_result

        # Dogpile protection: only ONE request per scope should recompute.
        # Concurrent requests either wait briefly or assume OK and retry.
        lock_key = f"{cache_key}:lock"
        lock_acquired = cache.add(
            lock_key, "recomputing", PrerequisiteCheckService.LOCK_WAIT_SECONDS
        )
        if not lock_acquired:
            # Another request is already recomputing. Wait a bounded time for
            # it to finish and populate the cache.
            wait_start = time.perf_counter()
            while (time.perf_counter() - wait_start) < PrerequisiteCheckService.LOCK_WAIT_SECONDS:
                time.sleep(0.25)
                cached_result = cache.get(cache_key)
                if cached_result is not None:
                    return cached_result
            # Lock holder is slow/stuck — proceed with a fresh recompute
            # rather than blocking forever.
            logger.warning(
                "FTS prerequisite lock wait timed out for scope={scope}; "
                "recomputing anyway",
                scope=scope,
            )

        try:
            return PrerequisiteCheckService._compute_postgres_fts_prerequisites(
                scope, cache_key
            )
        finally:
            cache.delete(lock_key)

    @staticmethod
    def _compute_postgres_fts_prerequisites(scope: str, cache_key: str) -> Dict[str, Any]:
        """Actual prerequisite computation (called under the dogpile lock)."""
        # Cold-cache recompute: make this visible in logs. If this line shows
        # up alongside a ~30s search_organizations duration, the prerequisite
        # check (not the search query) is the culprit.
        logger.warning(
            "FTS prerequisite cache MISS scope={scope} — running migration + "
            "backfill probes",
            scope=scope,
        )
        _trace_prereq("prereq_cache_miss", scope=scope)
        check_start = time.perf_counter()

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
        backfill_status = PrerequisiteCheckService.check_postgres_fts_backfill_status(
            scope=scope
        )

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
            total_ms = round((time.perf_counter() - check_start) * 1000, 1)
            logger.warning(
                "FTS prerequisite check DONE (not ready) scope={scope} "
                "total_ms={total_ms}",
                scope=scope,
                total_ms=total_ms,
            )
            _trace_prereq("prereq_done", scope=scope, ready=False, total_ms=total_ms)
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
        total_ms = round((time.perf_counter() - check_start) * 1000, 1)
        logger.info(
            "FTS prerequisite check DONE (ready) scope={scope} total_ms={total_ms}",
            scope=scope,
            total_ms=total_ms,
        )
        _trace_prereq("prereq_done", scope=scope, ready=True, total_ms=total_ms)
        return result

    @staticmethod
    def clear_cache():
        """Clear all prerequisite check caches."""
        cache.delete(PREREQUISITE_CHECK_CACHE_MIGRATION)
        for scope in (SCOPE_ENTITY, SCOPE_DOCUMENT):
            cache.delete(f"{PREREQUISITE_CHECK_CACHE_BACKFILL_STATUS_PREFIX}:{scope}")
            cache.delete(f"{PREREQUISITE_CHECK_CACHE_FULL_CHECK_PREFIX}:{scope}")
            cache.delete(f"{PREREQUISITE_CHECK_CACHE_FULL_CHECK_PREFIX}:{scope}:lock")
        logger.info("Cleared all prerequisite check caches")


# Global singleton instance
prerequisite_check = PrerequisiteCheckService()
