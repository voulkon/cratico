"""
Shared warmup helpers for analytics pre-calculation.

Provides generic functions for the common "compute once, slice into pages,
cache each page" pattern used by all warm_*_window functions.
"""

from __future__ import annotations

from datetime import date
from typing import Callable

from loguru import logger

from ._helpers import response_cache


def cache_paginated_offset(
    *,
    cache_prefix: str,
    full_results: list,
    total_count: int,
    page_size: int,
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    build_page_data: Callable[[list, int, int, int], dict],
    build_empty_data: Callable[[int], dict],
    extra_cache_kwargs: dict | None = None,
    use_historical_ttl: bool = False,
    log_label: str = "",
    max_limit: int = 0,
) -> int:
    """
    Slice ``full_results`` into ``page_size`` batches and cache each one
    under the offset+limit Redis key for ``cache_prefix``.

    Used by: top_payments, top_direct_assignments, top_by_amount,
             da_top_pairs, da_top_entities, da_top_orgs, explore_orgs.

    Args:
        cache_prefix:       Redis key prefix (e.g. "top_payments").
        full_results:       Pre-computed result list from a single
                            compute_* call with a large limit.
        total_count:        Total items in the DB (may exceed len(full_results)).
        page_size:          Frontend's page size.
        start_date_str:     ISO date string for the cache key.
        end_date_str:       ISO date string for the cache key.
        end_date:           Python date for TTL selection.
        build_page_data:    ``(page_results, offset, page_num, total_pages) -> dict``
                            Builds the page-specific response dict.
        build_empty_data:   ``(page_size) -> dict``
                            Builds the empty page-1 fallback dict.
        extra_cache_kwargs: Merged into every ``response_cache.build_key()`` call
                            (e.g. ``{"sort_by": "amount_desc"}``).
        use_historical_ttl: If True, pass ``timeout=response_cache.EXPIRE_HISTORICAL``.
        log_label:          Human-readable label for the log line.
        max_limit:          The max_limit used (for the log line).

    Returns:
        Number of pages cached (including empty fallback).
    """
    extra = extra_cache_kwargs or {}
    timeout = response_cache.EXPIRE_HISTORICAL if use_historical_ttl else None

    cached = 0
    for offset in range(0, len(full_results), page_size):
        page_results = full_results[offset : offset + page_size]
        if not page_results:
            break

        page = (offset // page_size) + 1
        total_pages = (
            max(1, (total_count + page_size - 1) // page_size) if page_size else 1
        )
        page_data = build_page_data(page_results, offset, page, total_pages)

        cache_key = response_cache.build_key(
            cache_prefix,
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset=str(offset),
            **extra,
        )
        kwargs = {"end_date": end_date}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response_cache.set(cache_key, page_data, **kwargs)
        cached += 1

    # ── always cache at least page 1 (even if empty) so subsequent
    #     requests get cache hits instead of triggering defer_on_miss ─
    if cached == 0:
        empty_data = build_empty_data(page_size)
        empty_key = response_cache.build_key(
            cache_prefix,
            start_date=start_date_str,
            end_date=end_date_str,
            limit=str(page_size),
            offset="0",
            **extra,
        )
        kwargs = {"end_date": end_date}
        if timeout is not None:
            kwargs["timeout"] = timeout
        response_cache.set(empty_key, empty_data, **kwargs)
        cached += 1

    logger.info(
        f"[AnalyticsPrecalc] Warmed {log_label or cache_prefix} "
        f"[{start_date_str} → {end_date_str}] {cached} pages "
        f"(max_limit={max_limit}, page_size={page_size}, total={total_count})"
    )

    return cached


def cache_single_key(
    *,
    cache_prefix: str,
    data: dict,
    start_date_str: str,
    end_date_str: str,
    end_date: date,
    extra_cache_kwargs: dict | None = None,
    log_label: str = "",
    log_detail: str = "",
) -> None:
    """
    Cache a single result under one Redis key (no pagination).

    Used by: explore_decision_types, explore_statistics.

    Args:
        cache_prefix:       Redis key prefix.
        data:               The response dict to cache.
        start_date_str:     ISO date string for the cache key.
        end_date_str:       ISO date string for the cache key.
        end_date:           Python date for TTL selection.
        extra_cache_kwargs: Merged into ``response_cache.build_key()``.
        log_label:          Human-readable label for the log line.
        log_detail:         Additional info for the log line.
    """
    extra = extra_cache_kwargs or {}

    cache_key = response_cache.build_key(
        cache_prefix,
        start_date=start_date_str,
        end_date=end_date_str,
        **extra,
    )
    response_cache.set(cache_key, data, end_date=end_date, timeout=response_cache.EXPIRE_HISTORICAL)

    detail = f" ({log_detail})" if log_detail else ""
    logger.info(
        f"[AnalyticsPrecalc] Warmed {log_label or cache_prefix} "
        f"[{start_date_str} → {end_date_str}]{detail}"
    )
