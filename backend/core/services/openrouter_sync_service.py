"""
OpenRouter model & price sync service.

Pulls the OpenRouter model catalogue and upserts rows into ``AIModelPricing``
so the existing ``AICostEstimator`` keeps working without code changes.

OpenRouter prices are per-token in USD; we multiply by 1 000 000 to store as
$ / million tokens, matching the existing ``PER_MILLION`` convention.
"""

from datetime import date
from decimal import Decimal

from core.ai_services.providers.openrouter import OpenRouterProvider
from core.models.ai_pricing import AIModelPricing
from loguru import logger


class OpenRouterModelSyncService:
    """Sync OpenRouter models + pricing into the ``AIModelPricing`` table."""

    @staticmethod
    def sync_models(api_key: str | None = None) -> dict:
        """
        Fetch the OpenRouter catalogue and upsert pricing rows.

        Returns a summary dict: ``{"synced": N, "created": N, "updated": N,
        "errors": N}``.
        """
        today = date.today()
        synced = created = updated = errors = 0

        try:
            models = OpenRouterProvider.list_models(api_key=api_key)
        except Exception as exc:
            logger.error(f"Failed to fetch OpenRouter models: {exc}", exc_info=True)
            return {"synced": 0, "created": 0, "updated": 0, "errors": 1}

        for m in models:
            model_id = m.get("id")
            if not model_id:
                continue
            try:
                pricing = m.get("pricing", {})
                # OpenRouter prices are per-token USD → convert to $/M
                prompt_price_raw = Decimal(str(pricing.get("prompt", "0")))
                completion_price_raw = Decimal(str(pricing.get("completion", "0")))
                input_price = prompt_price_raw * Decimal("1000000")
                output_price = completion_price_raw * Decimal("1000000")

                _, was_created = AIModelPricing.objects.update_or_create(
                    provider="OPENROUTER",
                    model_name=model_id,
                    effective_date=today,
                    defaults={
                        "display_name": m.get("name") or model_id,
                        "input_price": input_price,
                        "output_price": output_price,
                        "pricing_unit": "PER_MILLION",
                        "context_window": m.get("context_length"),
                        "model_type": "CHAT",
                        "is_active": True,
                    },
                )
                if was_created:
                    created += 1
                else:
                    updated += 1
                synced += 1
            except Exception as exc:
                errors += 1
                logger.warning(f"Failed to sync OpenRouter model {model_id}: {exc}")

        logger.info(
            f"OpenRouter sync complete: {synced} synced "
            f"({created} created, {updated} updated, {errors} errors)"
        )
        return {
            "synced": synced,
            "created": created,
            "updated": updated,
            "errors": errors,
        }
