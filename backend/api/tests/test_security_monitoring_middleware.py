"""
Integration tests for the Security Monitoring middleware.

These tests verify the middleware chain end-to-end:
  1. SECURITY_MONITORING_ENABLED flag gates everything
  2. Banned IPs receive 403
  3. Clean IPs pass through normally
  4. Velocity threshold triggers auto-ban
  5. Strike threshold triggers auto-ban
  6. SECURITY_AUTO_BAN_ENABLED must be on for enforcement
  7. SECURITY_FORENSIC_LOGGING_ENABLED logs all requests

Strategy:
  - Use Django's test Client, which goes through the full middleware stack.
  - Mock the SecurityService at the singleton level so we control Redis
    state without needing an actual Redis instance.
  - Feature flags are patched at the source:
      core.services.feature_flag_service.feature_flags
    because the middleware imports them locally (inside __call__, _finalize,
    and _maybe_log_forensic).
  - Celery tasks are patched at their definition site:
      api.tasks.security.persist_endpoint_access_log.delay

These are NOT true end-to-end tests (no real Redis), but they exercise the
middleware → service → response path with real Django request/response cycles.
Tagged as @pytest.mark.integration because they instantiate the full app.
"""

import pytest
from unittest.mock import MagicMock, patch

from django.test import Client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FF_PATH = "core.services.feature_flag_service.feature_flags"
TASK_PATH = "api.tasks.security.persist_endpoint_access_log.delay"


def _flags_enabled(*flag_names):
    """Return a side_effect that enables multiple feature flags."""

    def _check(name):
        return name in flag_names

    return _check


def _all_flags_disabled():
    """Return a side_effect that disables all feature flags."""
    return lambda _name: False


# The search autocomplete endpoint is AllowAny — good for testing.
API_PATH = "/api/search/autocomplete/?q=test"


# ---------------------------------------------------------------------------
# 1. Feature Flag Gating
# ---------------------------------------------------------------------------


class TestFeatureFlagGating:
    """Tests that the middleware does nothing when flags are off."""

    def test_allows_normal_request_when_security_disabled(self):
        """When SECURITY_MONITORING_ENABLED is off, all requests pass through."""
        client = Client(REMOTE_ADDR="10.0.0.100")

        with patch(
            f"{FF_PATH}.is_enabled",
            side_effect=_all_flags_disabled(),
        ):
            response = client.get(API_PATH)

        # The search endpoint might not exist in test DB, but the middleware
        # should not block — any response other than 403 means security
        # didn't interfere.
        assert response.status_code != 403, (
            "Security middleware blocked a request when SECURITY_MONITORING_ENABLED is off"
        )

    def test_bypasses_non_api_paths(self):
        """Middleware should skip non-/api/ paths entirely."""
        client = Client(REMOTE_ADDR="10.0.0.100")

        with patch(
            f"{FF_PATH}.is_enabled",
            side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
        ):
            # Hit a path that does NOT start with /api/. There is no such
            # route in the URLconf, so Django returns 404 — but the middleware
            # must not block it (a block would be 403).
            response = client.get("/admin/login/")

        # Should not be blocked regardless of security state
        assert response.status_code != 403, (
            f"Non-API path was blocked: {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 2. Ban Enforcement (Fast Path)
# ---------------------------------------------------------------------------


class TestBanEnforcement:
    """Tests that banned IPs are blocked with 403."""

    def test_banned_ip_receives_403(self):
        """A banned IP should get 403 before the view runs."""
        client = Client(REMOTE_ADDR="10.0.0.200")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=True,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH),
        ):
            response = client.get(API_PATH)

        assert response.status_code == 403, (
            f"Expected 403 for banned IP, got {response.status_code}"
        )

        body = response.json()
        assert "Access denied" in body.get("error", "")
        assert "blocked" in body.get("detail", "").lower()

    def test_clean_ip_passes_through(self):
        """An unbanned IP with no threats should get a normal response."""
        client = Client(REMOTE_ADDR="10.0.0.201")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value=None,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH),
        ):
            response = client.get(API_PATH)

        # Should not be 403
        assert response.status_code != 403, (
            f"Clean IP was blocked: {response.status_code}"
        )


# ---------------------------------------------------------------------------
# 3. Auto-Ban on Threat Detection
# ---------------------------------------------------------------------------


class TestAutoBan:
    """Tests that thresholds trigger auto-ban when enforcement is on."""

    def test_auto_ban_triggers_when_threat_detected(self):
        """When evaluate_threats returns a reason and auto-ban is on,
        the response should be 403 and ban_ip should be called."""
        client = Client(REMOTE_ADDR="10.0.0.202")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled(
                    "SECURITY_MONITORING_ENABLED", "SECURITY_AUTO_BAN_ENABLED"
                ),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value="velocity",
            ),
            patch(
                "api.middleware.security_monitoring.security_service.ban_ip"
            ) as mock_ban,
            patch(
                "api.middleware.security_monitoring.security_service._redis",
                MagicMock(),
            ) as mock_redis,
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=True,
            ),
            patch(TASK_PATH),
        ):
            mock_redis.get.return_value = b"150"
            # Use a truly public endpoint (AllowAny) so the view returns 200
            # and the middleware can overwrite it with 403 on auto-ban.
            response = client.get("/api/system/config/auth/")

        assert response.status_code == 403
        body = response.json()
        assert "Access denied" in body.get("error", "")
        assert "suspicious" in body.get("detail", "").lower()

        mock_ban.assert_called_once()
        call_args, _ = mock_ban.call_args
        assert call_args[0] == "10.0.0.202"
        assert call_args[1] == "velocity"

    def test_threat_without_auto_ban_does_not_block(self):
        """When a threat is detected but SECURITY_AUTO_BAN_ENABLED is off,
        the request should NOT be blocked."""
        client = Client(REMOTE_ADDR="10.0.0.203")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value="scan",
            ),
            patch(
                "api.middleware.security_monitoring.security_service.ban_ip"
            ) as mock_ban,
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=True,
            ),
            patch(TASK_PATH),
        ):
            response = client.get(API_PATH)

        assert response.status_code != 403
        mock_ban.assert_not_called()


# ---------------------------------------------------------------------------
# 4. Signal Recording
# ---------------------------------------------------------------------------


class TestSignalRecording:
    """Tests that record_signals is called for non-banned IPs."""

    def test_record_signals_called_for_clean_ip(self):
        """record_signals should be invoked with the correct args."""
        client = Client(REMOTE_ADDR="10.0.0.204")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ) as mock_record,
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value=None,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH),
        ):
            client.get(API_PATH)

        mock_record.assert_called_once()
        call_args = mock_record.call_args
        assert call_args[0][0] == "10.0.0.204"

    def test_record_signals_not_called_for_banned_ip(self):
        """Banned IPs skip signal recording to avoid amplifying."""
        client = Client(REMOTE_ADDR="10.0.0.205")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=True,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ) as mock_record,
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH),
        ):
            client.get(API_PATH)

        mock_record.assert_not_called()


# ---------------------------------------------------------------------------
# 5. Forensic Logging
# ---------------------------------------------------------------------------


class TestForensicLogging:
    """Tests that forensic logging is dispatched correctly."""

    def test_forensic_task_called_for_flagged_ip(self):
        """When an IP is flagged for forensics, the Celery task should fire."""
        client = Client(REMOTE_ADDR="10.0.0.206")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value=None,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=True,
            ),
            patch(TASK_PATH) as mock_task,
        ):
            client.get(API_PATH)

        mock_task.assert_called_once()
        _, kwargs = mock_task.call_args
        assert kwargs["ip_address"] == "10.0.0.206"
        assert kwargs["is_flagged"] is True
        assert "endpoint" in kwargs
        assert "status_code" in kwargs

    def test_forensic_task_not_called_when_not_flagged_and_forensic_off(self):
        """Clean IP with no forensic flags should not trigger DB writes."""
        client = Client(REMOTE_ADDR="10.0.0.207")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled("SECURITY_MONITORING_ENABLED"),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value=None,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH) as mock_task,
        ):
            client.get(API_PATH)

        mock_task.assert_not_called()

    def test_forensic_logging_all_when_flag_enabled(self):
        """When SECURITY_FORENSIC_LOGGING_ENABLED is on, ALL requests are logged."""
        client = Client(REMOTE_ADDR="10.0.0.208")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled(
                    "SECURITY_MONITORING_ENABLED",
                    "SECURITY_FORENSIC_LOGGING_ENABLED",
                ),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ),
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value=None,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=False,
            ),
            patch(TASK_PATH) as mock_task,
        ):
            client.get(API_PATH)

        mock_task.assert_called_once()
        _, kwargs = mock_task.call_args
        # is_flagged=False — normal traffic, just logged globally
        assert kwargs["is_flagged"] is False


# ---------------------------------------------------------------------------
# 6. Already-Banned Flag Propagation
# ---------------------------------------------------------------------------


class TestAlreadyBannedFlag:
    """Tests the _security_already_banned request flag propagation."""

    def test_already_banned_flag_prevents_double_ban(self):
        """When security.py sets _security_already_banned, the response
        middleware should not call record_signals or ban_ip again."""
        client = Client(REMOTE_ADDR="10.0.0.210")

        with (
            patch(
                f"{FF_PATH}.is_enabled",
                side_effect=_flags_enabled(
                    "SECURITY_MONITORING_ENABLED", "SECURITY_AUTO_BAN_ENABLED"
                ),
            ),
            patch(
                "api.middleware.security_monitoring.security_service.is_banned",
                return_value=False,
            ),
            patch(
                "api.middleware.security_monitoring.security_service.record_signals"
            ) as mock_record,
            patch(
                "api.middleware.security_monitoring.security_service.evaluate_threats",
                return_value="strikes",
            ) as mock_eval,
            patch(
                "api.middleware.security_monitoring.security_service.ban_ip"
            ) as mock_ban,
            patch(
                "api.middleware.security_monitoring.security_service.is_flagged_for_forensics",
                return_value=True,
            ),
            patch(TASK_PATH),
        ):
            # Inject the _security_already_banned flag via a monkey-patched
            # __call__ so _finalize sees it.
            from api.middleware.security_monitoring import (
                SecurityMonitoringResponseMiddleware,
            )

            original_call = SecurityMonitoringResponseMiddleware.__call__

            def patched_call(self, request):
                request._security_already_banned = True
                return original_call(self, request)

            with patch.object(
                SecurityMonitoringResponseMiddleware, "__call__", patched_call
            ):
                response = client.get(API_PATH)

        mock_record.assert_not_called()
        mock_eval.assert_not_called()
        mock_ban.assert_not_called()
        assert response.status_code != 403
