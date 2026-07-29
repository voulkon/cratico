"""
AICallStep — calls an LLM provider for each item (map mode) or once (single mode).

Config:
    provider: "OPENROUTER" (default)
    model: model ID
    prompt_template: Jinja2 template for the user message
    system_prompt: optional system message
    temperature: 0.3 (default)
    max_tokens: 1000 (default)
    map_over_items: true (default) — if true, run once per decision;
                    if false, run once on the joined text
"""

from decimal import Decimal

from core.ai_services.factory import get_provider
from core.models.pipeline import PipelineStepRun, RunStatus
from core.services.cost_ledger_service import CostLedgerService
from core.services.pipeline_engine import PipelineContext
from loguru import logger

# Jinja2 sandboxed environment for prompt rendering
try:
    from jinja2 import Environment, select_autoescape
    from jinja2.sandbox import ImmutableSandboxedEnvironment

    _jinja_env = ImmutableSandboxedEnvironment(autoescape=select_autoescape(["html", "xml"]))
except ImportError:
    _jinja_env = None
    logger.warning("jinja2 not installed — prompt templates will use str.format()")


class AICallStep:
    """Calls an LLM provider, optionally in map mode (one call per item)."""

    def execute(self, step, step_run: PipelineStepRun, context: PipelineContext, run):
        config = step.config or {}
        provider_name = config.get("provider", "OPENROUTER")
        model_name = config.get("model", "")
        prompt_template = config.get("prompt_template", "Summarize: {{ text }}")
        system_prompt = config.get("system_prompt", "")
        temperature = config.get("temperature", 0.3)
        max_tokens = config.get("max_tokens", 1000)
        map_over_items = config.get("map_over_items", True)

        # Resolve API key from user's AI settings
        api_key = self._resolve_api_key(context.user)

        provider = get_provider(provider_name, model_name, api_key=api_key)

        total_input = 0
        total_output = 0
        total_cost = Decimal("0")

        if map_over_items and context.per_item_outputs:
            # Map mode: one call per item
            results = {}
            for item_id, text in context.per_item_outputs.items():
                rendered_prompt = self._render_prompt(
                    prompt_template, text, context, step
                )
                result = provider.invoke(
                    text=rendered_prompt,
                    prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._log_interaction(result, context, run, step_run, item_id=item_id)

                if result.get("success"):
                    results[item_id] = result["text"]
                    total_input += result["input_tokens"]
                    total_output += result["output_tokens"]
                    total_cost += result.get("actual_cost_usd", Decimal("0"))
                else:
                    results[item_id] = f"[ERROR: {result.get('error', 'unknown')}]"
                    logger.warning(f"AICallStep failed for item {item_id}: {result.get('error')}")

            context.per_item_outputs = results
            context.steps_output[step.order] = "\n---\n".join(results.values())
        else:
            # Single mode: one call on joined text
            text = context.steps_output.get(step.order - 1, "") or "\n---\n".join(
                context.per_item_outputs.values()
            )
            rendered_prompt = self._render_prompt(prompt_template, text, context, step)
            result = provider.invoke(
                text=rendered_prompt,
                prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self._log_interaction(result, context, run, step_run)

            if result.get("success"):
                context.steps_output[step.order] = result["text"]
                total_input = result["input_tokens"]
                total_output = result["output_tokens"]
                total_cost = result.get("actual_cost_usd", Decimal("0"))
            else:
                context.steps_output[step.order] = f"[ERROR: {result.get('error')}]"
                raise RuntimeError(f"AI call failed: {result.get('error')}")

        step_run.input_tokens = total_input
        step_run.output_tokens = total_output
        step_run.cost_usd = total_cost
        step_run.output_text = (context.steps_output.get(step.order) or "")[:5000]
        step_run.save()

        logger.info(
            f"AICallStep: provider={provider_name} model={model_name} "
            f"in={total_input} out={total_output} cost=${total_cost:.6f}"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _resolve_api_key(self, user) -> str:
        """Get the user's API key if available, else system fallback."""
        if user is None:
            return ""
        try:
            from core.models.user_ai_settings import UserAISettings

            ai_settings = UserAISettings.get_default_for_user(user)
            return ai_settings.effective_api_key if ai_settings else ""
        except Exception:
            return ""

    def _render_prompt(self, template_str, text, context: PipelineContext, step):
        """Render a Jinja2 prompt template with available variables."""
        template_vars = {
            "text": text,
            "decisions": context.decisions,
            "batch": context.batch,
            "steps": context.steps_output,
            "per_item": [
                {"item_id": k, "output": v}
                for k, v in context.per_item_outputs.items()
            ],
        }

        if _jinja_env is not None:
            try:
                template = _jinja_env.from_string(template_str)
                return template.render(**template_vars)
            except Exception as exc:
                logger.warning(f"Jinja2 render failed ({exc}), falling back to format")
                # Fallback: simple format
                return template_str.replace("{{ text }}", text)

        # No Jinja2: simple replacement
        return template_str.replace("{{ text }}", text)

    def _log_interaction(
        self, result, context, run, step_run, item_id=None
    ):
        """Create an AIInteractionLog entry for this call."""
        billed_to = run.billed_to
        CostLedgerService.log_interaction(
            user=context.user,
            billed_to=billed_to,
            trigger=run.trigger,
            trigger_ref=run.trigger_ref,
            provider=result.get("provider", ""),
            model_name=result.get("model", ""),
            input_tokens=result.get("input_tokens", 0),
            output_tokens=result.get("output_tokens", 0),
            cost_usd=result.get("actual_cost_usd", 0),
            latency_ms=result.get("latency_ms"),
            status="SUCCESS" if result.get("success") else "FAILED",
            error_message=result.get("error"),
            pipeline_run=run,
            pipeline_step_run=step_run,
        )
