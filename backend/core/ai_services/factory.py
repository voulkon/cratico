"""
Provider Factory

Central factory for instantiating LLM providers.
Ensures consistent provider creation and error handling.
"""

from typing import Optional

from core.ai_services.base import BaseLLMProvider
from core.ai_services.providers.aws_bedrock import AWSBedrockProvider
from loguru import logger


def get_provider(
    provider_name: str, model_name: str, region_name: Optional[str] = None, **kwargs
) -> BaseLLMProvider:
    """
    Factory function to get the appropriate LLM provider instance.

    Args:
        provider_name: Provider identifier (e.g., "AWS_BEDROCK", "OPENAI", "OPENROUTER")
        model_name: Model name/ID specific to the provider
        region_name: AWS region (only for AWS_BEDROCK)
        **kwargs: Provider-specific configuration

    Returns:
        Initialized provider instance

    Raises:
        ValueError: If provider is not supported

    Example:
        # AWS Bedrock
        provider = get_provider("AWS_BEDROCK", "anthropic.claude-3-haiku-20240307-v1:0")
        result = provider.invoke(text="...", prompt="...")

        # Future: OpenAI
        # provider = get_provider("OPENAI", "gpt-4-turbo-2024-04-09")
    """
    provider_upper = provider_name.upper()

    if provider_upper == "AWS_BEDROCK":
        region = region_name or kwargs.get("region", "us-east-1")
        api_key = kwargs.get("api_key")  # Allow passing API key
        logger.info(f"Creating AWS Bedrock provider for model: {model_name}")
        return AWSBedrockProvider(
            provider_name=provider_name,
            model_name=model_name,
            region_name=region,
            api_key=api_key,
        )

    elif provider_upper == "OPENAI":
        # TODO: Implement when needed
        raise NotImplementedError(
            "OpenAI provider not yet implemented. " "Use AWS_BEDROCK for now."
        )

    elif provider_upper == "OPENROUTER":
        # TODO: Implement when needed
        raise NotImplementedError(
            "OpenRouter provider not yet implemented. " "Use AWS_BEDROCK for now."
        )

    elif provider_upper == "ANTHROPIC":
        # Direct Anthropic API (not through Bedrock)
        # TODO: Implement when needed
        raise NotImplementedError(
            "Direct Anthropic provider not yet implemented. "
            "Use AWS_BEDROCK with Claude models for now."
        )

    else:
        raise ValueError(
            f"Unsupported provider: {provider_name}. "
            f"Supported providers: AWS_BEDROCK"
        )


# Convenience aliases
create_provider = get_provider
get_llm_provider = get_provider
