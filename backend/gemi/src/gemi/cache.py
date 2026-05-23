"""Caching utilities for the GEMI API client."""

import hashlib
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Cache(ABC):
    """Abstract base class for cache implementations."""

    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""

    @abstractmethod
    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the cache with optional TTL in seconds."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete a value from the cache."""

    @abstractmethod
    def clear(self) -> None:
        """Clear all values from the cache."""


class MemoryCache(Cache):
    """Simple in-memory cache implementation."""

    def __init__(self, default_ttl: int = 300):  # 5 minutes default
        self.default_ttl = default_ttl
        self._cache: Dict[str, Dict[str, Any]] = {}

    def get(self, key: str) -> Optional[Any]:
        """Get a value from the cache."""
        if key not in self._cache:
            return None

        item = self._cache[key]
        if item["expires_at"] and time.time() > item["expires_at"]:
            del self._cache[key]
            return None

        return item["value"]

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Set a value in the cache with optional TTL in seconds."""
        if ttl is None:
            ttl = self.default_ttl

        expires_at = time.time() + ttl if ttl > 0 else None

        self._cache[key] = {"value": value, "expires_at": expires_at}

    def delete(self, key: str) -> None:
        """Delete a value from the cache."""
        self._cache.pop(key, None)

    def clear(self) -> None:
        """Clear all values from the cache."""
        self._cache.clear()


class NoCache(Cache):
    """No-op cache implementation that doesn't cache anything."""

    def get(self, key: str) -> Optional[Any]:
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        pass

    def delete(self, key: str) -> None:
        pass

    def clear(self) -> None:
        pass


def make_cache_key(endpoint: str, params: Optional[Dict[str, Any]] = None) -> str:
    """Generate a cache key from endpoint and parameters."""
    key_data = {"endpoint": endpoint}
    if params:
        # Sort params to ensure consistent key generation
        key_data["params"] = {k: v for k, v in sorted(params.items()) if v is not None}

    key_str = json.dumps(key_data, sort_keys=True)
    return hashlib.sha256(key_str.encode()).hexdigest()


class CachedClient:
    """Mixin to add caching capabilities to API clients."""

    def __init__(self, cache: Optional[Cache] = None, cache_ttl: int = 300):
        self.cache = cache or NoCache()
        self.cache_ttl = cache_ttl

    def _get_cached_or_fetch(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        fetch_func=None,
        ttl: Optional[int] = None,
    ) -> Any:
        """Get data from cache or fetch it if not cached."""
        cache_key = make_cache_key(endpoint, params)

        # Try to get from cache first
        cached_result = self.cache.get(cache_key)
        if cached_result is not None:
            return cached_result

        # Fetch from API
        if fetch_func is None:
            raise ValueError("fetch_func is required when data is not cached")

        result = fetch_func()

        # Cache the result
        cache_ttl = ttl or self.cache_ttl
        self.cache.set(cache_key, result, cache_ttl)

        return result
