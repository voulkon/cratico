"""
AICallStep — calls an LLM provider for each item (map mode) or once (single mode).

Config:
    provider: "OPENROUTER" (default)
    model: model ID
    prompt_template: Jinja2 template for the user message
    system_prompt: optional system message
    temperature: 0.3 (default)
    max_tokens: optional per-step override — falls back to DEFAULT_MAX_TOKENS
    map_over_items: true (default) — if true, run once per decision;
                    if false, run once on the joined text
    cache_one_liners: false (default) — map mode only: read/write the shared
                    per-decision one-liner cache (``DecisionOneLiner``).
                    Requires ``ExtractStep`` provenance metadata.
    prompt_kind: "batch_one_liner" (default with cache) — lineage slug stored
                    on the ``OneLinerConfig`` row
"""

from decimal import Decimal

from core.ai_services.factory import get_provider
from core.ai_services.summary_prompts import BATCH_ONE_LINER_PROMPT_KIND
from core.models.pipeline import PipelineStepRun, RunStatus
from core.services.cost_ledger_service import CostLedgerService
from core.services.pipeline_engine import PipelineContext
from django.utils import timezone
from loguru import logger

# Code-level default for max_tokens.  Only persist an override in step config
# when you need a non-default budget — scalar defaults stay in code so tuning
# them is a code change, not a data migration.
DEFAULT_MAX_TOKENS = 3000

# Hard ceiling applied to *user-supplied* budgets (per-run override or the
# per-user preference).  Reasoning models bill "thinking" tokens at completion
# rates, so a typo like 500000 would be expensive.  Operator-set step config is
# trusted and left unclamped.
MAX_USER_MAX_TOKENS = 16000

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
        model_name = self._resolve_model(context, config.get("model", ""))
        # Surface the resolved model so callers (e.g. tasks) can record it
        context.metadata["model_used"] = model_name
        prompt_template = config.get("prompt_template", "Summarize: {{ text }}")
        system_prompt = config.get("system_prompt", "")
        temperature = config.get("temperature", 0.3)
        max_tokens = self._resolve_max_tokens(context, config)
        map_over_items = config.get("map_over_items", True)

        # Resolve API key from user's AI settings
        api_key = self._resolve_api_key(context.user)

        provider = get_provider(provider_name, model_name, api_key=api_key)

        total_input = 0
        total_output = 0
        total_cost = Decimal("0")
        rendered_prompts: list[str] = []  # collect for input_preview

        # One-liner cache setup — map mode only; single mode ignores the flag.
        cache_mode = bool(config.get("cache_one_liners")) and map_over_items
        ol_config = None
        ol_stats = None
        item_extractions = {}
        decisions_by_item = {}
        if cache_mode and context.per_item_outputs:
            ol_config = self._one_liner_config(
                config, prompt_template, system_prompt,
                provider_name, model_name, temperature, max_tokens,
            )
            item_extractions = context.metadata.get("item_extractions") or {}
            decisions_by_item = {
                str(d.pk): d for d in context.decisions if not isinstance(d, dict)
            }
            ol_stats = context.metadata.setdefault(
                "one_liner_cache", {"hits": 0, "misses": 0}
            )
            # Explicit regeneration: bypass the hit lookup and always mint a
            # fresh attempt under the *current* circumstances.
            force_attempt = bool(context.metadata.get("one_liner_force"))
        else:
            force_attempt = False

        if map_over_items and context.per_item_outputs:
            # Map mode: one call per item
            results = {}
            for item_id, text in context.per_item_outputs.items():
                decision = decisions_by_item.get(item_id) if ol_config else None
                extraction_id = item_extractions.get(item_id) if ol_config else None

                # Cache hit: reuse the stored one-liner at zero cost.
                if ol_config is not None and not force_attempt:
                    cached = self._one_liner_cache_get(
                        decision, ol_config, extraction_id
                    )
                    if cached is not None:
                        results[item_id] = cached.one_liner
                        ol_stats["hits"] += 1
                        continue

                rendered_prompt = self._render_prompt(
                    prompt_template, text, context, step
                )
                rendered_prompts.append(rendered_prompt)

                # Claim/adopt the attempt row BEFORE invoking so failures are
                # recorded on it (and concurrent workers never share one).
                # Dict/non-numeric item ids are not cacheable — they bypass
                # the cache (and its counters) exactly as today.
                cacheable = ol_config is not None and decision is not None
                row = (
                    self._one_liner_claim(
                        item_id, decision, ol_config, extraction_id, context
                    )
                    if cacheable
                    else None
                )
                if cacheable:
                    ol_stats["misses"] += 1

                result = provider.invoke(
                    text=rendered_prompt,
                    prompt=system_prompt,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                self._log_interaction(result, context, run, step_run, item_id=item_id)

                # Fail loudly on any failure OR a "success" with empty text —
                # an empty summary silently poisons the downstream merge step.
                if not result.get("success") or not (result.get("text") or "").strip():
                    error = result.get("error") or "empty response text"
                    if row is not None:
                        self._one_liner_mark_failed(row, error)
                    logger.error(f"AICallStep failed for item {item_id}: {error}")
                    raise RuntimeError(f"AI call failed for item {item_id}: {error}")

                results[item_id] = result.get("text", "")
                if row is not None:
                    self._one_liner_store(row, result, run)
                total_input += result["input_tokens"]
                total_output += result["output_tokens"]
                total_cost += result.get("actual_cost_usd", Decimal("0"))

            context.per_item_outputs = results
            context.steps_output[step.order] = "\n---\n".join(results.values())
        else:
            # Single mode: one call on joined text
            text = context.steps_output.get(step.order - 1, "") or "\n---\n".join(
                context.per_item_outputs.values()
            )
            rendered_prompt = self._render_prompt(prompt_template, text, context, step)
            rendered_prompts.append(rendered_prompt)
            result = provider.invoke(
                text=rendered_prompt,
                prompt=system_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            self._log_interaction(result, context, run, step_run)

            # Fail loudly on any failure OR a "success" with empty text.
            if not result.get("success") or not (result.get("text") or "").strip():
                error = result.get("error") or "empty response text"
                raise RuntimeError(f"AI call failed: {error}")

            context.steps_output[step.order] = result.get("text", "")
            total_input = result["input_tokens"]
            total_output = result["output_tokens"]
            total_cost = result.get("actual_cost_usd", Decimal("0"))

        step_run.input_tokens = total_input
        step_run.output_tokens = total_output
        step_run.cost_usd = total_cost
        step_run.input_preview = (
            "\n\n---\n\n".join(rendered_prompts) if rendered_prompts else ""
        )[:5000]
        step_run.output_text = (context.steps_output.get(step.order) or "")[:5000]
        step_run.save()

        logger.info(
            f"AICallStep: provider={provider_name} model={model_name} "
            f"in={total_input} out={total_output} cost=${total_cost:.6f}"
        )

    # ------------------------------------------------------------------
    # One-liner cache helpers (map mode + ``cache_one_liners`` flag only)
    # ------------------------------------------------------------------
    def _one_liner_config(
        self, config, prompt_template, system_prompt,
        provider_name, model_name, temperature, max_tokens,
    ):
        """Resolve (and get-or-create) the ``OneLinerConfig`` row for this
        step's *resolved* generation circumstances."""
        from core.models.one_liner_config import OneLinerConfig

        return OneLinerConfig.get_or_create_for(
            prompt_kind=config.get("prompt_kind") or BATCH_ONE_LINER_PROMPT_KIND,
            system_prompt=system_prompt,
            prompt_template=prompt_template,
            provider=provider_name,
            model=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    def _one_liner_cache_get(self, decision, ol_config, extraction_id):
        """Return the max-attempt COMPLETED row of this lineage, or ``None``."""
        if decision is None:
            return None
        from core.models.decision_one_liner import DecisionOneLiner

        return DecisionOneLiner.latest_completed(
            decision=decision, config=ol_config, extraction_id=extraction_id
        )

    def _one_liner_claim(self, item_id, decision, ol_config, extraction_id, context):
        """Adopt → claim → mint an attempt row for a cache miss.

        - Adoption (``context.metadata["adopt_one_liner_rows"]``): internal
          Celery retries overwrite the same row in place — retry noise must
          not mint attempts.
        - Claim: atomically flip a leftover PENDING row of this lineage to
          RUNNING (e.g. created by the explicit one-liner endpoint).
        - Mint: our own new attempt — a worker that loses the claim never
          blocks; at worst one duplicate provider call.
        Returns ``None`` when the item cannot be cached (dict/non-numeric
        item ids bypass the cache exactly as today)."""
        if decision is None:
            return None
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )

        adopted_id = (context.metadata.get("adopt_one_liner_rows") or {}).get(
            item_id
        )
        if adopted_id:
            row = DecisionOneLiner.objects.filter(
                pk=adopted_id, decision=decision, config=ol_config
            ).first()
            if row is not None and row.status in (
                OneLinerStatus.PENDING,
                OneLinerStatus.RUNNING,
            ):
                row.status = OneLinerStatus.RUNNING
                row.save(update_fields=["status", "updated_at"])
                return row

        row = DecisionOneLiner.claim_pending(
            decision=decision, config=ol_config, extraction_id=extraction_id
        )
        if row is not None:
            return row

        return DecisionOneLiner.new_attempt(
            decision=decision,
            config=ol_config,
            extraction_id=extraction_id,
            status=OneLinerStatus.RUNNING,
        )

    def _one_liner_store(self, row, result, run):
        """Persist a successful generation on the attempt row."""
        from core.models.decision_one_liner import OneLinerStatus

        row.one_liner = result.get("text", "")
        row.status = OneLinerStatus.COMPLETED
        row.input_tokens = result.get("input_tokens")
        row.output_tokens = result.get("output_tokens")
        row.cost_usd = result.get("actual_cost_usd")
        row.latency_ms = result.get("latency_ms")
        row.billed_to = run.billed_to
        row.pipeline_run = run
        row.completed_at = timezone.now()
        row.save()

    def _one_liner_mark_failed(self, row, error):
        """Record the failure on the attempt row, then let the step fail."""
        from core.models.decision_one_liner import OneLinerStatus

        row.status = OneLinerStatus.FAILED
        row.error_message = (error or "")[:500]
        row.save(update_fields=["status", "error_message", "updated_at"])

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

    def _resolve_model(self, context, pipeline_default: str) -> str:
        """
        Resolve which model to use.

        Precedence:
            0. ``context.metadata["model_override"]`` — explicit per-run override
               (e.g. user picked a specific model for this summary)
            1. User's ``UserAIModelPreference.preferred_model`` (independent of key)
            2. ``PipelineStep.config.model`` (pipeline default)
            3. ``settings.AI_DEFAULT_MODEL`` (system-wide fallback)
        """
        # 0. Explicit per-run override from context metadata
        override = context.metadata.get("model_override")
        if override:
            return override

        try:
            from core.models.user_ai_model_preference import UserAIModelPreference

            preferred = UserAIModelPreference.get_preferred_model(context.user)
            if preferred:
                return preferred
        except Exception:
            pass

        if pipeline_default:
            return pipeline_default

        # Ultimate fallback: system-wide default
        from django.conf import settings

        return getattr(settings, "AI_DEFAULT_MODEL", "deepseek/deepseek-v4-flash")

    def _resolve_max_tokens(self, context, config: dict) -> int:
        """
        Resolve the output-token budget.

        Precedence (mirrors ``_resolve_model``):
            0. ``context.metadata["max_tokens_override"]`` — explicit per-run
               override (e.g. caller knows this batch needs a longer budget)
            1. per-user ``UserAIModelPreference.max_tokens`` — user-set budget
            2. per-step ``config["max_tokens"]`` — persisted pipeline override
            3. ``DEFAULT_MAX_TOKENS`` — code-level default

        User-supplied values (override and preference) are clamped to
        ``MAX_USER_MAX_TOKENS``; operator-set step config is trusted.
        """
        # 0. Explicit per-run override
        override = context.metadata.get("max_tokens_override")
        if override:
            return min(int(override), MAX_USER_MAX_TOKENS)

        # 1. Per-user preference (if set)
        user_tokens = self._resolve_user_max_tokens(context.user)
        if user_tokens:
            return min(int(user_tokens), MAX_USER_MAX_TOKENS)

        # 2. Per-step persisted override, else code default
        return config.get("max_tokens") or DEFAULT_MAX_TOKENS

    def _resolve_user_max_tokens(self, user) -> int | None:
        """Return the user's preferred ``max_tokens``, or ``None`` if unset."""
        if user is None:
            return None
        try:
            from core.models.user_ai_model_preference import UserAIModelPreference

            return UserAIModelPreference.get_preferred_max_tokens(user)
        except Exception:
            return None

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
