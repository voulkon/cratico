"""
Tests for defer_on_miss cache warming.

Covers:
  - cache_decorator._handle_defer_on_miss behaviour
  - ResponseCacheService warmup status get/set/clear
  - warm_single_window Celery task
  - redis_keys get_warmup_status_key
  - Warmup registry completeness
"""

from unittest.mock import MagicMock, patch

import pytest
from django.http import HttpRequest, QueryDict
from rest_framework.response import Response

from core.decorators.cache_decorator import (
    WARMUP_STATUS_IN_PROGRESS,
    WARMUP_STATUS_READY,
    _build_202_response,
    _handle_defer_on_miss,
)
from core.services.response_cache_service import response_cache


# ── Helpers ────────────────────────────────────────────────────────────────


def make_get_request(params: dict = None) -> HttpRequest:
    """Build a minimal GET request with query params."""
    request = HttpRequest()
    request.method = "GET"
    request.GET = QueryDict("", mutable=True)
    if params:
        for k, v in params.items():
            request.GET[k] = v
    return request


# ═══════════════════════════════════════════════════════════════════════════
# get_warmup_status_key
# ═══════════════════════════════════════════════════════════════════════════


class TestGetWarmupStatusKey:
    def test_prefix_is_added(self):
        from api.redis_keys import get_warmup_status_key

        cache_key = "api_cache:da:explore_orgs:end_date=2025-01-01:start_date=2025-01-01"
        result = get_warmup_status_key(cache_key)

        assert result.startswith("warmup:")
        assert result == f"warmup:{cache_key}"

    def test_roundtrip_prefix(self):
        """The warmup status key should contain the original cache key."""
        from api.redis_keys import get_warmup_status_key

        cache_key = "api_cache:da:da_top_entities:end_date=2026-06-23:limit=20:offset=0:sort_by=amount:start_date=2026-06-22"
        warmup_key = get_warmup_status_key(cache_key)

        # The warmup key should end with the cache key
        assert warmup_key.endswith(cache_key)


# ═══════════════════════════════════════════════════════════════════════════
# ResponseCacheService warmup status
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmupStatusCache:
    """Tests for get_warmup_status / set_warmup_status / clear_warmup_status.

    These use the real Django cache (configured to use LocMemCache in tests).
    """

    def test_get_returns_none_when_not_set(self):
        key = "api_cache:da:test_view:end_date=2025-01-01"
        assert response_cache.get_warmup_status(key) is None

    def test_set_and_get_in_progress(self):
        key = "api_cache:da:test_view:end_date=2025-01-01"
        response_cache.set_warmup_status(key, WARMUP_STATUS_IN_PROGRESS)

        assert response_cache.get_warmup_status(key) == WARMUP_STATUS_IN_PROGRESS

    def test_set_and_get_ready(self):
        key = "api_cache:da:test_view:end_date=2025-01-01"
        response_cache.set_warmup_status(key, WARMUP_STATUS_READY)

        assert response_cache.get_warmup_status(key) == WARMUP_STATUS_READY

    def test_clear_removes_status(self):
        key = "api_cache:da:test_view:end_date=2025-01-01"
        response_cache.set_warmup_status(key, WARMUP_STATUS_IN_PROGRESS)
        response_cache.clear_warmup_status(key)

        assert response_cache.get_warmup_status(key) is None

    def test_different_keys_are_independent(self):
        key_a = "api_cache:da:view_a:end_date=2025-01-01"
        key_b = "api_cache:da:view_b:end_date=2025-01-01"

        response_cache.set_warmup_status(key_a, WARMUP_STATUS_IN_PROGRESS)
        response_cache.set_warmup_status(key_b, WARMUP_STATUS_READY)

        assert response_cache.get_warmup_status(key_a) == WARMUP_STATUS_IN_PROGRESS
        assert response_cache.get_warmup_status(key_b) == WARMUP_STATUS_READY

    def test_custom_timeout(self):
        """set_warmup_status should accept an optional timeout."""
        key = "api_cache:da:test:end_date=2025-01-01"
        response_cache.set_warmup_status(key, "in_progress", timeout=60)
        assert response_cache.get_warmup_status(key) == "in_progress"


# ═══════════════════════════════════════════════════════════════════════════
# _build_202_response
# ═══════════════════════════════════════════════════════════════════════════


class TestBuild202Response:
    def test_status_code_is_202(self):
        resp = _build_202_response("my_key", 30)
        assert resp.status_code == 202

    def test_body_contains_status_warming(self):
        resp = _build_202_response("my_key", 30)
        assert resp.data["status"] == "warming"

    def test_body_contains_cache_key(self):
        resp = _build_202_response("api_cache:da:test:foo=bar", 30)
        assert resp.data["cache_key"] == "api_cache:da:test:foo=bar"

    def test_body_contains_retry_after(self):
        resp = _build_202_response("my_key", 45)
        assert resp.data["retry_after"] == 45

    def test_retry_after_header_is_set(self):
        resp = _build_202_response("my_key", 20)
        assert resp["Retry-After"] == "20"

    def test_different_retry_after_values(self):
        for seconds in [10, 30, 60, 120]:
            resp = _build_202_response("key", seconds)
            assert resp.data["retry_after"] == seconds
            assert resp["Retry-After"] == str(seconds)

    def test_message_is_informative(self):
        resp = _build_202_response("key", 30)
        assert "Data is being prepared" in resp.data["message"]


# ═══════════════════════════════════════════════════════════════════════════
# _handle_defer_on_miss
# ═══════════════════════════════════════════════════════════════════════════


class TestHandleDeferOnMiss:
    @pytest.fixture(autouse=True)
    def setup(self):
        """Clear warmup status keys before each test."""
        self.cache_key = "api_cache:da:test_view:end_date=2025-01-01:start_date=2025-01-01"
        response_cache.clear_warmup_status(self.cache_key)
        yield
        response_cache.clear_warmup_status(self.cache_key)

    def test_returns_202_when_no_warmup_in_progress(self):
        """First miss should mark in-progress, dispatch, and return 202."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        response = _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        assert response.status_code == 202
        assert response.data["status"] == "warming"

    def test_marks_warmup_in_progress(self):
        """After the first call, warmup_status should be in_progress."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        assert (
            response_cache.get_warmup_status(self.cache_key)
            == WARMUP_STATUS_IN_PROGRESS
        )

    def test_dispatches_warmup_task(self):
        """The defer_warmup_task callable should be invoked."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        mock_warmup.assert_called_once_with(cache_key=self.cache_key, request=request)

    def test_does_not_dispatch_when_already_in_progress(self):
        """Second call while warmup is in-progress should NOT re-dispatch."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        # First call
        _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        # Second call — should NOT dispatch again
        _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        # Warmup should only have been dispatched once
        assert mock_warmup.call_count == 1

    def test_both_calls_return_202(self):
        """Both first and second call should return 202."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        resp1 = _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        resp2 = _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        assert resp1.status_code == 202
        assert resp2.status_code == 202

    def test_view_is_not_executed(self):
        """The original view function should NEVER be called."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        mock_view.assert_not_called()

    def test_different_cache_keys_are_independent(self):
        """Two different keys should both dispatch independently."""
        key_a = "api_cache:da:view_a:end_date=2025-01-01:start_date=2025-01-01"
        key_b = "api_cache:da:view_b:end_date=2025-02-01:start_date=2025-02-01"

        response_cache.clear_warmup_status(key_a)
        response_cache.clear_warmup_status(key_b)

        request_a = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )
        request_b = make_get_request(
            {"start_date": "2025-02-01", "end_date": "2025-02-01"}
        )

        mock_view = MagicMock()
        mock_warmup = MagicMock()

        # Dispatch for key_a
        _handle_defer_on_miss(
            request=request_a,
            cache_key=key_a,
            cache_prefix="view_a",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        # Dispatch for key_b — should proceed (different key)
        _handle_defer_on_miss(
            request=request_b,
            cache_key=key_b,
            cache_prefix="view_b",
            defer_retry_after=30,
            defer_warmup_task=mock_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        assert mock_warmup.call_count == 2

        response_cache.clear_warmup_status(key_a)
        response_cache.clear_warmup_status(key_b)

    def test_warmup_task_exception_is_handled(self):
        """If the custom warmup task raises, it should be caught and not propagate."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()

        def failing_warmup(cache_key, request):
            raise RuntimeError("Warmup failed!")

        # Should not raise
        response = _handle_defer_on_miss(
            request=request,
            cache_key=self.cache_key,
            cache_prefix="test_view",
            defer_retry_after=30,
            defer_warmup_task=failing_warmup,
            view_func=mock_view,
            log_cache_operations=True,
        )

        # Still returns 202
        assert response.status_code == 202

    def test_no_custom_warmup_task_dispatches_celery(self):
        """When defer_warmup_task is None, the default Celery task should be dispatched."""
        request = make_get_request(
            {"start_date": "2025-01-01", "end_date": "2025-01-01"}
        )

        mock_view = MagicMock()

        with patch(
            "core.tasks.tasks_post_import.warm_single_window.delay"
        ) as mock_delay:
            _handle_defer_on_miss(
                request=request,
                cache_key=self.cache_key,
                cache_prefix="test_view",
                defer_retry_after=30,
                defer_warmup_task=None,
                view_func=mock_view,
                log_cache_operations=True,
            )

            mock_delay.assert_called_once()
            call_kwargs = mock_delay.call_args[1]
            assert call_kwargs["view_name"] == "test_view"
            assert call_kwargs["cache_key"] == self.cache_key


# ═══════════════════════════════════════════════════════════════════════════
# warm_single_window Celery task
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmSingleWindow:
    def test_unknown_view_returns_error(self):
        """Calling with an unregistered view_name should return status=unknown_view."""
        from core.tasks.tasks_post_import import warm_single_window

        result = warm_single_window(
            view_name="nonexistent_view",
            params={"start_date": "2025-01-01", "end_date": "2025-01-01"},
            cache_key="api_cache:da:nonexistent:end_date=2025-01-01",
        )

        assert result["status"] == "unknown_view"

    def test_missing_date_params_returns_error(self):
        """Missing start_date or end_date should return status=missing_date_params."""
        from core.tasks.tasks_post_import import warm_single_window

        result = warm_single_window(
            view_name="explore_orgs",
            params={},
            cache_key="api_cache:da:explore_orgs:",
        )

        assert result["status"] == "missing_date_params"

    def test_missing_start_date_only(self):
        """Only end_date provided → still missing."""
        from core.tasks.tasks_post_import import warm_single_window

        result = warm_single_window(
            view_name="explore_orgs",
            params={"end_date": "2025-01-01"},
            cache_key="api_cache:da:explore_orgs:end_date=2025-01-01",
        )

        assert result["status"] == "missing_date_params"

    @patch.dict(
        "core.services.analytics_precalc_service.WARMUP_REGISTRY",
        clear=True,
    )
    def test_valid_view_calls_warm_function(self):
        """A registered view should call its warm function."""
        from core.services.analytics_precalc_service import WARMUP_REGISTRY
        from core.tasks.tasks_post_import import warm_single_window

        mock_warm = MagicMock(return_value=None)
        WARMUP_REGISTRY["explore_orgs"] = mock_warm

        result = warm_single_window(
            view_name="explore_orgs",
            params={"start_date": "2025-01-01", "end_date": "2025-01-01"},
            cache_key="api_cache:da:explore_orgs:end_date=2025-01-01:start_date=2025-01-01",
        )

        mock_warm.assert_called_once()
        call_kwargs = mock_warm.call_args[1]
        assert call_kwargs["start_date_str"] == "2025-01-01"
        assert call_kwargs["end_date_str"] == "2025-01-01"

        assert result["status"] == "warmed"

    @patch.dict(
        "core.services.analytics_precalc_service.WARMUP_REGISTRY",
        clear=True,
    )
    def test_warmup_failure_clears_status(self):
        """If the warm function raises, the in-progress status is cleared."""
        from core.services.analytics_precalc_service import WARMUP_REGISTRY
        from core.tasks.tasks_post_import import warm_single_window

        mock_warm = MagicMock(side_effect=RuntimeError("DB is down"))
        WARMUP_REGISTRY["explore_orgs"] = mock_warm

        cache_key = "api_cache:da:explore_orgs:end_date=2025-01-01:start_date=2025-01-01"
        # Set in_progress first
        response_cache.set_warmup_status(cache_key, WARMUP_STATUS_IN_PROGRESS)

        result = warm_single_window(
            view_name="explore_orgs",
            params={"start_date": "2025-01-01", "end_date": "2025-01-01"},
            cache_key=cache_key,
        )

        assert result["status"] == "failed"
        # Status should have been cleared
        assert response_cache.get_warmup_status(cache_key) is None

    @patch.dict(
        "core.services.analytics_precalc_service.WARMUP_REGISTRY",
        clear=True,
    )
    def test_success_sets_status_ready(self):
        """On success, warmup status is set to 'ready'."""
        from core.services.analytics_precalc_service import WARMUP_REGISTRY
        from core.tasks.tasks_post_import import warm_single_window

        mock_warm = MagicMock(return_value=None)
        WARMUP_REGISTRY["explore_orgs"] = mock_warm

        cache_key = "api_cache:da:explore_orgs:end_date=2025-01-01:start_date=2025-01-01"

        warm_single_window(
            view_name="explore_orgs",
            params={"start_date": "2025-01-01", "end_date": "2025-01-01"},
            cache_key=cache_key,
        )

        assert response_cache.get_warmup_status(cache_key) == "ready"


# ═══════════════════════════════════════════════════════════════════════════
# WARMUP_REGISTRY completeness
# ═══════════════════════════════════════════════════════════════════════════


class TestWarmupRegistry:
    """Ensure every @cached_view with defer_on_miss has a warm function registered."""

    def test_all_defer_views_have_warmup(self):
        from core.services.analytics_precalc_service import WARMUP_REGISTRY

        expected_views = {
            "explore_orgs",
            "da_top_pairs",
            "explore_decisions",
            "da_top_entities",
            "da_top_orgs",
            "explore_decision_types",
            "explore_statistics",
        }

        registered = set(WARMUP_REGISTRY.keys())

        missing = expected_views - registered
        assert not missing, f"Views missing from WARMUP_REGISTRY: {missing}"

        extra = registered - expected_views
        # Extra is fine — but let's just note them
        if extra:
            print(f"Note: extra views in WARMUP_REGISTRY: {extra}")

    def test_registry_values_are_callable(self):
        from core.services.analytics_precalc_service import WARMUP_REGISTRY

        for view_name, warm_fn in WARMUP_REGISTRY.items():
            assert callable(warm_fn), f"WARMUP_REGISTRY['{view_name}'] is not callable"


# ═══════════════════════════════════════════════════════════════════════════
# @cached_view integration — defer_on_miss path
# ═══════════════════════════════════════════════════════════════════════════


class TestCachedViewDeferOnMiss:
    """
    Test the full @cached_view(defer_on_miss=True) flow.

    We use a minimal view + mock to verify the decorator branches correctly.
    """

    def test_cache_hit_returns_200_and_bypasses_defer(self):
        """When data is in cache, defer_on_miss is irrelevant — return 200."""
        from core.decorators.cache_decorator import cached_view
        from rest_framework.decorators import api_view, permission_classes
        from rest_framework.permissions import AllowAny

        view_name = "test_defer_hit"

        @cached_view(
            cache_prefix=view_name,
            cache_params=["test_param"],
            defer_on_miss=True,
            log_cache_operations=False,
        )
        @api_view(["GET"])
        @permission_classes([AllowAny])
        def test_view(request):
            return Response({"from": "view"})

        # Pre-populate cache
        cache_key = response_cache.build_key(view_name, test_param="hello")
        response_cache.set(cache_key, {"from": "cache"})

        request = make_get_request({"test_param": "hello"})

        response = test_view(request)

        assert response.status_code == 200
        assert response.data == {"from": "cache"}

        # Cleanup
        response_cache.invalidate_prefix(view_name)

    @patch("core.decorators.cache_decorator._handle_defer_on_miss")
    def test_cache_miss_calls_defer_handler(self, mock_handler):
        """On cache miss with defer_on_miss=True, _handle_defer_on_miss is called."""
        from core.decorators.cache_decorator import cached_view
        from rest_framework.decorators import api_view, permission_classes
        from rest_framework.permissions import AllowAny

        view_name = "test_defer_miss"

        # Return a 202 from the handler
        mock_handler.return_value = Response(
            {"status": "warming"}, status=202
        )

        @cached_view(
            cache_prefix=view_name,
            cache_params=["test_param"],
            defer_on_miss=True,
            log_cache_operations=False,
        )
        @api_view(["GET"])
        @permission_classes([AllowAny])
        def test_view(request):
            return Response({"from": "view"})

        # Ensure cache is empty
        response_cache.invalidate_prefix(view_name)

        request = make_get_request({"test_param": "world"})

        response = test_view(request)

        assert response.status_code == 202
        mock_handler.assert_called_once()

    def test_defer_on_miss_false_still_runs_view_synchronously(self):
        """Without defer_on_miss, cache miss runs the view normally."""
        from core.decorators.cache_decorator import cached_view
        from rest_framework.decorators import api_view, permission_classes
        from rest_framework.permissions import AllowAny

        view_name = "test_sync_miss"

        @cached_view(
            cache_prefix=view_name,
            cache_params=["test_param"],
            defer_on_miss=False,
            log_cache_operations=False,
        )
        @api_view(["GET"])
        @permission_classes([AllowAny])
        def test_view(request):
            return Response({"from": "view"})

        # Ensure cache is empty
        response_cache.invalidate_prefix(view_name)

        request = make_get_request({"test_param": "sync"})

        response = test_view(request)

        assert response.status_code == 200
        assert response.data == {"from": "view"}


# ═══════════════════════════════════════════════════════════════════════════
# Default Celery dispatch (no custom warmup task)
# ═══════════════════════════════════════════════════════════════════════════


class TestDefaultCeleryDispatch:
    """When defer_warmup_task is None, the decorator dispatches via Celery."""

    def test_dispatch_includes_request_params(self):
        """The Celery task should receive all request GET params."""
        from core.decorators.cache_decorator import _dispatch_warmup

        request = make_get_request(
            {
                "start_date": "2025-06-01",
                "end_date": "2025-06-30",
                "limit": "20",
                "offset": "0",
                "sort_by": "amount",
            }
        )

        with patch(
            "core.tasks.tasks_post_import.warm_single_window.delay"
        ) as mock_delay:
            _dispatch_warmup(
                cache_key="api_cache:da:test:end_date=2025-06-30:limit=20:offset=0:sort_by=amount:start_date=2025-06-01",
                cache_prefix="da_top_entities",
                request=request,
                defer_warmup_task=None,
            )

            mock_delay.assert_called_once()
            call_kwargs = mock_delay.call_args[1]
            assert call_kwargs["view_name"] == "da_top_entities"
            assert call_kwargs["params"]["start_date"] == "2025-06-01"
            assert call_kwargs["params"]["end_date"] == "2025-06-30"
            assert call_kwargs["params"]["limit"] == "20"
            assert call_kwargs["params"]["offset"] == "0"
            assert call_kwargs["params"]["sort_by"] == "amount"
