"""
Tests for ``OpenRouterModelSyncService`` — OpenRouter model & price sync.

Covers:
- Creating new ``AIModelPricing`` entries
- Updating existing entries (idempotent sync)
- Price conversion (per-token → per-million)
- Skipping models without an ID
- API failure handling
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from core.models.ai_pricing import AIModelPricing
from core.services.openrouter_sync_service import OpenRouterModelSyncService

pytestmark = pytest.mark.django_db


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def clean_pricing():
    """Remove all AIModelPricing entries before and after each test."""
    AIModelPricing.objects.all().delete()
    yield
    AIModelPricing.objects.all().delete()


# Sample OpenRouter model catalogue entries
SAMPLE_MODELS = [
    {
        "id": "google/gemini-flash-1.5",
        "name": "Gemini Flash 1.5",
        "context_length": 1000000,
        "pricing": {"prompt": "0.000000075", "completion": "0.0000003"},
    },
    {
        "id": "anthropic/claude-3.5-sonnet",
        "name": "Claude 3.5 Sonnet",
        "context_length": 200000,
        "pricing": {"prompt": "0.000003", "completion": "0.000015"},
    },
    {
        # Model without an ID — should be skipped
        "name": "No ID model",
        "context_length": 1000,
        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
    },
]


# ============================================================================
# Tests
# ============================================================================


class TestSyncModels:
    """Tests for ``OpenRouterModelSyncService.sync_models``."""

    def test_creates_new_entries(self):
        """First sync creates ``AIModelPricing`` rows for each valid model."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=SAMPLE_MODELS,
        ):
            result = OpenRouterModelSyncService.sync_models()

        assert result["synced"] == 2  # 2 valid models (one skipped for no ID)
        assert result["created"] == 2
        assert result["updated"] == 0
        assert result["errors"] == 0

        # Verify rows exist
        assert AIModelPricing.objects.count() == 2
        pricing = AIModelPricing.objects.get(model_name="google/gemini-flash-1.5")
        assert pricing.provider == "OPENROUTER"
        assert pricing.display_name == "Gemini Flash 1.5"
        assert pricing.context_window == 1000000
        assert pricing.is_active is True

    def test_updates_existing_entries(self):
        """Re-syncing the same models updates instead of duplicating."""
        # Pre-create an entry
        AIModelPricing.objects.create(
            provider="OPENROUTER",
            model_name="google/gemini-flash-1.5",
            effective_date=date.today(),
            input_price=Decimal("1"),
            output_price=Decimal("1"),
            pricing_unit="PER_MILLION",
        )

        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=SAMPLE_MODELS,
        ):
            result = OpenRouterModelSyncService.sync_models()

        assert result["updated"] == 1
        assert result["created"] == 1  # the second model
        assert AIModelPricing.objects.count() == 2

    def test_price_conversion_per_token_to_per_million(self):
        """Per-token USD prices are multiplied by 1,000,000."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=[SAMPLE_MODELS[1]],  # Claude
        ):
            OpenRouterModelSyncService.sync_models()

        pricing = AIModelPricing.objects.get(
            model_name="anthropic/claude-3.5-sonnet"
        )
        # prompt: 0.000003 * 1_000_000 = 3.0
        assert pricing.input_price == Decimal("3.0")
        # completion: 0.000015 * 1_000_000 = 15.0
        assert pricing.output_price == Decimal("15.0")
        assert pricing.pricing_unit == "PER_MILLION"

    def test_skips_models_without_id(self):
        """Models missing ``id`` are skipped entirely."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=SAMPLE_MODELS,
        ):
            OpenRouterModelSyncService.sync_models()

        # The "No ID model" should not be in the database
        assert not AIModelPricing.objects.filter(
            display_name="No ID model"
        ).exists()

    def test_api_failure_returns_error_count(self):
        """When ``list_models`` raises, the result reports errors."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            side_effect=Exception("Network error"),
        ):
            result = OpenRouterModelSyncService.sync_models()

        assert result == {
            "synced": 0,
            "created": 0,
            "updated": 0,
            "errors": 1,
        }
        assert AIModelPricing.objects.count() == 0

    def test_effective_date_set_to_today(self):
        """All created/updated rows have ``effective_date = today``."""
        today = date.today()
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=SAMPLE_MODELS[:1],
        ):
            OpenRouterModelSyncService.sync_models()

        pricing = AIModelPricing.objects.get(
            model_name="google/gemini-flash-1.5"
        )
        assert pricing.effective_date == today

    def test_empty_catalogue_no_error(self):
        """An empty model list synced cleanly."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=[],
        ):
            result = OpenRouterModelSyncService.sync_models()

        assert result == {
            "synced": 0,
            "created": 0,
            "updated": 0,
            "errors": 0,
        }

    def test_model_type_set_to_chat(self):
        """All synced models have ``model_type = 'CHAT'``."""
        with patch(
            "core.services.openrouter_sync_service.OpenRouterProvider.list_models",
            return_value=SAMPLE_MODELS[:1],
        ):
            OpenRouterModelSyncService.sync_models()

        pricing = AIModelPricing.objects.get(
            model_name="google/gemini-flash-1.5"
        )
        assert pricing.model_type == "CHAT"
