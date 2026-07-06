"""
Unit tests for api/tasks/security.py — the async forensic-logging Celery task.

Covers:
  - Successful EndpointAccessLog creation with full fields
  - Graceful handling of missing user (User.DoesNotExist)
  - Graceful handling of DB errors (swallowed, logged)
  - is_flagged / flag_reason propagation
  - user_id=None skips user lookup
  - query_params with GET and POST data
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth import get_user_model

from api.tasks.security import persist_endpoint_access_log

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_user(db):
    """Create a real user in the test DB so User.objects.get() works."""
    return User.objects.create_user(
        username="testuser",
        email="test@example.com",
        password="testpass123",
    )


# ---------------------------------------------------------------------------
# Successful persistence
# ---------------------------------------------------------------------------


class TestPersistSuccess:
    """Tests that the task creates EndpointAccessLog rows correctly."""

    def test_creates_log_with_all_fields(self, db, mock_user):
        """All fields should be stored correctly in the DB."""
        persist_endpoint_access_log(
            ip_address="203.0.113.42",
            endpoint="/api/search/",
            method="GET",
            query_params={"GET": {"q": "test", "page": "1"}},
            user_agent="Mozilla/5.0",
            status_code=200,
            response_time_ms=45,
            user_id=mock_user.pk,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="203.0.113.42")
        assert log.endpoint == "/api/search/"
        assert log.method == "GET"
        assert log.query_params == {"GET": {"q": "test", "page": "1"}}
        assert log.user_agent == "Mozilla/5.0"
        assert log.status_code == 200
        assert log.response_time_ms == 45
        assert log.user == mock_user
        assert log.is_flagged is False
        assert log.flag_reason == ""

    def test_creates_log_with_flagged_true(self, db):
        """is_flagged=True and flag_reason are persisted."""
        persist_endpoint_access_log(
            ip_address="10.0.0.99",
            endpoint="/api/admin/",
            method="POST",
            query_params=None,
            user_agent=None,
            status_code=403,
            response_time_ms=12,
            user_id=None,
            is_flagged=True,
            flag_reason="velocity",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="10.0.0.99")
        assert log.is_flagged is True
        assert log.flag_reason == "velocity"
        assert log.status_code == 403
        assert log.user is None

    def test_creates_log_with_minimal_fields(self, db):
        """Task should work with only required fields and None for optionals."""
        persist_endpoint_access_log(
            ip_address="8.8.8.8",
            endpoint="/api/health/",
            method="HEAD",
            query_params=None,
            user_agent=None,
            status_code=None,
            response_time_ms=None,
            user_id=None,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="8.8.8.8")
        assert log.endpoint == "/api/health/"
        assert log.status_code is None
        assert log.response_time_ms is None
        assert log.query_params is None
        assert log.user_agent is None


# ---------------------------------------------------------------------------
# User resolution edge cases
# ---------------------------------------------------------------------------


class TestUserResolution:
    """Tests for how the task handles the user_id → User lookup."""

    def test_user_id_none_skips_lookup(self, db):
        """When user_id is None, the task should not attempt a DB lookup."""
        persist_endpoint_access_log(
            ip_address="1.2.3.4",
            endpoint="/api/public/",
            method="GET",
            query_params=None,
            user_agent=None,
            status_code=200,
            response_time_ms=5,
            user_id=None,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="1.2.3.4")
        assert log.user is None

    def test_user_does_not_exist_is_graceful(self, db):
        """When the user PK doesn't exist, the task should not crash."""
        # Pick an ID that definitely doesn't exist in a fresh test DB
        nonexistent_id = 999999

        # Should not raise
        persist_endpoint_access_log(
            ip_address="4.3.2.1",
            endpoint="/api/x/",
            method="GET",
            query_params=None,
            user_agent=None,
            status_code=404,
            response_time_ms=10,
            user_id=nonexistent_id,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="4.3.2.1")
        assert log.user is None  # gracefully set to None


# ---------------------------------------------------------------------------
# Error resilience
# ---------------------------------------------------------------------------


class TestErrorResilience:
    """Tests that the task swallows DB errors instead of crashing the worker."""

    def test_db_error_is_swallowed(self, db):
        """If EndpointAccessLog.objects.create raises, the task should
        log the error and not propagate the exception."""
        with patch(
            "api.models.EndpointAccessLog.objects.create",
            side_effect=Exception("DB connection lost"),
        ):
            # Should NOT raise — the task catches Exception
            persist_endpoint_access_log(
                ip_address="9.9.9.9",
                endpoint="/api/fail/",
                method="GET",
                query_params=None,
                user_agent=None,
                status_code=500,
                response_time_ms=100,
                user_id=None,
                is_flagged=False,
                flag_reason="",
            )

        # If we get here, the exception was swallowed — test passes
        assert True

    def test_integrity_error_is_swallowed(self, db):
        """Even integrity errors (e.g. duplicate unique constraint, though
        unlikely for this model) should not crash the worker."""
        from django.db import IntegrityError

        with patch(
            "api.models.EndpointAccessLog.objects.create",
            side_effect=IntegrityError("constraint violation"),
        ):
            persist_endpoint_access_log(
                ip_address="9.9.9.9",
                endpoint="/api/fail2/",
                method="GET",
                query_params=None,
                user_agent=None,
                status_code=500,
                response_time_ms=100,
                user_id=None,
                is_flagged=False,
                flag_reason="",
            )

        assert True


# ---------------------------------------------------------------------------
# query_params edge cases
# ---------------------------------------------------------------------------


class TestQueryParams:
    """Tests for how query_params are stored."""

    def test_get_params_only(self, db):
        persist_endpoint_access_log(
            ip_address="5.5.5.5",
            endpoint="/api/search/",
            method="GET",
            query_params={"GET": {"q": "hello", "lang": "el"}},
            user_agent=None,
            status_code=200,
            response_time_ms=20,
            user_id=None,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="5.5.5.5")
        assert log.query_params == {"GET": {"q": "hello", "lang": "el"}}

    def test_post_params(self, db):
        persist_endpoint_access_log(
            ip_address="6.6.6.6",
            endpoint="/api/submit/",
            method="POST",
            query_params={"POST": {"name": "value"}},
            user_agent=None,
            status_code=201,
            response_time_ms=30,
            user_id=None,
            is_flagged=True,
            flag_reason="strikes",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="6.6.6.6")
        assert log.query_params == {"POST": {"name": "value"}}
        assert log.is_flagged is True

    def test_mixed_get_and_post(self, db):
        """The middleware may pass both GET and POST keys."""
        persist_endpoint_access_log(
            ip_address="7.7.7.7",
            endpoint="/api/mixed/",
            method="POST",
            query_params={"GET": {"page": "1"}, "POST": {"action": "save"}},
            user_agent=None,
            status_code=200,
            response_time_ms=25,
            user_id=None,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="7.7.7.7")
        assert log.query_params["GET"] == {"page": "1"}
        assert log.query_params["POST"] == {"action": "save"}

    def test_query_params_none(self, db):
        """None query_params should be stored as None."""
        persist_endpoint_access_log(
            ip_address="8.8.4.4",
            endpoint="/api/noparams/",
            method="GET",
            query_params=None,
            user_agent=None,
            status_code=204,
            response_time_ms=5,
            user_id=None,
            is_flagged=False,
            flag_reason="",
        )

        from api.models import EndpointAccessLog

        log = EndpointAccessLog.objects.get(ip_address="8.8.4.4")
        assert log.query_params is None
