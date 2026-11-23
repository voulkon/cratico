"""
Tests for the @cached_view options added in the organization-page perf work:
``cache_path_params``, ``ttl_fn``, and per-request ``defer_on_miss``.
"""

from unittest.mock import patch

from django.http import HttpRequest, QueryDict
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from core.decorators.cache_decorator import cached_view
from core.services.response_cache_service import response_cache


def _request(params=None):
    request = HttpRequest()
    request.method = "GET"
    request.GET = QueryDict("", mutable=True)
    for key, value in (params or {}).items():
        request.GET[key] = value
    return request


def _make_view(**decorator_kwargs):
    @cached_view(log_cache_operations=False, **decorator_kwargs)
    @api_view(["GET"])
    @permission_classes([AllowAny])
    def endpoint(request, organization_uid=None):
        return Response({"ok": True})

    return endpoint


class TestCachePathParams:
    def test_path_param_is_part_of_the_cache_key(self):
        view = _make_view(
            cache_prefix="test_path_params",
            cache_params=["q"],
            cache_path_params=["organization_uid"],
        )

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ) as mock_set:
            response = view(_request({"q": "x"}), organization_uid="ORG1")

        assert response.status_code == 200
        cache_key = mock_set.call_args.args[0]
        assert "organization_uid=ORG1" in cache_key
        assert "q=x" in cache_key

    def test_missing_path_param_falls_back_to_empty(self):
        view = _make_view(
            cache_prefix="test_path_params_missing",
            cache_params=[],
            cache_path_params=["organization_uid"],
        )

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ) as mock_set:
            response = view(_request())

        assert response.status_code == 200
        assert "organization_uid=" in mock_set.call_args.args[0]


class TestTtlFn:
    def test_ttl_fn_overrides_static_ttl(self):
        view = _make_view(
            cache_prefix="test_ttl_fn",
            cache_params=[],
            ttl=999,
            ttl_fn=lambda request: 123,
        )

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ) as mock_set:
            response = view(_request())

        assert response.status_code == 200
        assert mock_set.call_args.kwargs["timeout"] == 123

    def test_ttl_fn_none_falls_back_to_smart_end_date_ttl(self):
        view = _make_view(
            cache_prefix="test_ttl_fn_fallback",
            cache_params=["end_date"],
            end_date_param="end_date",
            ttl_fn=lambda request: None,
        )

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ) as mock_set:
            response = view(_request({"end_date": "2020-01-01"}))

        assert response.status_code == 200
        assert mock_set.call_args.kwargs["timeout"] is None
        assert mock_set.call_args.kwargs["end_date"] is not None


class TestCallableDeferOnMiss:
    def test_predicate_decides_per_request(self):
        view = _make_view(
            cache_prefix="test_defer_callable",
            cache_params=[],
            defer_on_miss=lambda request: request.GET.get("defer") == "1",
        )

        warming = Response({"status": "warming"}, status=202)

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ), patch(
            "core.decorators.cache_decorator._handle_defer_on_miss",
            return_value=warming,
        ) as defer_handler:
            deferred = view(_request({"defer": "1"}))

        assert deferred.status_code == 202
        defer_handler.assert_called_once()

        with patch.object(response_cache, "get", return_value=None), patch.object(
            response_cache, "set"
        ), patch(
            "core.decorators.cache_decorator._handle_defer_on_miss"
        ) as defer_handler:
            synchronous = view(_request())

        assert synchronous.status_code == 200
        defer_handler.assert_not_called()
