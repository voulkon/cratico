"""
Base LLM Provider

Abstract base class that all LLM providers must implement.
Ensures consistent monitoring, cost tracking, and token usage recording.
"""

from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, Optional

from core.utils.ai_cost_estimator import AICostEstimator
from loguru import logger


class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM providers.

    All provider implementations must:
    1. Track input/output tokens
    2. Calculate actual costs using AIModelPricing
    3. Measure latency
    4. Support both estimation and actual invocation
    5. Return standardized response format

    Usage:
        provider = AWSBedrockProvider("AWS_BEDROCK", "anthropic.claude-3-haiku-20240307-v1:0")

        # Estimate only (no API call)
        estimate = provider.estimate_cost(text="...", prompt="...")

        # Actual invocation
        result = provider.invoke(text="...", prompt="...", temperature=0.7)
    """

    def __init__(self, provider_name: str, model_name: str):
        """
        Initialize provider.

        Args:
            provider_name: Provider identifier (e.g., "AWS_BEDROCK", "OPENAI")
            model_name: Specific model name/ID
        """
        self.provider_name = provider_name
        self.model_name = model_name
        self.cost_estimator = AICostEstimator()

        # Validate pricing exists
        pricing = self.cost_estimator.get_pricing(provider_name, model_name)
        if not pricing:
            logger.warning(
                f"No pricing found for {provider_name}/{model_name}. "
                "Cost tracking will be incomplete."
            )

    @abstractmethod
    def invoke(
        self,
        text: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Invoke the LLM provider with actual API call.

        Args:
            text: Input text to process
            prompt: System/instruction prompt
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum output tokens (None = use model default)
            **kwargs: Provider-specific parameters

        Returns:
            Standardized response dictionary:
            {
                'success': bool,              # Whether call succeeded
                'text': str,                  # Generated text response
                'input_tokens': int,          # Actual input tokens used
                'output_tokens': int,         # Actual output tokens generated
                'estimated_cost_usd': Decimal,# Estimated cost before call
                'actual_cost_usd': Decimal,   # Actual cost based on tokens
                'latency_ms': int,            # Call latency in milliseconds
                'model': str,                 # Model used
                'provider': str,              # Provider name
                'error': str,                 # Error message if failed (optional)
                'metadata': dict              # Provider-specific metadata (optional)
            }
        """

    def estimate_cost(
        self,
        text: str,
        prompt: str,
        custom_overhead: Optional[float] = None,
        custom_output_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Estimate cost without making actual API call.

        Args:
            text: Input text
            prompt: System prompt
            custom_overhead: Custom prompt overhead ratio
            custom_output_ratio: Custom output ratio

        Returns:
            Estimation dictionary (same format as invoke but without 'text' field)
        """
        # Combine text and prompt for token counting
        full_input = f"{prompt}\n\n{text}"

        estimate = self.cost_estimator.estimate_analysis_cost(
            text=full_input,
            provider=self.provider_name,
            model_name=self.model_name,
            task_type=None,
            custom_overhead=custom_overhead,
            custom_output_ratio=custom_output_ratio,
        )

        return {
            "success": True,
            "input_tokens": estimate["input_tokens_with_overhead"],
            "output_tokens": estimate["output_tokens"],
            "estimated_cost_usd": estimate.get("total_cost_usd", Decimal("0")),
            "actual_cost_usd": estimate.get(
                "total_cost_usd", Decimal("0")
            ),  # Same as estimate
            "latency_ms": 0,  # No actual call
            "model": self.model_name,
            "provider": self.provider_name,
            "is_estimate": True,
        }

    def calculate_cost(self, input_tokens: int, output_tokens: int) -> Decimal:
        """
        Calculate actual cost based on token counts.

        Args:
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens

        Returns:
            Total cost in USD
        """
        pricing = self.cost_estimator.get_pricing(self.provider_name, self.model_name)

        if not pricing:
            logger.warning(
                f"No pricing available for {self.provider_name}/{self.model_name}"
            )
            return Decimal("0")

        return pricing.calculate_cost(input_tokens, output_tokens)

    def _standardize_response(
        self,
        success: bool,
        text: Optional[str],
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
        error: Optional[str] = None,
        metadata: Optional[Dict] = None,
        cost_from_provider: Optional[Decimal] = None,
    ) -> Dict[str, Any]:
        """
        Create standardized response dictionary.

        Internal helper to ensure consistent response format.

        Args:
            cost_from_provider: When the API response includes a cost field
                (e.g. OpenRouter's ``usage.cost``), pass it here to use the
                provider's own cost calculation instead of the local pricing
                tables.  Falls back to local calculation when ``None``.
        """
        # estimated_cost always uses local pricing tables for comparability
        estimated_cost = self.calculate_cost(input_tokens, output_tokens)
        # actual cost uses the provider's reported value when available,
        # otherwise falls back to local calculation
        actual_cost = (
            cost_from_provider
            if cost_from_provider is not None
            else self.calculate_cost(input_tokens, output_tokens)
        )

        response = {
            "success": success,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "estimated_cost_usd": estimated_cost,
            "actual_cost_usd": actual_cost,
            "latency_ms": latency_ms,
            "model": self.model_name,
            "provider": self.provider_name,
            "is_estimate": False,
        }

        if text is not None:
            response["text"] = text

        if error:
            response["error"] = error

        if metadata:
            response["metadata"] = metadata

        return response

    def __repr__(self):
        return f"{self.__class__.__name__}(provider={self.provider_name}, model={self.model_name})"
