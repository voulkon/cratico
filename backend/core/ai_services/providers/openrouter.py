"""
OpenRouter LLM Provider Implementation

Provides access to all models available through OpenRouter
(https://openrouter.ai) using the OpenAI-compatible chat completions API.

Supports:
- Chat completions (``POST /chat/completions``)
- Model listing with pricing (``GET /models``)
- Key validation (``GET /key/info``)

All responses are funneled through ``BaseLLMProvider._standardize_response``
so cost tracking and token accounting work identically to the AWS Bedrock
provider.
"""

import time
from decimal import Decimal
from typing import Any, Dict, List, Optional

import requests
from core.ai_services.base import BaseLLMProvider
from django.conf import settings
from loguru import logger

# Module-level session for connection pooling
_session = requests.Session()


class OpenRouterProvider(BaseLLMProvider):
    """
    OpenRouter provider implementation.

    Usage::

        provider = OpenRouterProvider("OPENROUTER", "anthropic/claude-3.5-sonnet")
        result = provider.invoke(text="...", prompt="Summarize this", temperature=0.3)
    """

    def __init__(
        self,
        provider_name: str,
        model_name: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        """
        Initialize OpenRouter provider.

        Args:
            provider_name: Should be ``"OPENROUTER"``.
            model_name: OpenRouter model ID (e.g. ``"anthropic/claude-3.5-sonnet"``).
            api_key: OpenRouter API key. Falls back to ``settings.OPENROUTER_API_KEY``.
            base_url: API base URL. Falls back to ``settings.OPENROUTER_API_BASE``.
        """
        super().__init__(provider_name, model_name)
        self.api_key = api_key or getattr(settings, "OPENROUTER_API_KEY", "")
        self.base_url = (base_url or getattr(settings, "OPENROUTER_API_BASE", "")).rstrip("/")

        if not self.api_key:
            logger.warning(
                "OpenRouterProvider initialized without an API key. "
                "Calls will fail unless a key is provided at invoke time."
            )

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------
    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            # OpenRouter recommends these for analytics:
            "HTTP-Referer": getattr(settings, "OPENROUTER_REFERER", "") or "https://crati.local",
            "X-Title": "Crati AI Summarization",
        }

    # ------------------------------------------------------------------
    # invoke()
    # ------------------------------------------------------------------
    def invoke(
        self,
        text: str,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Invoke an OpenRouter chat completion.

        Args:
            text: Input text to process (user message content).
            prompt: System/instruction prompt (system message content).
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum output tokens.
            **kwargs: Extra fields merged into the request body (e.g. ``tools``).

        Returns:
            Standardized response dictionary (see ``BaseLLMProvider``).
        """
        if not self.api_key:
            return self._standardize_response(
                success=False,
                text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
                error="No OpenRouter API key configured.",
            )

        messages = []
        if prompt:
            messages.append({"role": "system", "content": prompt})
        messages.append({"role": "user", "content": text})

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        # Merge extra kwargs (tools, top_p, etc.)
        payload.update(kwargs)

        url = f"{self.base_url}/chat/completions"
        start = time.monotonic()

        try:
            resp = _session.post(
                url, json=payload, headers=self._headers(), timeout=120
            )
            latency_ms = int((time.monotonic() - start) * 1000)

            if resp.status_code != 200:
                error_msg = f"OpenRouter API error {resp.status_code}: {resp.text[:500]}"
                logger.error(error_msg)
                return self._standardize_response(
                    success=False,
                    text=None,
                    input_tokens=0,
                    output_tokens=0,
                    latency_ms=latency_ms,
                    error=error_msg,
                    metadata={"status_code": resp.status_code},
                )

            data = resp.json()
            choices = data.get("choices", [])
            generated_text = ""
            finish_reason = None
            if choices:
                choice = choices[0]
                # .get() returns None when the key exists but has a null value,
                # so use `or ""` to fall back to an empty string in that case.
                generated_text = choice.get("message", {}).get("content") or ""
                finish_reason = choice.get("finish_reason")

            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)

            # OpenRouter returns a cost field in the usage object.
            # Use it directly instead of local pricing tables so we always
            # match what OpenRouter actually charged.
            raw_cost = usage.get("cost")
            cost_from_provider = Decimal(str(raw_cost)) if raw_cost is not None else None

            metadata = {
                "id": data.get("id"),
                "model": data.get("model"),
                "finish_reason": finish_reason,
            }

            # A 200 response with empty content is still a failure: a reasoning
            # model can burn its whole token budget on "thinking" and never emit
            # an answer (content=null, completion_tokens>0).  Fail loudly instead
            # of letting an empty string silently propagate downstream.
            if not generated_text.strip():
                error_msg = (
                    f"OpenRouter returned empty content for model={self.model_name} "
                    f"(finish_reason={finish_reason}, output_tokens={output_tokens})"
                )
                logger.error(error_msg)
                return self._standardize_response(
                    success=False,
                    text=None,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    latency_ms=latency_ms,
                    error=error_msg,
                    metadata=metadata,
                    cost_from_provider=cost_from_provider,
                )

            logger.info(
                f"OpenRouter call ok: model={self.model_name} "
                f"in={input_tokens} out={output_tokens} latency={latency_ms}ms "
                f"cost={cost_from_provider}"
            )

            return self._standardize_response(
                success=True,
                text=generated_text,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                latency_ms=latency_ms,
                metadata=metadata,
                cost_from_provider=cost_from_provider,
            )

        except requests.exceptions.Timeout:
            latency_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"OpenRouter request timed out after {latency_ms}ms"
            logger.error(error_msg)
            return self._standardize_response(
                success=False,
                text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                error=error_msg,
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            error_msg = f"OpenRouter request failed: {exc}"
            logger.error(error_msg, exc_info=True)
            return self._standardize_response(
                success=False,
                text=None,
                input_tokens=0,
                output_tokens=0,
                latency_ms=latency_ms,
                error=error_msg,
            )

    # ------------------------------------------------------------------
    # Class-level helpers (no instance state needed)
    # ------------------------------------------------------------------
    @classmethod
    def list_models(cls, api_key: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Fetch the OpenRouter model catalogue.

        Returns a list of dicts with keys:
        ``id``, ``name``, ``context_length``, ``pricing`` (``prompt``,
        ``completion`` — per-token USD).
        """
        base_url = getattr(settings, "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
        headers = {"Content-Type": "application/json"}
        key = api_key or getattr(settings, "OPENROUTER_API_KEY", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"

        resp = _session.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", [])
        return [
            {
                "id": m.get("id"),
                "name": m.get("name") or m.get("id"),
                "context_length": m.get("context_length"),
                "pricing": {
                    "prompt": m.get("pricing", {}).get("prompt", "0"),
                    "completion": m.get("pricing", {}).get("completion", "0"),
                },
            }
            for m in data
        ]

    @classmethod
    def check_key(cls, api_key: str) -> Dict[str, Any]:
        """
        Validate an OpenRouter API key via ``GET /key``.

        Returns a dict with ``is_valid``, ``limit_total``, ``limit_remaining``,
        ``limit_used``, and raw ``data``.
        """
        base_url = getattr(settings, "OPENROUTER_API_BASE", "https://openrouter.ai/api/v1")
        headers = {"Authorization": f"Bearer {api_key}"}
        try:
            resp = _session.get(
                f"{base_url.rstrip('/')}/key", headers=headers, timeout=15
            )
            if resp.status_code == 200:
                data = resp.json().get("data", {})
                return {
                    "is_valid": True,
                    "limit_total": data.get("limit"),
                    "limit_remaining": data.get("limit_remaining"),
                    "limit_used": data.get("usage"),
                    "data": data,
                }
            return {"is_valid": False, "error": f"HTTP {resp.status_code}", "data": {}}
        except Exception as exc:
            return {"is_valid": False, "error": str(exc), "data": {}}
