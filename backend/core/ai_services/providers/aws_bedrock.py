"""
AWS Bedrock Provider Implementation

Provides access to AWS Bedrock models (Claude, Titan, Nova, etc.)
with built-in monitoring and cost tracking.
"""

import json
import time
from typing import Any, Dict, Optional

import boto3
from core.ai_services.base import BaseLLMProvider
from loguru import logger


class AWSBedrockProvider(BaseLLMProvider):
    """
    AWS Bedrock provider implementation.

    Supports:
    - Anthropic Claude models (Haiku, Sonnet, Opus)
    - Amazon Titan models
    - Amazon Nova models
    - Meta Llama models

    Usage:
        provider = AWSBedrockProvider("AWS_BEDROCK", "anthropic.claude-3-haiku-20240307-v1:0")

        result = provider.invoke(
            text="Document to analyze...",
            prompt="Summarize this document",
            temperature=0.7
        )
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        region_name: str = "us-east-1",
        api_key: str = None,
    ):
        """
        Initialize AWS Bedrock provider.

        Supports two authentication methods:
        1. API Key (newer): Pass api_key or set AWS_BEARER_TOKEN_BEDROCK env var
        2. IAM credentials (traditional): AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY

        Args:
            provider_name: Should be "AWS_BEDROCK"
            model_name: Full Bedrock model ID (e.g., "anthropic.claude-3-haiku-20240307-v1:0")
            region_name: AWS region for Bedrock service
            api_key: Optional Bedrock API key (overrides env var)
        """
        super().__init__(provider_name, model_name)

        import os

        self.region_name = region_name
        self.api_key = api_key or os.getenv("AWS_BEARER_TOKEN_BEDROCK")

        # Create bedrock client with appropriate auth
        client_kwargs = {"service_name": "bedrock-runtime", "region_name": region_name}

        # If API key is provided, use it
        # Note: As of Dec 2025, boto3 might not directly support API keys yet
        # This is a placeholder for when AWS releases official support
        if self.api_key:
            logger.info("Using Bedrock API Key for authentication")
            # TODO: Update this when AWS releases official boto3 API key support
            # For now, API key might need to be passed as custom headers
            # client_kwargs['api_key'] = self.api_key
            logger.warning(
                "API Key authentication may require boto3 update. "
                "Falling back to IAM credentials if available."
            )

        self.bedrock_client = boto3.client(**client_kwargs)

        # Determine model family for request formatting
        self.model_family = self._detect_model_family(model_name)
        logger.info(
            f"Initialized AWS Bedrock provider for {model_name} ({self.model_family})"
        )

    def _detect_model_family(self, model_name: str) -> str:
        """Detect model family from model ID"""
        model_lower = model_name.lower()

        if "claude" in model_lower or "anthropic" in model_lower:
            return "claude"
        elif "titan" in model_lower:
            return "titan"
        elif "nova" in model_lower:
            return "nova"
        elif "llama" in model_lower:
            return "llama"
        elif "mistral" in model_lower:
            return "mistral"
        else:
            logger.warning(
                f"Unknown model family for {model_name}, defaulting to 'claude'"
            )
            return "claude"

    def invoke(
        self,
        text: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Invoke AWS Bedrock model.

        Args:
            text: Input text to process
            prompt: System/instruction prompt
            temperature: Sampling temperature (0.0 to 1.0)
            max_tokens: Maximum output tokens (defaults to model default)
            **kwargs: Model-specific parameters

        Returns:
            Standardized response with actual token usage and costs
        """
        start_time = time.time()

        # Set default max_tokens if not provided
        if max_tokens is None:
            max_tokens = 2048  # Reasonable default

        try:
            # Format request based on model family
            if self.model_family == "claude":
                body = self._format_claude_request(
                    text, prompt, temperature, max_tokens, **kwargs
                )
            elif self.model_family == "titan":
                body = self._format_titan_request(
                    text, prompt, temperature, max_tokens, **kwargs
                )
            elif self.model_family == "nova":
                body = self._format_nova_request(
                    text, prompt, temperature, max_tokens, **kwargs
                )
            else:
                # Generic format (Claude-like)
                body = self._format_claude_request(
                    text, prompt, temperature, max_tokens, **kwargs
                )

            # Invoke Bedrock
            response = self.bedrock_client.invoke_model(
                modelId=self.model_name, body=json.dumps(body)
            )

            # Calculate latency
            latency_ms = int((time.time() - start_time) * 1000)

            # Parse response based on model family
            response_body = json.loads(response["body"].read())

            if self.model_family == "claude":
                result_text, input_tokens, output_tokens = self._parse_claude_response(
                    response_body
                )
            elif self.model_family == "titan":
                result_text, input_tokens, output_tokens = self._parse_titan_response(
                    response_body
                )
            elif self.model_family == "nova":
                result_text, input_tokens, output_tokens = self._parse_nova_response(
                    response_body
                )
            else:
                result_text, input_tokens, output_tokens = self._parse_claude_response(
                    response_body
                )

            # Create standardized response with cost tracking
            return self._standardize_response(
                success=True,
                text=result_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                metadata={
                    "model_family": self.model_family,
                    "region": self.region_name,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            )

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            logger.error(f"Error invoking Bedrock model {self.model_name}: {e}")

            return self._standardize_response(
                success=False,
                text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                error=str(e),
            )

    def _format_claude_request(
        self, text: str, prompt: str, temperature: float, max_tokens: int, **kwargs
    ) -> Dict[str, Any]:
        """Format request for Claude models"""
        return {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": f"{prompt}\n\n{text}"}],
        }

    def _format_titan_request(
        self, text: str, prompt: str, temperature: float, max_tokens: int, **kwargs
    ) -> Dict[str, Any]:
        """Format request for Titan models"""
        return {
            "inputText": f"{prompt}\n\n{text}",
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
                "topP": kwargs.get("top_p", 0.9),
                "stopSequences": kwargs.get("stop_sequences", []),
            },
        }

    def _format_nova_request(
        self, text: str, prompt: str, temperature: float, max_tokens: int, **kwargs
    ) -> Dict[str, Any]:
        """Format request for Nova models"""
        return {
            "messages": [
                {"role": "user", "content": [{"text": f"{prompt}\n\n{text}"}]}
            ],
            "inferenceConfig": {
                "max_new_tokens": max_tokens,
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.9),
            },
        }

    def _parse_claude_response(self, response_body: Dict) -> tuple[str, int, int]:
        """Parse Claude model response"""
        content = response_body.get("content", [])
        result_text = ""
        if content and len(content) > 0:
            result_text = content[0].get("text", "")

        usage = response_body.get("usage", {})
        input_tokens = usage.get("input_tokens", 0)
        output_tokens = usage.get("output_tokens", 0)

        return result_text, input_tokens, output_tokens

    def _parse_titan_response(self, response_body: Dict) -> tuple[str, int, int]:
        """Parse Titan model response"""
        results = response_body.get("results", [])
        result_text = ""
        if results and len(results) > 0:
            result_text = results[0].get("outputText", "")

        input_tokens = response_body.get("inputTextTokenCount", 0)

        # Titan doesn't always return output token count, estimate it
        output_tokens = 0
        if results and len(results) > 0:
            output_tokens = results[0].get("tokenCount", 0)

        return result_text, input_tokens, output_tokens

    def _parse_nova_response(self, response_body: Dict) -> tuple[str, int, int]:
        """Parse Nova model response"""
        output = response_body.get("output", {})
        message = output.get("message", {})
        content = message.get("content", [])

        result_text = ""
        if content and len(content) > 0:
            result_text = content[0].get("text", "")

        usage = response_body.get("usage", {})
        input_tokens = usage.get("inputTokens", 0)
        output_tokens = usage.get("outputTokens", 0)

        return result_text, input_tokens, output_tokens


# Convenience function for backward compatibility
def invoke_bedrock_model(
    text: str,
    model_id: str,
    prompt: str,
    track_cost: bool = True,
    task_type: str = "summary",
    temperature: float = 0.7,
    max_tokens: int = 2048,
    region_name: str = "us-east-1",
) -> Dict[str, Any]:
    """
    Convenience function to invoke Bedrock models (maintains backward compatibility).

    Args:
        text: Input text
        model_id: Bedrock model ID
        prompt: Instruction prompt
        track_cost: Whether to track costs (always True now)
        task_type: Task type (unused, kept for compatibility)
        temperature: Sampling temperature
        max_tokens: Maximum output tokens
        region_name: AWS region

    Returns:
        Result dictionary with text, tokens, and costs
    """
    provider = AWSBedrockProvider("AWS_BEDROCK", model_id, region_name)
    return provider.invoke(
        text=text, prompt=prompt, temperature=temperature, max_tokens=max_tokens
    )
