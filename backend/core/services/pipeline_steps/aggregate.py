"""
AggregateStep — merges per-item outputs into a single result.

Config:
    strategy: "concat" (default) or "summarize_each_then_merge"
    merge_prompt_template: Jinja2 template for the merge AI call
    max_tokens: 1000 (default, for the merge call)
    provider: "OPENROUTER" (default, for merge call)
    model: model ID (for merge call)
"""

from decimal import Decimal

from core.ai_services.factory import get_provider
from core.models.pipeline import PipelineStepRun
from core.services.cost_ledger_service import CostLedgerService
from core.services.pipeline_engine import PipelineContext
from loguru import logger


class AggregateStep:
    """Aggregates per-item outputs into a final result."""

    def execute(self, step, step_run: PipelineStepRun, context: PipelineContext, run):
        config = step.config or {}
        strategy = config.get("strategy", "concat")

        if strategy == "concat":
            self._concat(context, step)
        elif strategy == "summarize_each_then_merge":
            self._summarize_merge(context, step, step_run, run)
        else:
            raise ValueError(f"Unknown aggregate strategy: {strategy}")

        step_run.output_text = (context.steps_output.get(step.order) or "")[:10000]
        step_run.save()

        logger.info(f"AggregateStep: strategy={strategy}")

    # ------------------------------------------------------------------
    # Strategies
    # ------------------------------------------------------------------
    def _concat(self, context: PipelineContext, step):
        """Simply join per-item outputs."""
        joined = "\n---\n".join(context.per_item_outputs.values())
        context.steps_output[step.order] = joined

    def _summarize_merge(self, context: PipelineContext, step, step_run, run):
        """Run a final AI call over the joined per-item summaries."""
        config = step.config or {}
        provider_name = config.get("provider", "OPENROUTER")
        model_name = config.get("model", "")
        merge_template = config.get(
            "merge_prompt_template",
            "Synthesize a single summary of these decision summaries:\n{{ text }}",
        )
        max_tokens = config.get("max_tokens", 1000)
        temperature = config.get("temperature", 0.3)

        # Build the text from per-item outputs
        items_text = "\n---\n".join(context.per_item_outputs.values())

        # Render the merge prompt
        from core.services.pipeline_steps.ai_call import AICallStep

        ai_call = AICallStep()
        rendered = ai_call._render_prompt(merge_template, items_text, context, step)

        # Resolve API key
        api_key = ai_call._resolve_api_key(context.user)
        provider = get_provider(provider_name, model_name, api_key=api_key)

        result = provider.invoke(
            text=rendered,
            prompt=config.get("system_prompt", "You are a legal analyst."),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # Log the interaction
        CostLedgerService.log_interaction(
            user=context.user,
            billed_to=run.billed_to,
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

        if result.get("success"):
            context.steps_output[step.order] = result["text"]
            step_run.input_tokens = result["input_tokens"]
            step_run.output_tokens = result["output_tokens"]
            step_run.cost_usd = Decimal(str(result.get("actual_cost_usd", 0)))
            step_run.input_preview = rendered[:5000]
        else:
            raise RuntimeError(f"Aggregate merge call failed: {result.get('error')}")
