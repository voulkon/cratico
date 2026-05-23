"""
AWS Bedrock Integration for Cost Estimation

This module provides utilities for using AWS Bedrock with the cost estimator.
AWS Bedrock provides access to various foundation models including Claude, Titan, and more.

Example usage:
    from core.utils.bedrock_helper import estimate_bedrock_cost, invoke_bedrock_model

    # Estimate cost
    cost = estimate_bedrock_cost(
        text="Document to analyze...",
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        task_type="summary"
    )
    print(f"Estimated cost: ${cost['total_cost_usd']:.6f}")

    # Invoke model with cost tracking
    result = invoke_bedrock_model(
        text="Document to analyze...",
        model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        prompt="Summarize this document:",
        track_cost=True
    )
"""

import json
from decimal import Decimal
from typing import Any, Dict, Optional

import boto3
from core.utils.ai_cost_estimator import AICostEstimator
from loguru import logger


class BedrockHelper:
    """Helper class for AWS Bedrock operations with cost tracking"""

    def __init__(self, region_name: str = "us-east-1"):
        """
        Initialize Bedrock helper.

        Args:
            region_name: AWS region for Bedrock service
        """
        self.bedrock_client = boto3.client(
            service_name="bedrock-runtime", region_name=region_name
        )
        self.cost_estimator = AICostEstimator()

    def estimate_cost(
        self,
        text: str,
        model_id: str,
        task_type: str = "summary",
        custom_overhead: Optional[float] = None,
        custom_output_ratio: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Estimate the cost of processing text with a Bedrock model.

        Args:
            text: Input text to process
            model_id: Bedrock model ID (e.g., 'anthropic.claude-3-haiku-20240307-v1:0')
            task_type: Type of task for output estimation
            custom_overhead: Optional custom overhead ratio
            custom_output_ratio: Optional custom output ratio

        Returns:
            Cost estimation dictionary
        """
        # Use model_id directly - pricing comes from database
        return self.cost_estimator.estimate_analysis_cost(
            text=text,
            provider="AWS_BEDROCK",
            model_name=model_id,  # Use full model ID directly
            task_type=task_type,
            custom_overhead=custom_overhead,
            custom_output_ratio=custom_output_ratio,
        )

    def invoke_claude(
        self,
        text: str,
        model_id: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        track_cost: bool = True,
        task_type: str = "summary",
    ) -> Dict[str, Any]:
        """
        Invoke a Claude model on Bedrock with cost tracking.

        Args:
            text: Document text to process
            model_id: Claude model ID
            prompt: Instruction prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            track_cost: Whether to estimate and return cost
            task_type: Type of task for cost estimation

        Returns:
            Dictionary with response and optional cost data
        """
        # Prepare the request
        messages = [{"role": "user", "content": f"{prompt}\n\n{text}"}]

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": messages,
        }

        # Estimate cost before invocation if tracking
        cost_estimate = None
        if track_cost:
            cost_estimate = self.estimate_cost(
                text=text, model_id=model_id, task_type=task_type
            )

        try:
            # Invoke the model
            response = self.bedrock_client.invoke_model(
                modelId=model_id, body=json.dumps(body)
            )

            # Parse response
            response_body = json.loads(response["body"].read())

            # Extract text content
            content = response_body.get("content", [])
            result_text = ""
            if content and len(content) > 0:
                result_text = content[0].get("text", "")

            # Get token usage if available
            usage = response_body.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)

            result = {
                "success": True,
                "text": result_text,
                "model_id": model_id,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

            # Add cost information if tracking
            if track_cost and cost_estimate:
                # Calculate actual cost based on returned token counts
                pricing = self.cost_estimator.get_pricing("AWS_BEDROCK", model_id)

                if pricing and input_tokens > 0:
                    actual_input_cost = (
                        Decimal(str(input_tokens)) / Decimal("1000000")
                    ) * pricing.input_price_per_million

                    actual_output_cost = Decimal("0")
                    if output_tokens > 0 and pricing.output_price_per_million:
                        actual_output_cost = (
                            Decimal(str(output_tokens)) / Decimal("1000000")
                        ) * pricing.output_price_per_million

                    result.update(
                        {
                            "estimated_cost_usd": cost_estimate["total_cost_usd"],
                            "actual_cost_usd": actual_input_cost + actual_output_cost,
                            "input_cost_usd": actual_input_cost,
                            "output_cost_usd": actual_output_cost,
                        }
                    )
                else:
                    result["estimated_cost_usd"] = cost_estimate.get("total_cost_usd")

            return result

        except Exception as e:
            logger.error(f"Error invoking Bedrock model {model_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "model_id": model_id,
            }

    def invoke_titan(
        self,
        text: str,
        model_id: str,
        prompt: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
        track_cost: bool = True,
        task_type: str = "summary",
    ) -> Dict[str, Any]:
        """
        Invoke an Amazon Titan model on Bedrock with cost tracking.

        Args:
            text: Document text to process
            model_id: Titan model ID
            prompt: Instruction prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            track_cost: Whether to estimate and return cost
            task_type: Type of task for cost estimation

        Returns:
            Dictionary with response and optional cost data
        """
        # Prepare the request for Titan
        body = {
            "inputText": f"{prompt}\n\n{text}",
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": temperature,
            },
        }

        # Estimate cost before invocation if tracking
        cost_estimate = None
        if track_cost:
            cost_estimate = self.estimate_cost(
                text=text, model_id=model_id, task_type=task_type
            )

        try:
            # Invoke the model
            response = self.bedrock_client.invoke_model(
                modelId=model_id, body=json.dumps(body)
            )

            # Parse response
            response_body = json.loads(response["body"].read())

            # Extract results
            results = response_body.get("results", [])
            result_text = ""
            if results and len(results) > 0:
                result_text = results[0].get("outputText", "")

            # Titan doesn't always return token counts, so we estimate
            input_tokens = response_body.get("inputTextTokenCount", 0)

            result = {
                "success": True,
                "text": result_text,
                "model_id": model_id,
                "input_tokens": input_tokens,
            }

            if track_cost and cost_estimate:
                result["estimated_cost_usd"] = cost_estimate.get("total_cost_usd")

            return result

        except Exception as e:
            logger.error(f"Error invoking Bedrock model {model_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "model_id": model_id,
            }

    def create_embedding(
        self,
        text: str,
        model_id: str = "amazon.titan-embed-text-v2:0",
        track_cost: bool = True,
    ) -> Dict[str, Any]:
        """
        Create embeddings using Bedrock with cost tracking.

        Args:
            text: Text to embed
            model_id: Embedding model ID
            track_cost: Whether to estimate and return cost

        Returns:
            Dictionary with embedding and optional cost data
        """
        body = {"inputText": text}

        # Estimate cost if tracking
        cost_estimate = None
        if track_cost:
            cost_estimate = self.cost_estimator.estimate_embedding_cost(
                text=text, provider="AWS_BEDROCK", model_name=model_id
            )

        try:
            response = self.bedrock_client.invoke_model(
                modelId=model_id, body=json.dumps(body)
            )

            response_body = json.loads(response["body"].read())
            embedding = response_body.get("embedding", [])

            result = {
                "success": True,
                "embedding": embedding,
                "dimensions": len(embedding),
                "model_id": model_id,
            }

            if track_cost and cost_estimate:
                result.update(
                    {
                        "estimated_cost_usd": cost_estimate.get("cost_usd"),
                        "input_tokens": cost_estimate.get("input_tokens"),
                    }
                )

            return result

        except Exception as e:
            logger.error(f"Error creating embedding with {model_id}: {e}")
            return {
                "success": False,
                "error": str(e),
                "model_id": model_id,
            }


# Convenience functions
def estimate_bedrock_cost(
    text: str, model_id: str, task_type: str = "summary"
) -> Dict[str, Any]:
    """
    Convenience function to estimate Bedrock model cost.

    Args:
        text: Input text
        model_id: Bedrock model ID
        task_type: Type of task

    Returns:
        Cost estimation dictionary
    """
    helper = BedrockHelper()
    return helper.estimate_cost(text, model_id, task_type)


def invoke_bedrock_model(
    text: str,
    model_id: str,
    prompt: str,
    max_tokens: int = 2048,
    temperature: float = 0.7,
    track_cost: bool = True,
    task_type: str = "summary",
    region_name: str = "us-east-1",
) -> Dict[str, Any]:
    """
    DEPRECATED: Use the new provider system instead.

    This function is kept for backward compatibility but internally uses AWSBedrockProvider.

    NEW APPROACH:
        from core.ai_services import get_provider

        provider = get_provider("AWS_BEDROCK", model_id)
        result = provider.invoke(text=text, prompt=prompt, temperature=temperature, max_tokens=max_tokens)

    Args:
        text: Document text
        model_id: Bedrock model ID
        prompt: Instruction prompt
        max_tokens: Maximum output tokens
        temperature: Sampling temperature
        track_cost: Whether to track costs (always True with new system)
        task_type: Type of task (ignored, kept for compatibility)
        region_name: AWS region

    Returns:
        Response dictionary with cost data
    """
    helper = BedrockHelper()

    # Detect model type and use appropriate method
    if "claude" in model_id.lower():
        return helper.invoke_claude(
            text=text,
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            track_cost=track_cost,
            task_type=task_type,
        )
    elif "titan" in model_id.lower():
        return helper.invoke_titan(
            text=text,
            model_id=model_id,
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            track_cost=track_cost,
            task_type=task_type,
        )
    else:
        return {"success": False, "error": f"Unsupported model type: {model_id}"}
