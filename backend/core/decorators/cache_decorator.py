"""
API Response Cache Decorator

Provides @cached_view decorator to automatically cache expensive API view responses.
Eliminates the need for manual cache key building, checking, and setting.

Usage:
    from core.decorators.cache_decorator import cached_view

    @cached_view(
        cache_prefix="explore_orgs",
        cache_params=["start_date", "end_date", "limit"],
        end_date_param="end_date"  # For smart TTL computation
    )
    @api_view(["GET"])
    def my_view(request):
        # Just write your logic - caching is automatic!
        return Response({"data": "..."})

Key features:
- Automatic cache key generation from request params
- Smart TTL based on end_date (historical vs current data)
- Handles both Response objects and dict responses
- Conditional caching via should_cache_fn
- Respects cache-control headers
"""

from datetime import datetime
from functools import wraps
from typing import Any, Callable, List, Optional

from core.services.response_cache_service import response_cache
from django.utils import timezone
from django.utils.dateparse import parse_date
from loguru import logger
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

# ── Defer-on-miss status constants ──────────────────────────────────────
WARMUP_STATUS_IN_PROGRESS = "in_progress"
WARMUP_STATUS_READY = "ready"


def cached_view(
    cache_prefix: str,
    cache_params: Optional[List[str]] = None,
    end_date_param: Optional[str] = None,
    ttl: Optional[int] = None,
    should_cache_fn: Optional[Callable[[Any], bool]] = None,
    log_cache_operations: bool = True,
    # ── NEW: defer-on-miss ──────────────────────────────────────────
    defer_on_miss: bool = False,
    defer_retry_after: int = 30,
    defer_warmup_task: Optional[Callable] = None,
):
    """
    Decorator to automatically cache API view responses.

    Args:
        cache_prefix: Prefix for cache key (e.g., "explore_orgs")
        cache_params: List of query param names to include in cache key.
                     If None, includes all query params.
        end_date_param: Name of the end_date parameter for smart TTL.
                       If provided, uses historical (24h) or current (5m) TTL.
        ttl: Override TTL in seconds. If provided, ignores end_date_param.
        should_cache_fn: Optional function that receives the request and returns
                        bool indicating whether to cache. Useful for skipping
                        cache on search queries or complex filters.
        log_cache_operations: Whether to log cache hits/misses (default: True)
        defer_on_miss: If True, on cache miss return 202 Accepted and dispatch
                      a background warmup task instead of executing the heavy
                      query synchronously.  The frontend polls until the cache
                      is populated. (default: False)
        defer_retry_after: Seconds to tell the frontend to wait before retrying
                          (default: 30).  Sent as Retry-After header + body.
        defer_warmup_task: Optional callable to dispatch for on-demand warmup.
                          Receives (cache_key, request) and must trigger the
                          background compute+cache.  If None, the default
                          ``warm_single_window`` Celery task is used.

    Example:
        @cached_view(
            cache_prefix="explore_orgs",
            cache_params=["start_date", "end_date", "limit"],
            end_date_param="end_date"
        )
        @api_view(["GET"])
        def explore_organizations(request):
            # Your view logic here
            data = expensive_database_query()
            return Response(data)

        # Skip caching for search queries:
        @cached_view(
            cache_prefix="decisions",
            cache_params=["start_date", "end_date", "page"],
            end_date_param="end_date",
            should_cache_fn=lambda req: not req.GET.get("q")
        )
        def search_decisions(request):
            # Only caches when no search query
            ...

        # Defer heavy queries on cache miss:
        @cached_view(
            cache_prefix="da_top_entities",
            cache_params=["start_date", "end_date", "limit", "offset"],
            end_date_param="end_date",
            defer_on_miss=True,
            defer_retry_after=30,
        )
        def top_entities(request):
            return Response(compute_da_top_entities(...))
    """

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Check if we should cache this request
            if should_cache_fn and not should_cache_fn(request):
                if log_cache_operations:
                    logger.debug(
                        f"[Cache Decorator] Skipping cache for {cache_prefix} "
                        f"(should_cache_fn returned False)"
                    )
                return view_func(request, *args, **kwargs)

            # Build cache key from request params
            if cache_params is None:
                # Include all query params
                key_params = {k: v for k, v in request.GET.items()}
            else:
                # Only include specified params
                key_params = {k: request.GET.get(k, "") for k in cache_params}

            cache_key = response_cache.build_key(cache_prefix, **key_params)

            if log_cache_operations:
                logger.info(
                    f"[Cache Decorator] Checking cache for {cache_prefix} | "
                    f"key={cache_key}"
                )

            # Try to get from cache
            cached_response = response_cache.get(cache_key)
            if cached_response is not None:
                if log_cache_operations:
                    logger.info(
                        f"[Cache Decorator HIT] Returning cached data for {cache_prefix}"
                    )

                # Create Response with cached data and set up renderer
                response = Response(cached_response)
                response.accepted_renderer = JSONRenderer()
                response.accepted_media_type = "application/json"
                response.renderer_context = {}
                return response

            # ── Cache MISS ────────────────────────────────────────────
            if log_cache_operations:
                logger.info(
                    f"[Cache Decorator MISS] No cache found for {cache_prefix}, "
                )

            # ── defer_on_miss path ────────────────────────────────────
            if defer_on_miss:
                return _handle_defer_on_miss(
                    request=request,
                    cache_key=cache_key,
                    cache_prefix=cache_prefix,
                    defer_retry_after=defer_retry_after,
                    defer_warmup_task=defer_warmup_task,
                    view_func=view_func,
                    log_cache_operations=log_cache_operations,
                )

            # ── synchronous path (original behaviour) ─────────────────
            if log_cache_operations:
                logger.info("executing view...")

            # Execute the view
            response = view_func(request, *args, **kwargs)

            # Extract response data
            if isinstance(response, Response):
                # DRF Response object
                if response.status_code >= 400:
                    # Don't cache error responses
                    if log_cache_operations:
                        logger.debug(
                            f"[Cache Decorator] Not caching error response "
                            f"(status={response.status_code})"
                        )
                    return response
                response_data = response.data
            else:
                # Already a dict or other serializable type
                response_data = response

            # Determine end_date for smart TTL
            end_date = None
            if end_date_param and ttl is None:
                end_date_str = request.GET.get(end_date_param)
                if end_date_str:
                    try:
                        end_date_parsed = parse_date(end_date_str)
                        if end_date_parsed:
                            end_date = timezone.make_aware(
                                datetime.combine(end_date_parsed, datetime.max.time())
                            )
                    except (ValueError, TypeError) as e:
                        logger.warning(
                            f"[Cache Decorator] Failed to parse end_date: {e}"
                        )

            # Cache the response
            if log_cache_operations:
                logger.info(
                    f"[Cache Decorator SET] Caching response for {cache_prefix} | "
                    f"key={cache_key}"
                )

            response_cache.set(cache_key, response_data, end_date=end_date, timeout=ttl)

            return response

        return wrapper

    return decorator


def skip_cache_if_search(request) -> bool:
    """Helper function to skip caching when search query is present."""
    return not request.GET.get("q")


# ── defer_on_miss helpers ────────────────────────────────────────────────


def _handle_defer_on_miss(
    request,
    cache_key: str,
    cache_prefix: str,
    defer_retry_after: int,
    defer_warmup_task: Optional[Callable],
    view_func,
    log_cache_operations: bool,
) -> Response:
    """
    On cache miss with defer_on_miss=True, check warmup status and either:

    1. If warmup already in-progress → return 202 (avoids duplicate dispatch)
    2. If no warmup yet → mark in-progress, dispatch warmup, return 202

    Returns a 202 Accepted response telling the frontend to retry.
    """
    # ── Check if warmup is already in-progress ───────────────────────
    warmup_status = response_cache.get_warmup_status(cache_key)
    if warmup_status == WARMUP_STATUS_IN_PROGRESS:
        if log_cache_operations:
            logger.info(
                f"[Cache Decorator DEFER] Warmup already in-progress for "
                f"{cache_prefix} | key={cache_key}"
            )
        return _build_202_response(cache_key, defer_retry_after)

    # ── Mark warmup as in-progress ───────────────────────────────────
    response_cache.set_warmup_status(cache_key, WARMUP_STATUS_IN_PROGRESS)
    if log_cache_operations:
        logger.info(
            f"[Cache Decorator DEFER] Marked warmup in-progress for "
            f"{cache_prefix} | key={cache_key}"
        )

    # ── Dispatch warmup task ─────────────────────────────────────────
    _dispatch_warmup(
        cache_key=cache_key,
        cache_prefix=cache_prefix,
        request=request,
        defer_warmup_task=defer_warmup_task,
    )

    return _build_202_response(cache_key, defer_retry_after)


def _dispatch_warmup(
    cache_key: str,
    cache_prefix: str,
    request,
    defer_warmup_task: Optional[Callable],
) -> None:
    """
    Dispatch the background warmup task.

    If defer_warmup_task is provided, calls it with (cache_key, request).
    Otherwise falls back to the default Celery-based warm_single_window task.
    """
    if defer_warmup_task is not None:
        try:
            defer_warmup_task(cache_key=cache_key, request=request)
        except Exception as exc:
            logger.error(
                f"[Cache Decorator DEFER] Custom warmup task failed for "
                f"{cache_prefix}: {exc}"
            )
    else:
        # Default: dispatch via Celery warm_single_window
        try:
            from core.tasks.tasks_post_import import warm_single_window

            # Build a dict of request params to pass to the warmup task
            params = {k: v for k, v in request.GET.items()}
            # Include the cache_prefix so the task knows which compute/warm to call
            warm_single_window.delay(
                view_name=cache_prefix,
                params=params,
                cache_key=cache_key,
            )
        except Exception as exc:
            logger.error(
                f"[Cache Decorator DEFER] Failed to dispatch warm_single_window "
                f"for {cache_prefix}: {exc}"
            )


def _build_202_response(cache_key: str, retry_after: int) -> Response:
    """
    Build a 202 Accepted response telling the frontend data is being prepared.
    """
    response = Response(
        {
            "status": "warming",
            "message": "Data is being prepared. Retry shortly.",
            "retry_after": retry_after,
            "cache_key": cache_key,
        },
        status=202,
    )
    response["Retry-After"] = str(retry_after)
    response.accepted_renderer = JSONRenderer()
    response.accepted_media_type = "application/json"
    response.renderer_context = {}
    return response


# ── Existing helpers ─────────────────────────────────────────────────────


def skip_cache_if_complex_filters(request, exclude_params: List[str] = None) -> bool:
    """
    Helper function to skip caching when complex filters are present.

    Args:
        request: The request object
        exclude_params: List of param names that are OK to have (won't trigger skip)

    Example:
        @cached_view(
            cache_prefix="decisions",
            should_cache_fn=lambda req: skip_cache_if_complex_filters(
                req,
                exclude_params=["start_date", "end_date", "page", "page_size"]
            )
        )
    """
    exclude_params = exclude_params or []

    # Check if any params other than the excluded ones are present
    for param in request.GET.keys():
        if param not in exclude_params:
            return False  # Has complex filter, don't cache

    return True  # Only basic params, OK to cache
