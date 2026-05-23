"""
AI Cost Estimation Utilities

This module provides utilities for estimating AI processing costs based on token usage.
Requires tiktoken library for accurate token counting.

Example usage:
    from core.utils.ai_cost_estimator import AICostEstimator

    estimator = AICostEstimator()

    # Estimate cost for a text analysis task
    result = estimator.estimate_analysis_cost(
        text="Long document text...",
        provider="OPENAI",
        model_name="gpt-4-turbo",
        task_type="summary"
    )
    print(f"Estimated cost: ${result['total_cost_usd']:.6f}")

    # Estimate cost for embeddings
    embedding_cost = estimator.estimate_embedding_cost(
        text="Text to embed...",
        provider="OPENAI_EMBED",
        model_name="text-embedding-3-large"
    )
"""

from decimal import Decimal
from typing import Any, Dict, Optional

from django.core.cache import cache
from loguru import logger


class AICostEstimator:
    """Estimates AI processing costs based on token counts and pricing data"""

    # Cache TTL for pricing lookups (1 hour)
    PRICING_CACHE_TTL = 3600

    def __init__(self):
        """Initialize the cost estimator"""
        self._tiktoken_available = self._check_tiktoken()

    def _check_tiktoken(self) -> bool:
        """Check if tiktoken is available"""
        try:
            pass

            return True
        except ImportError:
            logger.warning(
                "tiktoken library not available. Token counting will use approximations. "
                "Install with: pip install tiktoken"
            )
            return False

    def count_tokens(self, text: str, model: str = "gpt-4") -> int:
        """
        Count tokens in text using tiktoken or approximation.

        Args:
            text: The text to count tokens for
            model: Model name for encoding selection

        Returns:
            Estimated token count
        """
        if not text:
            return 0

        if self._tiktoken_available:
            try:
                import tiktoken

                # Try to get encoding for specific model
                try:
                    encoding = tiktoken.encoding_for_model(model)
                except KeyError:
                    # Fallback to cl100k_base (used by gpt-4, gpt-3.5-turbo)
                    encoding = tiktoken.get_encoding("cl100k_base")

                return len(encoding.encode(text))
            except Exception as e:
                logger.warning(f"Error using tiktoken: {e}. Using approximation.")

        # Approximation: ~4 characters per token for English text
        return len(text) // 4

    def get_pricing(self, provider: str, model_name: str) -> Optional[Any]:
        """
        Get pricing information for a provider/model combination.
        Uses caching to reduce database queries.

        Args:
            provider: Provider name (e.g., "OPENAI", "ANTHROPIC")
            model_name: Model name (e.g., "gpt-4-turbo")

        Returns:
            AIModelPricing instance or None
        """
        from core.models.ai_pricing import AIModelPricing

        cache_key = f"ai_pricing:{provider}:{model_name}"
        pricing = cache.get(cache_key)

        if pricing is None:
            pricing = AIModelPricing.get_active_pricing(provider, model_name)
            if pricing:
                cache.set(cache_key, pricing, self.PRICING_CACHE_TTL)

        return pricing

    def estimate_analysis_cost(
        self,
        text: str,
        provider: str,
        model_name: str,
        task_type: str = None,
        custom_overhead: Optional[float] = None,
        custom_output_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Estimate the cost of AI analysis on text.

        Args:
            text: The input text to analyze
            provider: AI provider name
            model_name: Specific model name
            task_type: Type of analysis task (optional, for reference only)
            custom_overhead: Prompt overhead ratio (default 0.05 = 5%)
            custom_output_ratio: Output as ratio of input (default 0.20 = 20%)

        Returns:
            Dictionary with cost breakdown:
            {
                'input_tokens': int,
                'input_tokens_with_overhead': int,
                'output_tokens': int,
                'input_cost_usd': Decimal,
                'output_cost_usd': Decimal,
                'total_cost_usd': Decimal,
                'pricing_available': bool,
                'model': str,
                'provider': str
            }
        """
        # Count base tokens
        base_tokens = self.count_tokens(text, model_name)

        # Apply overhead (use custom or default to 5%)
        overhead_ratio = (
            Decimal(str(custom_overhead))
            if custom_overhead is not None
            else Decimal("0.05")
        )
        input_tokens_with_overhead = int(base_tokens * (1 + float(overhead_ratio)))

        # Estimate output tokens (use custom or default to 20%)
        output_ratio = custom_output_ratio if custom_output_ratio is not None else 0.20
        output_tokens = int(base_tokens * output_ratio)

        # Get pricing
        pricing = self.get_pricing(provider, model_name)

        result = {
            "input_tokens": base_tokens,
            "input_tokens_with_overhead": input_tokens_with_overhead,
            "output_tokens": output_tokens,
            "pricing_available": pricing is not None,
            "model": model_name,
            "provider": provider,
            "task_type": task_type,
        }

        if pricing:
            # Calculate costs using pricing model methods
            input_price_per_token = pricing.get_input_price_per_token()
            output_price_per_token = pricing.get_output_price_per_token()

            input_cost = (
                Decimal(str(input_tokens_with_overhead)) * input_price_per_token
            )
            output_cost = Decimal(str(output_tokens)) * output_price_per_token

            result.update(
                {
                    "input_cost_usd": input_cost,
                    "output_cost_usd": output_cost,
                    "total_cost_usd": input_cost + output_cost,
                    "input_price_per_token": input_price_per_token,
                    "output_price_per_token": output_price_per_token,
                }
            )
        else:
            logger.warning(
                f"No pricing available for {provider}/{model_name}. "
                "Cost estimation incomplete."
            )
            result.update(
                {
                    "input_cost_usd": None,
                    "output_cost_usd": None,
                    "total_cost_usd": None,
                }
            )

        return result

    def estimate_embedding_cost(
        self, text: str, provider: str, model_name: str
    ) -> Dict[str, Any]:
        """
        Estimate the cost of generating embeddings for text.

        Args:
            text: The input text to embed
            provider: Embedding provider name
            model_name: Specific embedding model name

        Returns:
            Dictionary with cost breakdown:
            {
                'input_tokens': int,
                'cost_usd': Decimal,
                'pricing_available': bool,
                'model': str,
                'provider': str
            }
        """
        # Count tokens
        tokens = self.count_tokens(text, model_name)

        # Get pricing
        pricing = self.get_pricing(provider, model_name)

        result = {
            "input_tokens": tokens,
            "pricing_available": pricing is not None,
            "model": model_name,
            "provider": provider,
        }

        if pricing:
            # Calculate cost using pricing model methods
            input_price_per_token = pricing.get_input_price_per_token()
            cost = Decimal(str(tokens)) * input_price_per_token

            result.update(
                {
                    "cost_usd": cost,
                    "price_per_token": input_price_per_token,
                }
            )
        else:
            logger.warning(
                f"No pricing available for {provider}/{model_name}. "
                "Cost estimation incomplete."
            )
            result["cost_usd"] = None

        return result

    def estimate_extraction_batch_cost(
        self, extraction_ids: list, provider: str, model_name: str, task_type: str
    ) -> Dict[str, Any]:
        """
        Estimate total cost for processing a batch of DocumentExtraction records.

        Args:
            extraction_ids: List of DocumentExtraction IDs
            provider: AI provider name
            model_name: Model name
            task_type: Type of analysis

        Returns:
            Dictionary with aggregated cost estimates and per-document breakdown
        """
        from core.models.document_analysis import DocumentExtraction

        extractions = DocumentExtraction.objects.filter(id__in=extraction_ids).only(
            "id", "raw_text", "character_count"
        )

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = Decimal("0")
        estimates = []

        for extraction in extractions:
            if not extraction.raw_text:
                continue

            estimate = self.estimate_analysis_cost(
                text=extraction.raw_text,
                provider=provider,
                model_name=model_name,
                task_type=task_type,
            )

            estimates.append({"extraction_id": extraction.id, **estimate})

            total_input_tokens += estimate["input_tokens_with_overhead"]
            total_output_tokens += estimate["output_tokens"]

            if estimate["total_cost_usd"]:
                total_cost += estimate["total_cost_usd"]

        return {
            "total_documents": len(estimates),
            "total_input_tokens": total_input_tokens,
            "total_output_tokens": total_output_tokens,
            "total_cost_usd": total_cost,
            "per_document_estimates": estimates,
            "provider": provider,
            "model": model_name,
            "task_type": task_type,
        }


def estimate_document_analysis_cost(
    text: str, provider: str, model_name: str, task_type: str = "summary"
) -> Dict[str, Any]:
    """
    Convenience function for estimating analysis cost.

    Args:
        text: Text to analyze
        provider: AI provider
        model_name: Model name
        task_type: Analysis task type

    Returns:
        Cost estimate dictionary
    """
    estimator = AICostEstimator()
    return estimator.estimate_analysis_cost(text, provider, model_name, task_type)


def estimate_embedding_cost(
    text: str, provider: str, model_name: str
) -> Dict[str, Any]:
    """
    Convenience function for estimating embedding cost.

    Args:
        text: Text to embed
        provider: Embedding provider
        model_name: Model name

    Returns:
        Cost estimate dictionary
    """
    estimator = AICostEstimator()
    return estimator.estimate_embedding_cost(text, provider, model_name)
