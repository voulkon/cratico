"""
Tests for per-request cache statistics (collector + summary middleware).
"""

from unittest.mock import MagicMock, patch

from api.middleware.cache_stats import CacheStatsMiddleware
from core.services.cache_stats import (
    get_cache_stats,
    record_cache_access,
    start_collecting,
    stop_collecting,
)
from core.services.response_cache_service import response_cache


def test_records_hits_and_misses_for_current_context():
    start_collecting()

    record_cache_access("api_cache:da:explore_orgs:start=1", hit=True)
    record_cache_access("api_cache:da:top_pairs:start=1", hit=False)

    accesses = stop_collecting()
    assert [(a.view, a.hit) for a in accesses] == [
        ("explore_orgs", True),
        ("top_pairs", False),
    ]


def test_lookups_are_ignored_when_not_collecting():
    stop_collecting()

    record_cache_access("api_cache:da:explore_orgs:start=1", hit=True)

    assert get_cache_stats() == ()


def test_stop_collecting_resets_the_collector():
    start_collecting()
    record_cache_access("api_cache:da:explore_orgs:start=1", hit=True)

    stop_collecting()

    assert get_cache_stats() == ()


def test_middleware_logs_single_summary_line():
    request = MagicMock(method="GET", path="/api/v1/homepage/")

    def get_response(_request):
        record_cache_access("api_cache:da:explore_orgs:a=1", hit=True)
        record_cache_access("api_cache:da:top_pairs:a=1", hit=False)
        return MagicMock()

    middleware = CacheStatsMiddleware(get_response)

    with patch("api.middleware.cache_stats.logger") as mock_logger:
        middleware(request)

    mock_logger.info.assert_called_once()
    message = mock_logger.info.call_args.args[0]
    assert "lookups=2 hits=1 misses=1" in message
    assert "hit=[explore_orgs]" in message
    assert "miss=[top_pairs]" in message


def test_middleware_skips_summary_without_cache_lookups():
    request = MagicMock(method="GET", path="/api/v1/health/")
    middleware = CacheStatsMiddleware(lambda _request: MagicMock())

    with patch("api.middleware.cache_stats.logger") as mock_logger:
        middleware(request)

    mock_logger.info.assert_not_called()


def test_response_cache_get_records_hit():
    start_collecting()

    with patch("core.services.response_cache_service.cache") as mock_cache:
        mock_cache.get.return_value = {"data": 1}
        result = response_cache.get("api_cache:da:explore_orgs:a=1")

    assert result == {"data": 1}
    assert stop_collecting()[0].hit is True


def test_response_cache_get_logs_exception_and_treats_as_miss():
    start_collecting()

    with (
        patch("core.services.response_cache_service.cache") as mock_cache,
        patch("core.services.response_cache_service.logger") as mock_logger,
    ):
        mock_cache.get.side_effect = RuntimeError("redis unavailable")
        result = response_cache.get("api_cache:da:explore_orgs:a=1")

    assert result is None
    mock_logger.exception.assert_called_once()
    assert stop_collecting()[0].hit is False
