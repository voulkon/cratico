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
# VCR cassette sanitisation
# ---------------------------------------------------------------------------


def _sanitise_cassette(interaction: dict) -> dict:
    """
    Called **after** recording but **before** writing to the YAML file.

    - Redacts ``Authorization`` from request headers (don't leak the key).
    - Strips ``set-cookie`` from response headers (Cloudflare noise).
    - Trims ``/models`` body to 5 entries (full catalogue is ~600 KB).
    """
    request = interaction["request"]
    response = interaction["response"]

    # -- Request: redact sensitive headers ----------------------------------
    for header in ("Authorization", "Cookie"):
        request["headers"].pop(header, None)

    # -- Response: strip Cloudflare cookies ---------------------------------
    response["headers"].pop("set-cookie", None)

    # -- Response: trim /models body ----------------------------------------
    if "/models" in request["uri"]:
        raw = response["body"].get("string", "")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "data" in data:
                    data["data"] = data["data"][:5]
                    response["body"]["string"] = json.dumps(data)
            except (json.JSONDecodeError, TypeError):
                pass

    return interaction


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
        before_record=_sanitise_cassette,
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
    API key loaded from ``core/tests/.env.test``
    (``OPENROUTER_KEY_FOR_TESTS``).
    """
    return os.getenv("OPENROUTER_KEY_FOR_TESTS", "")


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
