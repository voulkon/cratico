"""
Cache Stats Middleware

Emits one summary line per request describing which cached views were hit and
which were missed, instead of one INFO line per cache lookup. Individual
lookups are still available at DEBUG level from the cache decorator.

Must be placed above the views (and before any middleware that may short-circuit
the response) so the per-request collector is reset before the view runs.
"""

from loguru import logger

from core.services.cache_stats import start_collecting, stop_collecting


class CacheStatsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        start_collecting()
        try:
            response = self.get_response(request)
        finally:
            accesses = stop_collecting()
        self._log_summary(request, accesses)
        return response

    @staticmethod
    def _log_summary(request, accesses):
        if not accesses:
            return

        hits = list(dict.fromkeys(a.view for a in accesses if a.hit))
        misses = list(dict.fromkeys(a.view for a in accesses if not a.hit))
        hit_count = sum(1 for a in accesses if a.hit)
        miss_count = len(accesses) - hit_count

        logger.info(
            f"[Cache Summary] {request.method} {request.path} | "
            f"lookups={len(accesses)} hits={hit_count} misses={miss_count} | "
            f"hit=[{', '.join(hits)}] miss=[{', '.join(misses)}]"
        )
