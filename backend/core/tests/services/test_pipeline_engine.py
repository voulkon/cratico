"""
Tests for ``PipelineEngine`` — data-driven DAG executor.

Covers:
- Successful pipeline runs (all steps succeed)
- Failed step marks the run as FAILED and skips remaining steps
- Cost / token roll-up from step runs
- ``_resolve_billed_to`` logic
- Empty / inactive step handling
- Unknown step type error
"""

from decimal import Decimal
from unittest.mock import PropertyMock, patch

import pytest
from core.models.pipeline import PipelineRun, PipelineStepRun, RunStatus, StepType
from core.services.pipeline_engine import PipelineContext, PipelineEngine

from .conftest import (
    PipelineDefinitionFactory,
    PipelineStepFactory,
)

pytestmark = pytest.mark.django_db


# ============================================================================
# Helpers
# ============================================================================


def _make_context(decisions=None, user=None):
    """Build a ``PipelineContext`` for tests."""
    return PipelineContext(
        decisions=decisions or [],
        batch=None,
        user=user,
    )


def _make_step(pipeline, order, step_type, name=None, config=None, is_active=True):
    """Shortcut to create a ``PipelineStep``."""
    return PipelineStepFactory(
        pipeline=pipeline,
        order=order,
        step_type=step_type,
        name=name or f"step-{order}",
        config=config or {},
        is_active=is_active,
    )


# ============================================================================
# Tests: successful runs
# ============================================================================


class TestSuccessfulRun:
    """Happy-path pipeline execution."""

    def test_empty_steps_completes_immediately(self, pipeline_definition, user):
        """Pipeline with no active steps → COMPLETED."""
        engine = PipelineEngine()
        context = _make_context(decisions=[{"id": "X"}], user=user)
        run = engine.run(pipeline_definition, context)

        assert run.status == RunStatus.COMPLETED
        assert run.total_input_tokens == 0
        assert run.total_output_tokens == 0
        assert run.total_cost_usd == 0

    def test_run_creates_pipeline_run_record(self, pipeline_definition, user):
        """A run creates a ``PipelineRun`` in the database."""
        step = _make_step(pipeline_definition, 0, StepType.EXTRACT)

        # Patch the executor so it runs without real extraction
        with patch.object(
            PipelineEngine, "_execute_step", return_value=None
        ):
            engine = PipelineEngine()
            context = _make_context(decisions=[{"id": "X"}], user=user)
            run = engine.run(pipeline_definition, context)

        assert PipelineRun.objects.filter(id=run.id).exists()
        assert run.status == RunStatus.COMPLETED
        assert run.trigger == "manual"
        assert run.started_at is not None
        assert run.completed_at is not None

    def test_trigger_and_ref_stored(self, pipeline_definition, user):
        """Custom trigger and trigger_ref are persisted."""
        with patch.object(PipelineEngine, "_execute_step", return_value=None):
            engine = PipelineEngine()
            context = _make_context(user=user)
            run = engine.run(
                pipeline_definition, context,
                trigger="batch_summary",
                trigger_ref="batch-42",
            )

        assert run.trigger == "batch_summary"
        assert run.trigger_ref == "batch-42"


# ============================================================================
# Tests: failures
# ============================================================================


class TestFailedRun:
    """Error handling in pipeline execution."""

    def test_failed_step_marks_run_failed(self, pipeline_definition, user):
        """When a step raises, the run status is FAILED."""
        _make_step(pipeline_definition, 0, StepType.EXTRACT)

        def _raise(*args, **kwargs):
            raise RuntimeError("Boom!")

        with patch.object(PipelineEngine, "_execute_step", side_effect=_raise):
            engine = PipelineEngine()
            context = _make_context(decisions=[{"id": "X"}], user=user)
            run = engine.run(pipeline_definition, context)

        assert run.status == RunStatus.FAILED
        assert "Boom!" in (run.error_message or "")

    def test_remaining_steps_skipped_on_failure(self, pipeline_definition, user):
        """When step 0 fails, step 1 is never executed."""
        _make_step(pipeline_definition, 0, StepType.EXTRACT)
        _make_step(pipeline_definition, 1, StepType.PREPROCESS)

        executed = []

        def _record_execution(self, step, *args, **kwargs):
            executed.append(step.order)
            if step.order == 0:
                raise RuntimeError("fail at step 0")

        with patch.object(PipelineEngine, "_execute_step", _record_execution):
            engine = PipelineEngine()
            context = _make_context(decisions=[{"id": "X"}], user=user)
            engine.run(pipeline_definition, context)

        assert executed == [0]


# ============================================================================
# Tests: billing resolution
# ============================================================================


class TestBilledTo:
    """``_resolve_billed_to`` logic."""

    def test_no_user_raises(self):
        engine = PipelineEngine()
        with pytest.raises(ValueError, match="user is required"):
            engine._resolve_billed_to(None)

    def test_run_requires_user(self, pipeline_definition):
        """``run`` refuses to start without a user to attribute billing to."""
        engine = PipelineEngine()
        context = _make_context(decisions=[{"id": "X"}])

        with pytest.raises(ValueError, match="require a user"):
            engine.run(pipeline_definition, context)

        assert not PipelineRun.objects.exists()

    def test_user_with_settings(self, user):
        """User with own API key → 'USER' (billed_to is a computed property)."""
        from core.models.user_ai_settings import UserAISettings

        UserAISettings.objects.create(
            user=user,
            provider=UserAISettings.Provider.OPENROUTER,
            is_active=True,
        )
        engine = PipelineEngine()

        # ``billed_to`` is a computed property requiring an encrypted key.
        with patch.object(
            UserAISettings, "billed_to",
            new_callable=PropertyMock,
            return_value="USER",
        ):
            assert engine._resolve_billed_to(user) == "USER"

    @pytest.mark.django_db
    def test_user_without_settings_falls_back(self, user):
        """User without ai_settings → 'SYSTEM'."""
        engine = PipelineEngine()
        assert engine._resolve_billed_to(user) == "SYSTEM"


# ============================================================================
# Tests: roll-up
# ============================================================================


class TestRollUpTotals:
    """``_roll_up_totals`` aggregates step-run metrics."""

    def test_sums_tokens_and_cost(self, pipeline_definition, user):
        """Total input/output tokens and cost are summed from step runs."""
        with patch.object(PipelineEngine, "_execute_step", return_value=None):
            engine = PipelineEngine()
            context = _make_context(user=user)
            run = engine.run(pipeline_definition, context)

        # Create step runs manually to test roll-up
        PipelineStepRun.objects.create(
            run=run, step=None, order=0, status=RunStatus.COMPLETED,
            input_tokens=100, output_tokens=50, cost_usd=Decimal("0.001"),
        )
        PipelineStepRun.objects.create(
            run=run, step=None, order=1, status=RunStatus.COMPLETED,
            input_tokens=200, output_tokens=80, cost_usd=Decimal("0.002"),
        )

        engine._roll_up_totals(run)
        run.save()
        run.refresh_from_db()

        assert run.total_input_tokens == 300
        assert run.total_output_tokens == 130
        assert run.total_cost_usd == Decimal("0.003")


# ============================================================================
# Tests: step dispatch
# ============================================================================


class TestStepDispatch:
    """``_execute_step`` creates step runs and handles errors."""

    def test_unknown_step_type_raises(self, pipeline_definition):
        """A step with an unregistered type raises ``ValueError``."""
        step = _make_step(
            pipeline_definition, 0, "BOGUS_TYPE", name="bad step"
        )
        engine = PipelineEngine()
        context = _make_context()
        # Create a parent run first
        run = PipelineRun.objects.create(
            pipeline=pipeline_definition,
            status=RunStatus.RUNNING,
            trigger="test",
        )

        with pytest.raises(ValueError, match="No executor registered"):
            engine._execute_step(step, context, run)

    def test_inactive_steps_skipped(self, pipeline_definition, user):
        """Inactive steps are not dispatched."""
        _make_step(pipeline_definition, 0, StepType.EXTRACT, is_active=False)
        _make_step(pipeline_definition, 1, StepType.EXTRACT, is_active=True)

        engine = PipelineEngine()
        context = _make_context(decisions=[{"id": "X"}], user=user)

        with patch.object(PipelineEngine, "_execute_step") as mock_exec:
            engine.run(pipeline_definition, context)
            # Only the active step (order=1) should be dispatched
            called_orders = [
                c.args[0].order for c in mock_exec.call_args_list
            ]
            assert called_orders == [1]
