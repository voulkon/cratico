"""
Tests for the OpenRouter LLM provider.

Recording workflow (run once)::

    cp core/tests/.env.test.example core/tests/.env.test
    # edit .env.test with a real OpenRouter key
    python -m pytest core/tests/ai_services/ -v

After that, cassettes are stored under
``fixtures/vcr_cassettes/ai_services/`` and subsequent runs replay
from disk — no key needed.

Cassettes created by this suite
-------------------------------
* ``invoke_success.yaml``          – chat completion (happy path)
* ``list_models.yaml``             – model catalogue
* ``check_key_valid.yaml``         – key validation (valid key)
* ``check_key_invalid.yaml``       – key validation (bad key)
"""

import pytest
from core.ai_services.factory import get_provider
from core.ai_services.providers.openrouter import OpenRouterProvider

pytestmark = pytest.mark.django_db


# ═══════════════════════════════════════════════════════════════════════════
# Factory tests (no network needed)
# ═══════════════════════════════════════════════════════════════════════════


class TestOpenRouterFactory:
    """Verify the provider factory returns the correct type."""

    def test_factory_returns_openrouter_provider(self, openrouter_api_key):
        provider = get_provider(
            provider_name="OPENROUTER",
            model_name="openai/gpt-3.5-turbo",
            api_key=openrouter_api_key,
        )
        assert isinstance(provider, OpenRouterProvider)
        assert provider.model_name == "openai/gpt-3.5-turbo"
        assert provider.provider_name == "OPENROUTER"


# ═══════════════════════════════════════════════════════════════════════════
# invoke() tests
# ═══════════════════════════════════════════════════════════════════════════


class TestInvoke:
    """Tests for ``OpenRouterProvider.invoke()``."""

    # -- Happy path (VCR-recorded) ------------------------------------------

    def test_invoke_success(self, vcr_cassette, openrouter_provider):
        """
        Invoke a chat completion and verify the standardised response shape.

        Uses the shared ``openrouter_provider`` fixture (key from
        ``.env.test``, model from ``test_model``).
        """
        with vcr_cassette("invoke_success.yaml"):
            result = openrouter_provider.invoke(
                text="What is the capital of France? Answer in one word.",
                prompt="You are a helpful assistant.",
                temperature=0.0,
                max_tokens=10,
            )

        # Standardised response shape
        assert result["success"] is True
        assert isinstance(result["text"], str)
        assert len(result["text"]) > 0
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0
        assert result["latency_ms"] >= 0
        assert result["provider"] == "OPENROUTER"
        assert result["model"] == openrouter_provider.model_name
        assert result["is_estimate"] is False
        assert "error" not in result

        # Metadata should contain the OpenRouter response id
        assert "metadata" in result
        assert "id" in result["metadata"]

    # -- Error: no API key --------------------------------------------------

    def test_invoke_no_api_key_returns_error(self, test_model):
        """invoke() with an empty key returns success=False."""
        provider = OpenRouterProvider(
            provider_name="OPENROUTER",
            model_name=test_model,
            api_key="",  # deliberately empty
        )

        result = provider.invoke(text="Hello", prompt="You are helpful.")

        assert result["success"] is False
        assert result["error"] is not None
        assert "No OpenRouter API key" in result["error"]
        assert result["input_tokens"] == 0
        assert result["output_tokens"] == 0

    def test_invoke_empty_content_fails_loudly(self, test_model):
        """
        A 200 response with empty ``message.content`` is treated as a failure.

        Reasoning models can burn their whole token budget on "thinking" and
        return ``content=null`` with ``completion_tokens>0`` — the exact
        failure that previously produced an empty summary on batch 305.
        """
        from unittest.mock import MagicMock, patch

        provider = OpenRouterProvider(
            provider_name="OPENROUTER",
            model_name=test_model,
            api_key="sk-or-v1-test-key",
        )

        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.json.return_value = {
            "id": "gen-fake-empty",
            "model": test_model,
            "choices": [
                {
                    "message": {"role": "assistant", "content": None},
                    "finish_reason": "length",
                }
            ],
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 500,
                "cost": 0.0001,
            },
        }

        with patch(
            "core.ai_services.providers.openrouter._session.post",
            return_value=fake_response,
        ):
            result = provider.invoke(
                text="Summarize this.",
                prompt="You are a legal analyst.",
                max_tokens=500,
            )

        assert result["success"] is False
        assert "empty content" in result["error"]
        # Tokens/cost are still recorded for the audit trail
        assert result["output_tokens"] == 500
        assert result["input_tokens"] == 10
        # finish_reason is surfaced in metadata for diagnostics
        assert result["metadata"]["finish_reason"] == "length"


# ═══════════════════════════════════════════════════════════════════════════
# list_models() tests
# ═══════════════════════════════════════════════════════════════════════════


class TestListModels:
    """Tests for ``OpenRouterProvider.list_models()`` classmethod."""

    def test_list_models_returns_catalogue(self, vcr_cassette, openrouter_api_key):
        """
        Fetch the model catalogue — both with and without an API key.

        The /models endpoint is public, so both calls return the same
        result; we share a single cassette.
        """
        with vcr_cassette("list_models.yaml"):
            models_no_auth = OpenRouterProvider.list_models()

        assert isinstance(models_no_auth, list)
        assert len(models_no_auth) > 0

        # A second call with an explicit key should also succeed
        if openrouter_api_key:
            with vcr_cassette("list_models.yaml"):
                models_with_key = OpenRouterProvider.list_models(
                    api_key=openrouter_api_key
                )
            # Both should return a non-empty catalogue (first call gets the
            # full response; the cassette is trimmed afterward by VCR).
            assert len(models_with_key) > 0

        # Every entry should have the expected keys
        for m in models_no_auth:
            assert "id" in m
            assert "name" in m
            assert "context_length" in m
            assert "pricing" in m
            assert "prompt" in m["pricing"]
            assert "completion" in m["pricing"]

        # At least one well-known model should appear.  Don't hardcode a
        # specific model ID — the OpenRouter catalogue changes over time, and
        # a stale cassette only guarantees the recorded entries exist.
        model_ids = {m["id"] for m in models_no_auth}
        assert len(model_ids) > 0, "Expected at least one model in the catalogue"
        # IDs should follow the standard "<provider>/<model>" format
        for model_id in model_ids:
            assert "/" in model_id, (
                f"Model ID {model_id!r} doesn't follow the '<provider>/<model>' format"
            )


# ═══════════════════════════════════════════════════════════════════════════
# check_key() tests
# ═══════════════════════════════════════════════════════════════════════════


class TestCheckKey:
    """Tests for ``OpenRouterProvider.check_key()`` classmethod."""

    def test_check_key_valid(self, vcr_cassette, openrouter_api_key):
        """
        Validate a real API key via GET /key/info.

        Uses the key from ``.env.test``.
        """
        if not openrouter_api_key:
            pytest.skip("No API key available – recording not possible")

        with vcr_cassette("check_key_valid.yaml"):
            result = OpenRouterProvider.check_key(openrouter_api_key)

        assert result["is_valid"] is True
        # Limits are present (OpenRouter provides them)
        assert result["limit_total"] is not None
        assert result["limit_remaining"] is not None
        assert result["limit_used"] is not None

    def test_check_key_invalid(self, vcr_cassette, bad_api_key):
        """A deliberately bad key returns is_valid=False."""
        with vcr_cassette("check_key_invalid.yaml"):
            result = OpenRouterProvider.check_key(bad_api_key)

        assert result["is_valid"] is False


# ═══════════════════════════════════════════════════════════════════════════
# _headers() test
# ═══════════════════════════════════════════════════════════════════════════


class TestHeaders:
    """Verify the request headers are correctly formed."""

    def test_headers_include_auth(self, openrouter_provider):
        headers = openrouter_provider._headers()
        assert headers["Authorization"] == f"Bearer {openrouter_provider.api_key}"
        assert headers["Content-Type"] == "application/json"
        assert "HTTP-Referer" in headers
        assert "X-Title" in headers


# ═══════════════════════════════════════════════════════════════════════════
# estimate_cost() tests
# ═══════════════════════════════════════════════════════════════════════════


class TestEstimateCost:
    """Verify cost estimation (no network)."""

    def test_estimate_returns_expected_shape(self, openrouter_provider):
        result = openrouter_provider.estimate_cost(
            text="Short text for estimation.",
            prompt="Summarize.",
        )

        assert result["success"] is True
        assert result["input_tokens"] > 0
        assert result["output_tokens"] > 0
        assert result["latency_ms"] == 0  # no API call
        assert result["is_estimate"] is True
        assert result["model"] == openrouter_provider.model_name
        assert result["provider"] == "OPENROUTER"
