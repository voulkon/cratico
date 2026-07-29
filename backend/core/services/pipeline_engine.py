"""
Pipeline engine — data-driven DAG executor.

Runs a ``PipelineDefinition`` by iterating its ordered ``PipelineStep``s and
dispatching each to the appropriate step executor.  All outputs, costs, and
errors are recorded on ``PipelineRun`` / ``PipelineStepRun``.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from django.utils import timezone
from loguru import logger

from core.models.pipeline import PipelineDefinition, PipelineRun, PipelineStepRun, RunStatus


@dataclass
class PipelineContext:
    """Mutable context passed through pipeline steps."""

    decisions: List[Any]  # list of Decision instances or dicts
    batch: Optional[Any] = None
    user: Optional[Any] = None
    steps_output: Dict[int, str] = field(default_factory=dict)  # {step_order: output}
    per_item_outputs: Dict[str, str] = field(default_factory=dict)  # {item_id: output}
    metadata: Dict[str, Any] = field(default_factory=dict)


class PipelineEngine:
    """Executes a ``PipelineDefinition`` and records the run."""

    def run(
        self,
        pipeline_def: PipelineDefinition,
        context: PipelineContext,
        trigger: str = "manual",
        trigger_ref: str | None = None,
    ) -> PipelineRun:
        """
        Execute *pipeline_def* with *context*.

        Returns the completed ``PipelineRun``.
        """
        run = PipelineRun.objects.create(
            pipeline=pipeline_def,
            status=RunStatus.RUNNING,
            triggered_by_user=context.user,
            trigger=trigger,
            trigger_ref=trigger_ref,
            started_at=timezone.now(),
        )

        # Determine billing attribution from user's AI settings
        run.billed_to = self._resolve_billed_to(context.user)
        run.save(update_fields=["billed_to"])

        try:
            steps = list(
                pipeline_def.steps.filter(is_active=True).order_by("order")
            )
            for step in steps:
                self._execute_step(step, context, run)

            run.status = RunStatus.COMPLETED
        except Exception as exc:
            run.status = RunStatus.FAILED
            run.error_message = str(exc)
            logger.error(f"Pipeline run {run.id} failed: {exc}", exc_info=True)
        finally:
            run.completed_at = timezone.now()
            # Roll up totals from step runs
            self._roll_up_totals(run)
            run.save()

        return run

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _resolve_billed_to(self, user) -> str:
        """Return 'USER' or 'SYSTEM' based on user's AI settings."""
        if user is None:
            return "SYSTEM"
        try:
            from core.models.user_ai_settings import UserAISettings

            ai_settings = UserAISettings.get_default_for_user(user)
            return ai_settings.billed_to if ai_settings else "SYSTEM"
        except Exception:
            return "SYSTEM"

    def _execute_step(self, step, context: PipelineContext, run: PipelineRun):
        """Dispatch a single step to its executor."""
        from core.services.pipeline_steps import STEP_EXECUTORS

        executor_cls = STEP_EXECUTORS.get(step.step_type)
        if not executor_cls:
            raise ValueError(
                f"No executor registered for step type '{step.step_type}'"
            )

        step_run = PipelineStepRun.objects.create(
            run=run,
            step=step,
            order=step.order,
            status=RunStatus.RUNNING,
            started_at=timezone.now(),
        )

        start = time.monotonic()
        try:
            executor = executor_cls()
            executor.execute(step, step_run, context, run)
            step_run.status = RunStatus.COMPLETED
        except Exception as exc:
            step_run.status = RunStatus.FAILED
            step_run.error_message = str(exc)
            logger.error(
                f"Step {step.order} ({step.name}) failed: {exc}", exc_info=True
            )
            raise
        finally:
            step_run.latency_ms = int((time.monotonic() - start) * 1000)
            step_run.completed_at = timezone.now()
            step_run.save()

    def _roll_up_totals(self, run: PipelineRun):
        """Sum up tokens and cost from all step runs."""
        from decimal import Decimal

        total_in = 0
        total_out = 0
        total_cost = Decimal("0")
        for sr in run.step_runs.all():
            total_in += sr.input_tokens
            total_out += sr.output_tokens
            total_cost += sr.cost_usd
        run.total_input_tokens = total_in
        run.total_output_tokens = total_out
        run.total_cost_usd = total_cost
