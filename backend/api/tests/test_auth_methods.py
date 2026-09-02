"""
Tests for the unified-auth decision layer (implementation step 02).

Covers:

- ``api.utils.auth_methods`` — the single source of truth for which auth
  providers are active (``clerk_is_fully_configured``, ``get_auth_methods``,
  ``get_clerk_publishable_key``) across the full USE_CLERK_AUTH x keys matrix.
- ``ClerkAuthentication`` guard paths that must short-circuit without any JWT
  fixtures, mirroring the same primitives the decision function advertises.
- The public ``GET /api/system/config/auth/`` endpoint — payload shape and the
  invariant that a publishable key is never exposed when Clerk is not usable.
- Coexistence regression: a Django ``Token`` credential must keep working when
  Clerk is enabled (the core promise of the unified-auth project).

Known gap (documented in the task doc): a full Clerk JWT happy-path test
(signed RS256 token -> authenticated user) needs key-pair signing fixtures;
none exist in the repo yet, so only the guard paths are covered here.

Note: ``api/tests`` is not in ``pytest.ini`` ``testpaths`` — run explicitly:
``cd backend && pytest api/tests/test_auth_methods.py -v``
"""

import pytest
from django.test import override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIRequestFactory
from unittest.mock import patch

from api.authentication import ClerkAuthentication
from api.utils.auth_methods import (
    clerk_is_fully_configured,
    get_auth_methods,
    get_clerk_publishable_key,
)

AUTH_CONFIG_URL = "/api/system/config/auth/"
ME_URL = "/api/auth/me/"

# Same singleton used by the auth_config view and the stealth/security
# middleware. Patching it keeps these tests hermetic (no Redis/DB flag reads).
FF_PATH = "core.services.feature_flag_service.feature_flags.is_enabled"

# Settings for a fully configured Clerk deployment. The JWT key never has to
# be a real key here: no test in this module decodes a JWT.
CLERK_FULLY_CONFIGURED = {
    "USE_CLERK_AUTH": True,
    "CLERK_JWT_PUBLIC_KEY": (
        "-----BEGIN PUBLIC KEY-----\nfake-test-key\n-----END PUBLIC KEY-----"
    ),
    "CLERK_SECRET_KEY": "sk_test_fake",
    "CLERK_PUBLISHABLE_KEY": "pk_test_fake",
}

CLERK_KEYS = ("CLERK_JWT_PUBLIC_KEY", "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY")


# ---------------------------------------------------------------------------
# 2a. Unit tests for the decision function
# ---------------------------------------------------------------------------


class TestClerkIsFullyConfigured:
    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_true_when_flag_on_and_all_keys_present(self):
        assert clerk_is_fully_configured() is True

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_false_when_flag_off_even_with_all_keys(self):
        assert clerk_is_fully_configured() is False

    @pytest.mark.parametrize("missing_key", CLERK_KEYS)
    def test_false_when_any_key_missing(self, missing_key):
        with override_settings(**{**CLERK_FULLY_CONFIGURED, missing_key: None}):
            assert clerk_is_fully_configured() is False

    @pytest.mark.parametrize("missing_key", CLERK_KEYS)
    def test_false_when_any_key_empty_string(self, missing_key):
        with override_settings(**{**CLERK_FULLY_CONFIGURED, missing_key: ""}):
            assert clerk_is_fully_configured() is False


class TestGetAuthMethods:
    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_clerk_and_django_when_fully_configured(self):
        assert get_auth_methods() == ["clerk", "django"]

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_django_only_when_flag_off(self):
        assert get_auth_methods() == ["django"]

    @pytest.mark.parametrize("missing_key", CLERK_KEYS)
    def test_django_only_when_any_key_missing(self, missing_key):
        with override_settings(**{**CLERK_FULLY_CONFIGURED, missing_key: None}):
            assert get_auth_methods() == ["django"]

    @override_settings(
        USE_CLERK_AUTH=False,
        CLERK_JWT_PUBLIC_KEY=None,
        CLERK_SECRET_KEY=None,
        CLERK_PUBLISHABLE_KEY=None,
    )
    def test_django_always_present_and_last(self):
        """The invariant the frontend relies on: 'django' is a valid final fallback."""
        methods = get_auth_methods()
        assert methods[-1] == "django"
        with override_settings(**CLERK_FULLY_CONFIGURED):
            assert get_auth_methods()[-1] == "django"


class TestGetClerkPublishableKey:
    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_returns_key_when_clerk_active(self):
        assert get_clerk_publishable_key() == "pk_test_fake"

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_none_when_flag_off(self):
        """Never hand out a key the backend would not accept credentials for."""
        assert get_clerk_publishable_key() is None

    @pytest.mark.parametrize("missing_key", CLERK_KEYS)
    def test_none_when_any_key_missing(self, missing_key):
        with override_settings(**{**CLERK_FULLY_CONFIGURED, missing_key: None}):
            assert get_clerk_publishable_key() is None


# ---------------------------------------------------------------------------
# ClerkAuthentication guard paths (no JWT fixtures required)
# ---------------------------------------------------------------------------


class TestClerkAuthenticationGuards:
    """
    The advertise/accept mirror invariant: whenever ``get_auth_methods()``
    omits "clerk", ``ClerkAuthentication`` must not authenticate anyone.
    """

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_skipped_when_feature_flag_off(self):
        request = APIRequestFactory().get(
            "/", HTTP_AUTHORIZATION="Bearer fake.jwt.token"
        )
        assert ClerkAuthentication().authenticate(request) is None

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "CLERK_JWT_PUBLIC_KEY": None})
    def test_skipped_when_public_key_missing(self):
        request = APIRequestFactory().get(
            "/", HTTP_AUTHORIZATION="Bearer fake.jwt.token"
        )
        assert ClerkAuthentication().authenticate(request) is None

    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_skipped_without_bearer_header(self):
        """A Django 'Token <key>' header must fall through to TokenAuthentication."""
        request = APIRequestFactory().get("/", HTTP_AUTHORIZATION="Token abc123")
        assert ClerkAuthentication().authenticate(request) is None


# ---------------------------------------------------------------------------
# 2b. API tests for GET /api/system/config/auth/
# ---------------------------------------------------------------------------


class TestAuthConfigEndpoint:
    def test_public_unauthenticated_200(self, api_client):
        """Endpoint must answer before login — the frontend needs it to render."""
        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200

    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_reports_clerk_and_django_when_fully_configured(self, api_client):
        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        payload = response.json()
        assert payload["auth_methods"] == ["clerk", "django"]
        assert payload["clerk_publishable_key"] == "pk_test_fake"

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_reports_django_only_when_flag_off(self, api_client):
        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        payload = response.json()
        assert payload["auth_methods"] == ["django"]
        assert payload["clerk_publishable_key"] is None

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "CLERK_PUBLISHABLE_KEY": ""})
    def test_reports_django_only_when_a_key_is_missing(self, api_client):
        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        payload = response.json()
        assert payload["auth_methods"] == ["django"]
        assert payload["clerk_publishable_key"] is None

    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_payload_shape_is_stable(self, api_client):
        """Frontend contract: these keys must always be present."""
        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(AUTH_CONFIG_URL)
        payload = response.json()
        assert set(payload["authentication"]) == {"required", "allowlist_enabled"}
        assert "min_length" in payload["password_requirements"]
        assert isinstance(payload["auth_methods"], list)
        assert "clerk_publishable_key" in payload


# ---------------------------------------------------------------------------
# 2c. Coexistence regression: Django token auth works while Clerk is enabled
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDjangoTokenCoexistence:
    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_django_token_accepted_when_clerk_enabled(self, api_client, user):
        token = Token.objects.create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(ME_URL)

        assert response.status_code == 200
        payload = response.json()
        # auth_method == "django" proves the Token credential — not a Clerk
        # JWT — authenticated this request while Clerk was enabled.
        assert payload["user"]["id"] == user.id
        assert payload["user"]["auth_method"] == "django"

    @override_settings(**{**CLERK_FULLY_CONFIGURED, "USE_CLERK_AUTH": False})
    def test_django_token_accepted_when_clerk_disabled(self, api_client, user):
        token = Token.objects.create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        with patch(FF_PATH, side_effect=lambda _name: False):
            response = api_client.get(ME_URL)

        assert response.status_code == 200
        assert response.json()["user"]["auth_method"] == "django"


# ---------------------------------------------------------------------------
# Stealth mode interaction (STEALTH_MODE=true deployments)
# ---------------------------------------------------------------------------


def _stealth_on(name: str) -> bool:
    return name == "STEALTH_MODE"


@pytest.mark.django_db
class TestStealthModeInteraction:
    """
    When STEALTH_MODE is on, the frontend is locked out of everything except
    the exempt auth/system prefixes — so auth_config reporting the right
    ``auth_methods`` is exactly what the login gate renders from. These tests
    pin the two contracts that must hold simultaneously: the exemption (the
    login UI can boot) and the gate (nothing else leaks).
    """

    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_auth_config_stays_public_and_reports_methods(self, api_client):
        with patch(FF_PATH, side_effect=_stealth_on):
            response = api_client.get(AUTH_CONFIG_URL)
        assert response.status_code == 200
        payload = response.json()
        assert payload["authentication"]["required"] is True
        assert payload["auth_methods"] == ["clerk", "django"]
        assert payload["clerk_publishable_key"] == "pk_test_fake"

    def test_protected_endpoint_gated_for_anonymous(self, api_client):
        with patch(FF_PATH, side_effect=_stealth_on):
            response = api_client.get("/api/decisions/")
        assert response.status_code == 401

    @override_settings(**CLERK_FULLY_CONFIGURED)
    def test_django_token_accepted_under_stealth(self, api_client, user):
        """Legit users are unaffected: token auth runs inside the middleware's
        own DRF authentication pass, so credentials still win."""
        token = Token.objects.create(user=user)
        api_client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

        with patch(FF_PATH, side_effect=_stealth_on):
            response = api_client.get(ME_URL)

        assert response.status_code == 200
        assert response.json()["user"]["auth_method"] == "django"
