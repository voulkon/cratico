"""
Response Cache Service

Centralized service for caching expensive API view responses in Redis.
Follows the same pattern as FeatureFlagService and PrerequisiteCheckService.

Key design decisions:
- Smart TTL: historical data (end_date in the past) gets 24h cache,
  current data gets 5min cache — past data won't change.
- Centralized key generation via api.redis_keys (no ad-hoc key building).
- Deterministic keys: sorted params ensure cache hits regardless of param order.
- Namespace isolation: all keys prefixed with "api_cache:da:" to avoid collisions.

Usage in views:
    from core.services.response_cache_service import response_cache

    # Check cache
    cache_key = response_cache.build_key("top_pairs", start=..., end=..., limit=6)
    cached = response_cache.get(cache_key)
    if cached is not None:
        return Response(cached)

    # ... expensive query ...

    # Store in cache
    response_cache.set(cache_key, response_data, end_date=end_date)
    return Response(response_data)
"""

from datetime import date
from typing import Any, Optional

from api.redis_keys import (
    API_CACHE_EXPIRE_CURRENT,
    API_CACHE_EXPIRE_HISTORICAL,
    API_CACHE_EXPIRE_STATS,
    WARMUP_STATUS_TTL,
    get_api_cache_key,
    get_warmup_status_key,
)
from django.core.cache import cache
from loguru import logger


class ResponseCacheService:
    """
    Centralized service for caching API view responses.

    Provides:
    - Deterministic key generation (via redis_keys.py)
    - Smart TTL based on whether data is historical or current
    - get/set with automatic TTL selection
    - Cache invalidation by namespace
    """

    # Expose constants for direct access if needed
    EXPIRE_HISTORICAL = API_CACHE_EXPIRE_HISTORICAL  # 24h
    EXPIRE_CURRENT = API_CACHE_EXPIRE_CURRENT  # 5min
    EXPIRE_STATS = API_CACHE_EXPIRE_STATS  # 10min

    @staticmethod
    def build_key(view_name: str, **params) -> str:
        """
        Build a deterministic cache key for a view response.

        Args:
            view_name: Short view identifier (e.g., "top_pairs", "org_top_recipients")
            **params: Query parameters that affect the response

        Returns:
            Redis key string
        """
        return get_api_cache_key(view_name, **params)

    @staticmethod
    def get(cache_key: str) -> Optional[Any]:
        """
        Retrieve a cached response.

        Args:
            cache_key: Key from build_key()

        Returns:
            Cached data dict, or None on cache miss
        """
        return cache.get(cache_key)

    @staticmethod
    def set(
        cache_key: str,
        data: Any,
        end_date: Optional[Any] = None,
        timeout: Optional[int] = None,
    ) -> None:
        """
        Store a response in cache with smart TTL.

        If end_date is provided, automatically selects TTL:
        - Historical data (end_date < today): 24 hours
        - Current data (end_date >= today): 5 minutes

        If timeout is provided explicitly, it overrides the smart TTL.

        Args:
            cache_key: Key from build_key()
            data: Response data to cache
            end_date: End date of the query range (for smart TTL)
            timeout: Override TTL in seconds
        """
        if timeout is not None:
            effective_timeout = timeout
            timeout_source = "explicit"
        elif end_date is not None:
            effective_timeout = ResponseCacheService._compute_timeout(end_date)
            timeout_source = "computed from end_date"
        else:
            # Default to current TTL if no info provided
            effective_timeout = API_CACHE_EXPIRE_CURRENT
            timeout_source = "default (current)"

        cache.set(cache_key, data, effective_timeout)

        logger.info(
            f"[ResponseCache SET] key={cache_key} | "
            f"TTL={effective_timeout}s ({effective_timeout//60}m) | "
            f"source={timeout_source} | "
            f"end_date={end_date}"
        )

    @staticmethod
    def _compute_timeout(end_date) -> int:
        """
        Determine cache timeout based on whether the date range is historical.

        Historical data (end_date in the past) won't change → 24h cache.
        Data including today may still be updated → 5min cache.

        Args:
            end_date: datetime or date object representing the query's end date

        Returns:
            Timeout in seconds
        """
        today = date.today()
        end_date_only = end_date.date() if hasattr(end_date, "date") else end_date

        if end_date_only < today:
            timeout = API_CACHE_EXPIRE_HISTORICAL
            reason = "historical (end_date < today)"
        else:
            timeout = API_CACHE_EXPIRE_CURRENT
            reason = "current (end_date >= today)"

        logger.debug(
            f"[TTL Computation] end_date={end_date_only} vs today={today} → "
            f"{timeout}s ({timeout//60}m) because {reason}"
        )

        return timeout

    @staticmethod
    def invalidate_prefix(view_name: str) -> int:
        """
        Invalidate all cached responses for a specific view.

        Uses Django-Redis's delete_pattern for bulk invalidation.
        Useful after data imports that change query results.

        Args:
            view_name: The view identifier used in build_key()

        Returns:
            Number of keys deleted
        """
        try:
            from django_redis import get_redis_connection

            # Use the default cache connection (DB 1)
            conn = get_redis_connection("default")
            pattern = f"*api_cache:da:{view_name}*"
            count = conn.delete_pattern(pattern)

            if count > 0:
                logger.info(
                    f"ResponseCache: invalidated {count} keys for view={view_name}"
                )
            return count
        except Exception as e:
            logger.warning(f"ResponseCache: invalidation failed for {view_name}: {e}")
            return 0

    @staticmethod
    def invalidate_all() -> int:
        """
        Invalidate all API response caches.

        Returns:
            Number of keys deleted
        """
        try:
            from django_redis import get_redis_connection

            conn = get_redis_connection("default")
            pattern = f"*api_cache*"
            count = conn.delete_pattern(pattern)

            logger.info(f"ResponseCache: invalidated all ({count} keys)")
            return count
        except Exception as e:
            logger.warning(f"ResponseCache: full invalidation failed: {e}")
            return 0

    # ── Warmup status tracking (defer_on_miss) ─────────────────────────

    @staticmethod
    def get_warmup_status(cache_key: str) -> Optional[str]:
        """
        Check the warmup status for a cache key.

        Returns:
            "in_progress", "ready", or None (no warmup has been initiated)
        """
        status_key = get_warmup_status_key(cache_key)
        return cache.get(status_key)

    @staticmethod
    def set_warmup_status(
        cache_key: str, status: str, timeout: Optional[int] = None
    ) -> None:
        """
        Set the warmup status for a cache key.

        Args:
            cache_key: The standard API cache key
            status: "in_progress" or "ready"
            timeout: TTL in seconds (default: WARMUP_STATUS_TTL = 120s)
        """
        effective_timeout = timeout if timeout is not None else WARMUP_STATUS_TTL
        status_key = get_warmup_status_key(cache_key)
        cache.set(status_key, status, effective_timeout)
        logger.debug(
            f"[ResponseCache WARMUP] status={status} key={status_key} "
            f"ttl={effective_timeout}s"
        )

    @staticmethod
    def clear_warmup_status(cache_key: str) -> None:
        """
        Remove the warmup status key (typically after a successful warmup,
        the status becomes redundant once the data cache exists).
        """
        status_key = get_warmup_status_key(cache_key)
        cache.delete(status_key)
        logger.debug(f"[ResponseCache WARMUP] cleared status key={status_key}")


# Singleton instance for import convenience
response_cache = ResponseCacheService()
