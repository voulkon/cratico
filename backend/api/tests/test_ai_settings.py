"""
Tests for AI Settings endpoints:

- GET/PUT  /api/ai/settings/
- POST     /api/ai/settings/test-key/
- GET      /api/ai/models/
- POST     /api/ai/models/sync/
"""

from unittest.mock import patch

import pytest
from django.urls import reverse

from core.models.user_ai_settings import UserAISettings


# ============================================================================
# Auto-use: mock encryption so tests don't need AI_SECRETS_KEY
# ============================================================================


@pytest.fixture(autouse=True)
def _mock_encryption():
    """Mock encrypt/decrypt to avoid requiring AI_SECRETS_KEY in tests."""
    with patch(
        "core.models.user_ai_settings.encrypt",
        side_effect=lambda plaintext: f"enc:{plaintext}",
    ), patch(
        "core.models.user_ai_settings.decrypt",
        side_effect=lambda ciphertext: ciphertext.replace("enc:", ""),
    ):
        yield


# ============================================================================
# Helpers
# ============================================================================


def _url(name: str, **kwargs) -> str:
    return reverse(f"ai_{name}", kwargs=kwargs)


# ============================================================================
# GET /api/ai/settings/
# ============================================================================


@pytest.mark.django_db
class TestAISettingsGET:
    def test_returns_defaults_when_no_settings_exist(self, authenticated_client):
        """First-time user: get_or_create returns defaults."""
        resp = authenticated_client.get(_url("settings"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "OPENROUTER"
        assert data["has_own_key"] is False
        assert data["api_key_masked"] == ""
        assert data["is_active"] is True

    def test_returns_existing_settings(self, authenticated_client, user):
        """Existing settings are serialized correctly."""
        settings = UserAISettings.objects.create(
            user=user,
            provider="OPENROUTER",
            default_model="openai/gpt-4o",
            monthly_budget_usd="50.00",
        )
        resp = authenticated_client.get(_url("settings"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == settings.id
        assert data["default_model"] == "openai/gpt-4o"
        assert data["monthly_budget_usd"] == "50.00"
        assert data["has_own_key"] is False

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests are rejected."""
        resp = api_client.get(_url("settings"))
        assert resp.status_code == 401


# ============================================================================
# PUT /api/ai/settings/
# ============================================================================


@pytest.mark.django_db
class TestAISettingsPUT:
    def test_update_provider_and_model(self, authenticated_client, user):
        """Update provider and default model."""
        resp = authenticated_client.put(
            _url("settings"),
            {"provider": "AWS_BEDROCK", "default_model": "anthropic.claude-v3"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["provider"] == "AWS_BEDROCK"
        assert data["default_model"] == "anthropic.claude-v3"

    def test_set_api_key(self, authenticated_client, user):
        """Setting an API key updates has_own_key and masked_key."""
        resp = authenticated_client.put(
            _url("settings"),
            {"api_key": "sk-or-v1-1234567890abcdefghij"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_own_key"] is True
        assert data["api_key_masked"].startswith("sk-")
        assert data["api_key_masked"].endswith("ghij")

    def test_clear_api_key(self, authenticated_client, user):
        """Empty string clears the stored key."""
        UserAISettings.objects.create(user=user)
        authenticated_client.put(
            _url("settings"),
            {"api_key": "sk-or-v1-somekey12345"},
            content_type="application/json",
        )
        resp = authenticated_client.put(
            _url("settings"),
            {"api_key": ""},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_own_key"] is False
        assert data["api_key_masked"] == ""

    def test_update_budget(self, authenticated_client):
        """Set and clear monthly budget."""
        resp = authenticated_client.put(
            _url("settings"),
            {"monthly_budget_usd": "100.00"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_budget_usd"] == "100.00"

        # Clear budget
        resp = authenticated_client.put(
            _url("settings"),
            {"monthly_budget_usd": None},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["monthly_budget_usd"] is None

    def test_deactivate_settings(self, authenticated_client):
        """Deactivating settings should be reflected."""
        resp = authenticated_client.put(
            _url("settings"),
            {"is_active": False},
            content_type="application/json",
        )
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

    def test_partial_update_preserves_other_fields(self, authenticated_client, user):
        """PUT only updates provided fields, others stay unchanged."""
        UserAISettings.objects.create(
            user=user,
            provider="OPENROUTER",
            default_model="openai/gpt-4o-mini",
            monthly_budget_usd="25.00",
        )
        resp = authenticated_client.put(
            _url("settings"),
            {"default_model": "google/gemini-flash"},
            content_type="application/json",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_model"] == "google/gemini-flash"
        assert data["provider"] == "OPENROUTER"
        assert data["monthly_budget_usd"] == "25.00"

    def test_requires_authentication(self, api_client):
        """Unauthenticated PUT is rejected."""
        resp = api_client.put(
            _url("settings"), {"provider": "OPENROUTER"}, content_type="application/json"
        )
        assert resp.status_code == 401


# ============================================================================
# POST /api/ai/settings/test-key/
# ============================================================================


@pytest.mark.django_db
class TestKeyValidation:
    def test_returns_valid_with_provided_key(self, authenticated_client):
        """Pass a key in the body and get a validation result."""
        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.check_key",
            return_value={"is_valid": True, "credits": 5.0},
        ):
            resp = authenticated_client.post(
                _url("test_key"),
                {"api_key": "sk-or-v1-valid"},
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert resp.json()["is_valid"] is True

    def test_returns_invalid_with_bad_key(self, authenticated_client):
        """Invalid key returns is_valid=False."""
        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.check_key",
            return_value={"is_valid": False, "error": "Invalid key"},
        ):
            resp = authenticated_client.post(
                _url("test_key"),
                {"api_key": "sk-or-v1-bad"},
                content_type="application/json",
            )
            assert resp.status_code == 200
            assert resp.json()["is_valid"] is False

    def test_uses_stored_key_when_no_body_key(self, authenticated_client, user):
        """When no api_key in body, the user's stored key is tested."""
        UserAISettings.objects.create(user=user)
        # User has no stored key → error
        resp = authenticated_client.post(
            _url("test_key"), {}, content_type="application/json"
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "No API key to test."

    def test_uses_stored_key_when_present(self, authenticated_client, user):
        """Stored key is used when no key in body."""
        settings = UserAISettings.objects.create(user=user)
        settings.set_api_key("sk-or-v1-stored")
        settings.save()

        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.check_key",
            return_value={"is_valid": True},
        ):
            resp = authenticated_client.post(
                _url("test_key"), {}, content_type="application/json"
            )
            assert resp.status_code == 200
            assert resp.json()["is_valid"] is True

    def test_requires_authentication(self, api_client):
        """Unauthenticated users cannot test keys."""
        resp = api_client.post(
            _url("test_key"), {"api_key": "sk-test"}, content_type="application/json"
        )
        assert resp.status_code == 401


# ============================================================================
# GET /api/ai/models/
# ============================================================================


@pytest.mark.django_db
class TestListModels:
    _SAMPLE_MODELS = [{"id": "openai/gpt-4o", "name": "GPT-4o"}]

    def test_returns_cached_models(self, authenticated_client):
        """Cache hit returns cached=True."""
        from django.core.cache import cache

        cache.set("openrouter_models_v1", self._SAMPLE_MODELS, 60)

        resp = authenticated_client.get(_url("models_list"))
        assert resp.status_code == 200
        data = resp.json()
        assert data["cached"] is True
        assert data["models"] == self._SAMPLE_MODELS

    def test_fetches_and_caches_on_miss(self, authenticated_client):
        """Cache miss fetches from OpenRouter."""
        from django.core.cache import cache

        cache.delete("openrouter_models_v1")

        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.list_models",
            return_value=self._SAMPLE_MODELS,
        ):
            resp = authenticated_client.get(_url("models_list"))
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached"] is False
            assert data["models"] == self._SAMPLE_MODELS

    def test_handles_provider_error(self, authenticated_client):
        """Provider failure returns 502."""
        from django.core.cache import cache

        cache.delete("openrouter_models_v1")

        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.list_models",
            side_effect=Exception("Service unavailable"),
        ):
            resp = authenticated_client.get(_url("models_list"))
            assert resp.status_code == 502
            assert "Failed to fetch models" in resp.json()["error"]

    def test_public_access(self, api_client):
        """Models list is public — no authentication required."""
        from django.core.cache import cache

        cache.delete("openrouter_models_v1")

        with patch(
            "api.views.ai.ai_settings.OpenRouterProvider.list_models",
            return_value=self._SAMPLE_MODELS,
        ):
            resp = api_client.get(_url("models_list"))
            assert resp.status_code == 200
            data = resp.json()
            assert data["cached"] is False
            assert data["models"] == self._SAMPLE_MODELS


# ============================================================================
# POST /api/ai/models/sync/ (admin only)
# ============================================================================


@pytest.mark.django_db
class TestSyncModels:
    def test_admin_can_sync(self, admin_client):
        """Admin user can trigger model sync."""
        with patch(
            "api.views.ai.ai_settings.OpenRouterModelSyncService.sync_models",
            return_value={"synced": 10, "created": 2, "updated": 8},
        ):
            resp = admin_client.post(_url("models_sync"))
            assert resp.status_code == 200
            assert resp.json()["synced"] == 10

    def test_regular_user_cannot_sync(self, authenticated_client):
        """Non-admin users get 403."""
        resp = authenticated_client.post(_url("models_sync"))
        assert resp.status_code == 403

    def test_requires_authentication(self, api_client):
        """Unauthenticated requests get 401."""
        resp = api_client.post(_url("models_sync"))
        assert resp.status_code == 401
