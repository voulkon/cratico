"""
Per-request cache access statistics.

Records every ``ResponseCacheService.get()`` lookup into a context-local
collector so a single summary line can be emitted per request (see
``api.middleware.cache_stats.CacheStatsMiddleware``) instead of logging one
INFO line per lookup.

Collection is opt-in: it only happens between ``start_collecting()`` and
``stop_collecting()`` (called by the middleware), so cache lookups performed
outside HTTP requests (e.g. Celery workers) are not recorded and the
collector cannot grow without bound. Context variables keep the state
isolated per request/thread/task.
"""

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Tuple

from api.redis_keys import API_CACHE_DA_PREFIX


@dataclass(frozen=True)
class CacheAccess:
    """One cache lookup performed during the current request."""

    view: str
    key: str
    hit: bool


_EMPTY: Tuple[CacheAccess, ...] = ()
_accesses: ContextVar[Tuple[CacheAccess, ...]] = ContextVar(
    "response_cache_accesses", default=_EMPTY
)
_collecting: ContextVar[bool] = ContextVar(
    "response_cache_accesses_collecting", default=False
)


def _view_name_from_key(cache_key: str) -> str:
    """Extract the view identifier from an api_cache key."""
    if cache_key.startswith(API_CACHE_DA_PREFIX):
        return cache_key[len(API_CACHE_DA_PREFIX) :].split(":", 1)[0]
    return cache_key.split(":", 1)[0]


def start_collecting() -> None:
    """Reset and start collecting cache accesses for the current request."""
    _accesses.set(_EMPTY)
    _collecting.set(True)


def stop_collecting() -> Tuple[CacheAccess, ...]:
    """Stop collecting and return the accesses recorded so far."""
    accesses = _accesses.get()
    _collecting.set(False)
    _accesses.set(_EMPTY)
    return accesses


def record_cache_access(cache_key: str, hit: bool) -> None:
    """Record a cache lookup (hit or miss) when collection is active."""
    if not _collecting.get():
        return
    access = CacheAccess(
        view=_view_name_from_key(cache_key),
        key=cache_key,
        hit=hit,
    )
    _accesses.set(_accesses.get() + (access,))


def get_cache_stats() -> Tuple[CacheAccess, ...]:
    """Return the cache lookups recorded so far for the current request."""
    return _accesses.get()
