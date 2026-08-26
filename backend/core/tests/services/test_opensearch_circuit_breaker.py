"""Unit tests for the OpenSearchService circuit breaker.

Verifies that when the OpenSearch container is absent (flag on but cluster
unreachable), the service degrades to disabled and every call short-circuits
instead of retrying connections.
"""

from unittest import mock

import pytest
from core.services.opensearch_service import OpenSearchService


@pytest.fixture(autouse=True)
def reset_circuit_breaker():
    """Reset the class-level circuit breaker state between tests."""
    OpenSearchService._connection_tested = False
    OpenSearchService._connection_test_time = 0
    OpenSearchService._connection_ok = False
    yield
    OpenSearchService._connection_tested = False
    OpenSearchService._connection_test_time = 0
    OpenSearchService._connection_ok = False


def _mock_feature_flags(enabled: bool):
    """Patch feature_flags.is_enabled to return `enabled` for the flag."""
    return mock.patch(
        "core.services.opensearch_service.feature_flags.is_enabled",
        return_value=enabled,
    )


def test_flag_off_disables_service():
    """Flag off → service disabled, no connection probe attempted."""
    with _mock_feature_flags(False):
        service = OpenSearchService()
    assert service.is_enabled is False
    # No probe should have run.
    assert OpenSearchService._connection_tested is False


def test_flag_on_but_unreachable_disables_service():
    """Flag on but cluster unreachable → service disabled (circuit open)."""
    with _mock_feature_flags(True):
        with mock.patch(
            "core.services.opensearch_service.requests.get",
            side_effect=ConnectionError("boom"),
        ):
            service = OpenSearchService()
    assert service.is_enabled is False
    assert OpenSearchService._connection_tested is True
    assert OpenSearchService._connection_ok is False


def test_flag_on_and_reachable_enables_service():
    """Flag on and cluster healthy → service enabled (circuit closed)."""
    health_response = mock.Mock()
    health_response.status_code = 200
    health_response.json.return_value = {"status": "green"}

    index_response = mock.Mock()
    index_response.status_code = 200

    count_response = mock.Mock()
    count_response.status_code = 200
    count_response.json.return_value = {"count": 5}

    with _mock_feature_flags(True):
        with mock.patch(
            "core.services.opensearch_service.requests.get",
            side_effect=[health_response, index_response, count_response],
        ):
            service = OpenSearchService()
    assert service.is_enabled is True
    assert OpenSearchService._connection_ok is True


def test_disabled_service_short_circuits_calls():
    """When disabled, index/search return empty results without network calls."""
    with _mock_feature_flags(False):
        service = OpenSearchService()

    with mock.patch(
        "core.services.opensearch_service.requests.post"
    ) as mock_post:
        assert service.index_document({"decision_id": 1, "ada": "X"}) is False
        assert service.search_documents("q") == {
            "hits": {"hits": [], "total": {"value": 0}}
        }
        assert service.document_exists("X") is False
        mock_post.assert_not_called()


def test_self_heals_after_ttl_expiry():
    """After TTL expiry, a successful probe re-enables the service."""
    # First probe fails → disabled.
    with _mock_feature_flags(True):
        with mock.patch(
            "core.services.opensearch_service.requests.get",
            side_effect=ConnectionError("boom"),
        ):
            OpenSearchService()

    assert OpenSearchService._connection_ok is False

    # Force TTL expiry.
    OpenSearchService._connection_test_time = 0

    health_response = mock.Mock()
    health_response.status_code = 200
    health_response.json.return_value = {"status": "green"}
    index_response = mock.Mock()
    index_response.status_code = 200
    count_response = mock.Mock()
    count_response.status_code = 200
    count_response.json.return_value = {"count": 5}

    with _mock_feature_flags(True):
        with mock.patch(
            "core.services.opensearch_service.requests.get",
            side_effect=[health_response, index_response, count_response],
        ):
            service = OpenSearchService()

    assert service.is_enabled is True
    assert OpenSearchService._connection_ok is True