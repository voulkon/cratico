"""
Fixtures for OpenRouter / AI service tests.

Loads ``OPENROUTER_KEY_FOR_TESTS`` from ``core/tests/.env.test`` on the
**recording** pass.  After cassettes are recorded the key is no longer
needed — VCR replays from disk.

Copy ``.env.test.example`` → ``.env.test`` and fill in a real key to record.
"""

import json
import os
from pathlib import Path

import dotenv
import pytest
import vcr
from core.ai_services.providers.openrouter import OpenRouterProvider

# ---------------------------------------------------------------------------
# Load .env.test (gitignored) – see .env.test.example for the template
# ---------------------------------------------------------------------------
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env.test"
if _ENV_FILE.exists():
    dotenv.load_dotenv(_ENV_FILE)

# ---------------------------------------------------------------------------
# Cassette directory – kept under the existing fixtures/vcr_cassettes tree
# ---------------------------------------------------------------------------
CASSETTE_DIR = "fixtures/vcr_cassettes/ai_services"

# ---------------------------------------------------------------------------
# VCR cassette sanitisation (vcrpy ≥ 7 uses object callbacks, not dicts)
# ---------------------------------------------------------------------------

# vcrpy 7.x ``before_record_response`` doesn't expose the request URI,
# so we track it from ``before_record_request``.
_current_request_uri: str = ""


def _sanitise_request(request):
    """Redact sensitive headers from the recorded request."""
    global _current_request_uri
    _current_request_uri = request.uri
    request.headers.pop("Authorization", None)
    request.headers.pop("Cookie", None)
    return request


def _sanitise_response(response):
    """
    Strip ``set-cookie`` noise and trim ``/models`` body to 5 entries
    (the full catalogue is ~600 KB).
    """
    # Cloudflare cookies
    response["headers"].pop("set-cookie", None)

    # Trim /models body
    if "/models" in _current_request_uri:
        raw = response["body"].get("string", "")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "data" in data:
                    data["data"] = data["data"][:5]
                    response["body"]["string"] = json.dumps(data).encode("utf-8")
            except (json.JSONDecodeError, TypeError):
                pass

    return response


# ---------------------------------------------------------------------------
# VCR fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def vcr_config():
    """VCR instance configured for OpenRouter tests."""
    return vcr.VCR(
        serializer="yaml",
        cassette_library_dir=CASSETTE_DIR,
        record_mode="once",
        match_on=["uri", "method"],
        decode_compressed_response=True,
        before_record_request=_sanitise_request,
        before_record_response=_sanitise_response,
    )


@pytest.fixture
def vcr_cassette(vcr_config):
    """Factory fixture – returns a context-manager cassette."""

    def _create(cassette_name: str):
        return vcr_config.use_cassette(cassette_name)

    return _create


# ---------------------------------------------------------------------------
# Convenience fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_model() -> str:
    """A cheap, widely‑available model for recording chat completions."""
    return "mistralai/mistral-small-24b-instruct-2501"


@pytest.fixture
def bad_api_key() -> str:
    """A deliberately invalid key for negative tests."""
    return "sk-or-v1-bad-key-00000000000000000000000000"


@pytest.fixture
def openrouter_api_key() -> str:
    """
    API key loaded from ``core/tests/.env.test``.

    Falls back to a dummy key: in replay mode (cassettes committed) the
    value is never sent anywhere, it only needs to be non-empty so
    ``invoke()`` doesn't short-circuit with "No OpenRouter API key".
    """
    return os.getenv("OPENROUTER_KEY_FOR_TESTS", "sk-or-v1-dummy-replay-key")


@pytest.fixture
def openrouter_provider(openrouter_api_key: str, test_model: str) -> OpenRouterProvider:
    """
    Shared :class:`OpenRouterProvider` wired with the test key and model.

    Tests that need a *different* key or model should construct their own
    instance; this fixture is the happy-path default.
    """
    return OpenRouterProvider(
        provider_name="OPENROUTER",
        model_name=test_model,
        api_key=openrouter_api_key,
    )
