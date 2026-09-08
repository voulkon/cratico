"""
Tests for the guarded "throttle" block on GET /api/system/config/auth/
(implementation task 02 of the free-access-throttling E2E project).

Contract:

- ``EXPOSE_E2E_OPERATIONAL_CONFIG`` off (default/unset) -> 200 and **no**
  ``throttle`` key. Nothing new is exposed in production by default.
- Flag on -> ``throttle`` present with:
    - ``anon_daily_limit`` from ``settings.ANON_API_DAILY_LIMIT``
    - security values read live through the feature-flag service
      (``SECURITY_MONITORING_ENABLED`` / ``SECURITY_AUTO_BAN_ENABLED`` via
      ``is_enabled``, ``SECURITY_VELOCITY_THRESHOLD`` via ``get_value``).
- The endpoint stays ``AllowAny``/public in both cases.

Note: ``api/tests`` is not in ``pytest.ini`` ``testpaths`` — run explicitly:
``cd backend && pytest api/tests/test_operational_config.py -v``
"""

from unittest.mock import patch

import core.services.feature_flag_service as ffs
import pytest
from api.constants import DEFAULT_ANON_API_DAILY_LIMIT
from django.conf import settings
from django.test import override_settings

AUTH_CONFIG_URL = "/api/system/config/auth/"

# Same singleton the view consults. Patching keeps these tests hermetic
# (no Redis/DB flag reads), mirroring test_auth_methods.py.
FF_PATH = "core.services.feature_flag_service.feature_flags.is_enabled"
FF_MODULE = "core.services.feature_flag_service.feature_flags"


def _flags_off():
    return patch(FF_PATH, side_effect=lambda _name: False)


# ---------------------------------------------------------------------------
# 1. Flag off (default) -> no throttle key, production-safe
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestThrottleBlockHiddenByDefault:
    def test_no_throttle_key_when_flag_unset(self, api_client):
        """Default deployment: no EXPOSE_E2E_OPERATIONAL_CONFIG -> no leak."""
        with _flags_off():
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        assert "throttle" not in response.json()

    @override_settings(EXPOSE_E2E_OPERATIONAL_CONFIG=False)
    def test_no_throttle_key_when_flag_explicitly_false(self, api_client):
        with _flags_off():
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        assert "throttle" not in response.json()


# ---------------------------------------------------------------------------
# 2. Flag on -> throttle block with live values
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestThrottleBlockExposed:
    @override_settings(EXPOSE_E2E_OPERATIONAL_CONFIG=True, ANON_API_DAILY_LIMIT=8)
    def test_throttle_block_present_with_settings_limit(self, api_client):
        with _flags_off():
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        throttle = response.json()["throttle"]
        assert throttle["anon_daily_limit"] == 8
        # Security flags are off (patched) -> booleans reflect the service.
        assert throttle["security_monitoring_enabled"] is False
        assert throttle["security_auto_ban_enabled"] is False

    @override_settings(EXPOSE_E2E_OPERATIONAL_CONFIG=True)
    def test_anon_daily_limit_defaults_to_100_when_setting_missing(self, api_client):
        """The view's getattr fallback (DEFAULT_ANON_API_DAILY_LIMIT) when the setting is absent."""
        # The setting exists in base.py (300), so remove it to exercise the
        # view's getattr(..., DEFAULT_ANON_API_DAILY_LIMIT) fallback.
        had_setting = hasattr(settings, "ANON_API_DAILY_LIMIT")
        if had_setting:
            del settings.ANON_API_DAILY_LIMIT
        try:
            with _flags_off():
                response = api_client.get(AUTH_CONFIG_URL)
        finally:
            if had_setting:
                settings.ANON_API_DAILY_LIMIT = 300
        assert response.status_code == 200
        assert (
            response.json()["throttle"]["anon_daily_limit"]
            == DEFAULT_ANON_API_DAILY_LIMIT
        )

    @override_settings(EXPOSE_E2E_OPERATIONAL_CONFIG=True)
    def test_security_values_read_through_feature_flag_service(self, api_client):
        """Security booleans/threshold come from the same flag service the
        middleware consults — not from settings."""
        with patch(
            FF_PATH,
            side_effect=lambda name: name
            in ("SECURITY_MONITORING_ENABLED", "SECURITY_AUTO_BAN_ENABLED"),
        ), patch.object(
            ffs.feature_flags,
            "get_value",
            side_effect=lambda key, default=None: (
                5 if key == "SECURITY_VELOCITY_THRESHOLD" else default
            ),
        ):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        throttle = response.json()["throttle"]
        assert throttle["security_monitoring_enabled"] is True
        assert throttle["security_auto_ban_enabled"] is True
        assert throttle["security_velocity_threshold"] == 5


# ---------------------------------------------------------------------------
# 3. Endpoint stays public in both cases
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEndpointStaysPublic:
    @override_settings(EXPOSE_E2E_OPERATIONAL_CONFIG=True)
    def test_allowany_when_flag_on(self, api_client):
        with _flags_off():
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200

    def test_allowany_when_flag_off(self, api_client):
        with _flags_off():
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
