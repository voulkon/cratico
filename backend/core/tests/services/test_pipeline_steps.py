"""
Tests for pipeline step executors — ExtractStep, PreprocessStep,
AICallStep, and AggregateStep.

All AI-provider calls are mocked to avoid real API invocations.
"""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from core.models.pipeline import (
    PipelineRun,
    PipelineStepRun,
    RunStatus,
    StepType,
)
from core.services.pipeline_engine import PipelineContext

from .conftest import (
    PipelineDefinitionFactory,
    PipelineStepFactory,
    PipelineRunFactory,
)

pytestmark = pytest.mark.django_db


# ============================================================================
# Shared helpers
# ============================================================================


def _make_context(decisions=None, per_item_outputs=None, steps_output=None):
    """Build a ``PipelineContext`` for step tests."""
    return PipelineContext(
        decisions=decisions or [],
        per_item_outputs=per_item_outputs or {},
        steps_output=steps_output or {},
    )


def _make_run(pipeline_def):
    """Create a parent ``PipelineRun``."""
    return PipelineRunFactory(pipeline=pipeline_def, status=RunStatus.RUNNING)


def _make_step_run(run, step):
    """Create a ``PipelineStepRun``."""
    return PipelineStepRun.objects.create(
        run=run, step=step, order=step.order, status=RunStatus.RUNNING,
    )


# ============================================================================
# ExtractStep
# ============================================================================


class TestExtractStep:
    """Tests for ``ExtractStep.execute``."""

    def test_extracts_from_dict_decisions(self):
        """Dict decisions with ``raw_text`` populate ``per_item_outputs``."""
        from core.services.pipeline_steps.extract import ExtractStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[
            {"id": "ADA1", "raw_text": "Text one."},
            {"id": "ADA2", "raw_text": "Text two."},
        ])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.per_item_outputs == {
            "ADA1": "Text one.",
            "ADA2": "Text two.",
        }
        assert step_run.output_text is not None

    def test_extracts_from_dict_with_text_fallback(self):
        """If ``raw_text`` is missing, fall back to ``text`` key."""
        from core.services.pipeline_steps.extract import ExtractStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[
            {"id": "ADA1", "text": "Only text key."},
        ])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.per_item_outputs["ADA1"] == "Only text key."

    def test_max_chars_truncation(self):
        """Text is truncated when ``config.max_chars`` is set."""
        from core.services.pipeline_steps.extract import ExtractStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract", config={"max_chars": 5},
        )
        context = _make_context(decisions=[
            {"id": "ADA1", "raw_text": "Longer than 5 chars."},
        ])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.per_item_outputs["ADA1"] == "Longe"

    @pytest.mark.django_db
    def test_extracts_from_decision_model(self, decision_type):
        """Decision model with ``DocumentExtraction`` uses cached text."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.services.pipeline_steps.extract import ExtractStep

        decision = DecisionFactory(
            ada="ADA_MODEL", decision_type=decision_type,
        )
        DocumentExtractionFactory(
            decision=decision, raw_text="Extracted PDF text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[decision])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.per_item_outputs[str(decision.id)] == "Extracted PDF text."

    @pytest.mark.django_db
    def test_records_extraction_provenance(self, decision_type):
        """Model decisions record the extraction id used per item."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.services.pipeline_steps.extract import ExtractStep

        decision = DecisionFactory(ada="ADA_PROV", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Provenance text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[decision])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.metadata["item_extractions"] == {
            str(decision.id): extraction.id
        }

    @pytest.mark.django_db
    def test_provenance_skips_dict_decisions(self, decision_type):
        """Dict decisions are skipped in the provenance map."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.services.pipeline_steps.extract import ExtractStep

        decision = DecisionFactory(ada="ADA_MIX", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Model text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[
            decision,
            {"id": "ADA_DICT", "raw_text": "Dict text."},
        ])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        ExtractStep().execute(step, step_run, context, run)

        assert context.metadata["item_extractions"] == {
            str(decision.id): extraction.id
        }
        assert context.per_item_outputs["ADA_DICT"] == "Dict text."

    @pytest.mark.django_db
    def test_on_demand_provenance(self, decision_type):
        """On-demand extraction records the fresh extraction row id."""
        from conftest import DecisionFactory
        from core.services.pipeline_steps.extract import ExtractStep

        decision = DecisionFactory(ada="ADA_ONDEMAND", decision_type=decision_type)

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[decision])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        # Simulate the on-demand flow resolving a real extraction row
        from conftest import DocumentExtractionFactory

        def _fake_on_demand(d):
            row = DocumentExtractionFactory(decision=d, raw_text="Fresh text.")
            return "Fresh text.", row

        with patch.object(ExtractStep, "_extract_on_demand", side_effect=_fake_on_demand):
            ExtractStep().execute(step, step_run, context, run)

        assert context.per_item_outputs[str(decision.id)] == "Fresh text."
        row_id = context.metadata["item_extractions"][str(decision.id)]
        assert row_id is not None

    @pytest.mark.django_db
    def test_falls_back_to_subject(self, decision_type):
        """Decision with no extractable text falls back to a marked ``subject``.

        On-demand extraction is mocked to return nothing so the test is fast
        and offline — the real path would attempt a network download.
        """
        from conftest import DecisionFactory
        from core.services.pipeline_steps.extract import ExtractStep

        decision = DecisionFactory(
            ada="ADA_NOCACHE", decision_type=decision_type,
            subject="Subject only text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=0, step_type=StepType.EXTRACT,
            name="Extract",
        )
        context = _make_context(decisions=[decision])
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch.object(ExtractStep, "_extract_on_demand", return_value=("", None)):
            ExtractStep().execute(step, step_run, context, run)

        assert (
            context.per_item_outputs[str(decision.id)]
            == "[EXTRACTION_UNAVAILABLE] Subject only text."
        )
        # Subject fallback is marked with provenance None
        assert context.metadata["item_extractions"][str(decision.id)] is None


# ============================================================================
# PreprocessStep
# ============================================================================


class TestPreprocessStep:
    """Tests for ``PreprocessStep.execute``."""

    def test_applies_preprocessor_to_each_item(self):
        """Each item in ``per_item_outputs`` is transformed."""
        from core.services.pipeline_steps.preprocess import PreprocessStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=1, step_type=StepType.PREPROCESS,
            name="Preprocess", config={"preprocessor": "noop"},
        )
        context = _make_context(
            per_item_outputs={"A": "hello", "B": "world"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        PreprocessStep().execute(step, step_run, context, run)

        # noop should return unchanged
        assert context.per_item_outputs["A"] == "hello"
        assert context.per_item_outputs["B"] == "world"

    def test_defaults_to_noop(self):
        """No config preprocessor → uses 'noop'."""
        from core.services.pipeline_steps.preprocess import PreprocessStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=1, step_type=StepType.PREPROCESS,
            name="Preprocess",
        )
        context = _make_context(
            per_item_outputs={"A": "unchanged"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        PreprocessStep().execute(step, step_run, context, run)
        assert context.per_item_outputs["A"] == "unchanged"

    def test_writes_preview_to_step_run(self):
        """Output preview is written to the step run."""
        from core.services.pipeline_steps.preprocess import PreprocessStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=1, step_type=StepType.PREPROCESS,
            name="Preprocess",
        )
        context = _make_context(
            per_item_outputs={"A": "some text"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        PreprocessStep().execute(step, step_run, context, run)

        step_run.refresh_from_db()
        assert step_run.output_text is not None
        assert "some text" in step_run.output_text

    def test_unknown_preprocessor_raises(self):
        """An unregistered preprocessor raises ``KeyError``."""
        from core.services.pipeline_steps.preprocess import PreprocessStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=1, step_type=StepType.PREPROCESS,
            name="Preprocess", config={"preprocessor": "does_not_exist"},
        )
        context = _make_context(per_item_outputs={"A": "text"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with pytest.raises(KeyError, match="Unknown preprocessor"):
            PreprocessStep().execute(step, step_run, context, run)


# ============================================================================
# AICallStep
# ============================================================================


class TestAICallStep:
    """Tests for ``AICallStep.execute`` with a mocked provider."""

    def _success_result(self, text="AI summary"):
        """Return a standardised success response dict."""
        return {
            "success": True,
            "text": text,
            "input_tokens": 50,
            "output_tokens": 20,
            "actual_cost_usd": Decimal("0.0001"),
            "latency_ms": 150,
            "provider": "OPENROUTER",
            "model": "test/model",
        }

    def _fail_result(self, error="API error"):
        return {
            "success": False,
            "error": error,
            "input_tokens": 0,
            "output_tokens": 0,
            "actual_cost_usd": Decimal("0"),
        }

    def test_map_mode_one_call_per_item(self):
        """Each item triggers a separate AI call."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "prompt_template": "Summarize: {{ text }}",
                "map_over_items": True,
            },
        )
        context = _make_context(per_item_outputs={
            "A": "Text A", "B": "Text B",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.side_effect = [
                self._success_result("Summary A"),
                self._success_result("Summary B"),
            ]
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_count == 2
        assert context.per_item_outputs["A"] == "Summary A"
        assert context.per_item_outputs["B"] == "Summary B"

    def test_max_tokens_falls_back_to_code_default(self):
        """Omitting max_tokens in config makes the provider receive DEFAULT_MAX_TOKENS."""
        from core.services.pipeline_steps.ai_call import AICallStep, DEFAULT_MAX_TOKENS

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True},  # no max_tokens key
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("S")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_args.kwargs["max_tokens"] == DEFAULT_MAX_TOKENS

    def test_max_tokens_config_override_wins(self):
        """An explicit max_tokens in config overrides the code default."""
        from core.services.pipeline_steps.ai_call import AICallStep, DEFAULT_MAX_TOKENS

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True, "max_tokens": 123},
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("S")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        actual = mock_provider.invoke.call_args.kwargs["max_tokens"]
        assert actual == 123
        assert actual != DEFAULT_MAX_TOKENS

    def test_max_tokens_per_run_override_wins(self):
        """context.metadata['max_tokens_override'] beats both config and code default."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True, "max_tokens": 123},
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        context.metadata["max_tokens_override"] = 4567
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("S")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_args.kwargs["max_tokens"] == 4567

    def test_max_tokens_user_preference_wins(self):
        """A per-user max_tokens preference beats both step config and code default."""
        from conftest import UserFactory
        from core.models.user_ai_model_preference import UserAIModelPreference
        from core.services.pipeline_steps.ai_call import AICallStep

        user = UserFactory()
        UserAIModelPreference.objects.create(user=user, max_tokens=5000)

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True, "max_tokens": 123},
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        context.user = user
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("S")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_args.kwargs["max_tokens"] == 5000

    def test_max_tokens_user_preference_clamped(self):
        """An absurd per-user max_tokens is clamped to MAX_USER_MAX_TOKENS."""
        from conftest import UserFactory
        from core.models.user_ai_model_preference import UserAIModelPreference
        from core.services.pipeline_steps.ai_call import (
            AICallStep,
            MAX_USER_MAX_TOKENS,
        )

        user = UserFactory()
        UserAIModelPreference.objects.create(user=user, max_tokens=999999)

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True},
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        context.user = user
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("S")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_args.kwargs["max_tokens"] == MAX_USER_MAX_TOKENS

    def test_map_mode_accumulates_tokens_and_cost(self):
        """Multiple calls sum tokens and cost on the step run."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "map_over_items": True,
            },
        )
        context = _make_context(per_item_outputs={"A": "X", "B": "Y"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.side_effect = [
                self._success_result("S1"),
                self._success_result("S2"),
            ]
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        step_run.refresh_from_db()
        assert step_run.input_tokens == 100  # 50 + 50
        assert step_run.output_tokens == 40  # 20 + 20
        assert step_run.cost_usd == Decimal("0.0002")  # 0.0001 + 0.0001

    def test_map_mode_failed_item_raises(self):
        """A failed item fails the whole step loudly instead of leaving a
        placeholder that would poison the downstream merge."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True},
        )
        context = _make_context(per_item_outputs={
            "A": "OK", "B": "Will fail",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.side_effect = [
                self._success_result("Summary A"),
                self._fail_result("timeout"),
            ]
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="item B"):
                AICallStep().execute(step, step_run, context, run)

    def test_map_mode_empty_text_raises(self):
        """A 'success' with empty text is treated as a failure."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": True},
        )
        context = _make_context(per_item_outputs={"A": "Text A"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            # success=True but empty text — the exact failure mode we hit
            mock_provider.invoke.return_value = {
                **self._success_result(""),
                "output_tokens": 500,
            }
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="empty response text"):
                AICallStep().execute(step, step_run, context, run)

    def test_single_mode_one_call(self):
        """``map_over_items=False`` makes a single AI call."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize all",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "map_over_items": False,
            },
        )
        context = _make_context(
            per_item_outputs={"A": "One", "B": "Two"},
            steps_output={1: "Joined text"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("Combined")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_count == 1
        assert context.steps_output[2] == "Combined"

    def test_single_mode_failure_raises(self):
        """A failed single-mode AI call raises ``RuntimeError``."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": False},
        )
        context = _make_context(
            per_item_outputs={"A": "One"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._fail_result("bad")
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="AI call failed"):
                AICallStep().execute(step, step_run, context, run)

    def test_single_mode_empty_text_raises(self):
        """A single-mode 'success' with empty text fails loudly."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={"map_over_items": False},
        )
        context = _make_context(
            per_item_outputs={"A": "One"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("")
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="empty response text"):
                AICallStep().execute(step, step_run, context, run)

    def test_jinja2_rendering(self):
        """Jinja2 templates receive all context variables."""
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "prompt_template": "Item count: {{ decisions | length }}. Text: {{ text[:10] }}",
                "map_over_items": False,
            },
        )
        context = _make_context(
            decisions=[{"id": "A"}, {"id": "B"}],
            steps_output={1: "The full text goes here"},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success_result("OK")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        # Check that the rendered prompt was passed to the provider
        call_args = mock_provider.invoke.call_args
        rendered_prompt = call_args.kwargs["text"]
        assert "Item count: 2" in rendered_prompt


# ============================================================================
# AICallStep — one-liner cache (``cache_one_liners`` map mode)
# ============================================================================


class TestAICallStepOneLinerCache:
    """Cache-aware map mode: hits cost nothing, misses fill the cache."""

    def _cache_step(self, pipeline_def):
        from .conftest import PipelineStepFactory

        return PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize (cached)",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "system_prompt": "Be brief.",
                "prompt_template": "Summarize: {{ text }}",
                "map_over_items": True,
                "cache_one_liners": True,
                "prompt_kind": "batch_one_liner",
            },
        )

    def _cache_ol_config(self):
        """The ``OneLinerConfig`` row the cached step resolves to (matching
        system_prompt + the code-level ``max_tokens`` default)."""
        from core.models.one_liner_config import OneLinerConfig
        from core.services.pipeline_steps.ai_call import DEFAULT_MAX_TOKENS

        return OneLinerConfig.get_or_create_for(
            prompt_kind="batch_one_liner",
            system_prompt="Be brief.",
            prompt_template="Summarize: {{ text }}",
            provider="OPENROUTER",
            model="test/model",
            temperature=0.3,
            max_tokens=DEFAULT_MAX_TOKENS,
        )

    def _cache_context(self, decision, extraction, extra=None):
        context = _make_context(decisions=[decision],
                                per_item_outputs={str(decision.pk): "Full text."})
        context.metadata["item_extractions"] = {str(decision.pk): extraction.id}
        context.metadata.update(extra or {})
        return context

    def _success(self, text):
        return {
            "success": True,
            "text": text,
            "input_tokens": 50,
            "output_tokens": 20,
            "actual_cost_usd": Decimal("0.0001"),
            "latency_ms": 150,
            "provider": "OPENROUTER",
            "model": "test/model",
        }

    @pytest.mark.django_db
    def test_hit_reuses_stored_one_liner(self, decision_type):
        """A COMPLETED lineage row short-circuits the provider — zero cost."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_HIT", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )
        ol_config = self._cache_ol_config()
        DecisionOneLiner.objects.create(
            decision=decision,
            extraction=extraction,
            config=ol_config,
            attempt=1,
            status=OneLinerStatus.COMPLETED,
            one_liner="Cached one-liner.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        context = self._cache_context(decision, extraction)
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        mock_provider.invoke.assert_not_called()
        assert context.per_item_outputs[str(decision.pk)] == "Cached one-liner."
        assert context.metadata["one_liner_cache"] == {"hits": 1, "misses": 0}
        step_run.refresh_from_db()
        assert step_run.input_tokens == 0
        assert step_run.cost_usd == Decimal("0")

    @pytest.mark.django_db
    def test_miss_generates_and_stores_attempt(self, decision_type):
        """A cache miss invokes the provider once and persists the attempt."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_MISS", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        context = self._cache_context(decision, extraction)
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success("Fresh one-liner.")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        mock_provider.invoke.assert_called_once()
        row = DecisionOneLiner.objects.get(decision=decision)
        assert row.status == OneLinerStatus.COMPLETED
        assert row.one_liner == "Fresh one-liner."
        assert row.attempt == 1
        assert row.input_tokens == 50
        assert row.output_tokens == 20
        assert row.cost_usd == Decimal("0.0001")
        assert row.pipeline_run_id == run.id
        assert row.completed_at is not None
        assert context.metadata["one_liner_cache"] == {"hits": 0, "misses": 1}

    @pytest.mark.django_db
    def test_failure_marks_row_failed_and_raises(self, decision_type):
        """A failed provider call marks the attempt FAILED, then raises."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_FAIL", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        context = self._cache_context(decision, extraction)
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = {
                "success": False,
                "error": "API quota exceeded",
                "input_tokens": 0,
                "output_tokens": 0,
                "actual_cost_usd": Decimal("0"),
            }
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="item "):
                AICallStep().execute(step, step_run, context, run)

        row = DecisionOneLiner.objects.get(decision=decision)
        assert row.status == OneLinerStatus.FAILED
        assert "API quota exceeded" in row.error_message

    @pytest.mark.django_db
    def test_force_bypasses_hit_and_mints_new_attempt(self, decision_type):
        """``one_liner_force`` metadata ignores the stored hit and always
        generates a fresh attempt under the current circumstances."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_FORCE", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )
        ol_config = self._cache_ol_config()
        DecisionOneLiner.objects.create(
            decision=decision,
            extraction=extraction,
            config=ol_config,
            attempt=1,
            status=OneLinerStatus.COMPLETED,
            one_liner="Old one-liner.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        context = self._cache_context(
            decision, extraction, extra={"one_liner_force": True}
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success("New one-liner.")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        mock_provider.invoke.assert_called_once()
        rows = list(DecisionOneLiner.objects.filter(decision=decision))
        assert len(rows) == 2
        new_row = max(rows, key=lambda r: r.attempt)
        assert new_row.attempt == 2
        assert new_row.one_liner == "New one-liner."
        assert new_row.status == OneLinerStatus.COMPLETED
        # The old attempt is kept as history
        assert context.per_item_outputs[str(decision.pk)] == "New one-liner."

    @pytest.mark.django_db
    def test_dict_decisions_bypass_cache(self, decision_type):
        """Non-numeric/dict item ids are never cached (counters untouched)."""
        from core.models.decision_one_liner import DecisionOneLiner
        from core.services.pipeline_steps.ai_call import AICallStep

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        context = _make_context(
            decisions=[{"id": "ADA_DICT", "raw_text": "Dict text."}],
            per_item_outputs={"ADA_DICT": "Dict text."},
        )
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success("Dict summary.")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        mock_provider.invoke.assert_called_once()
        assert not DecisionOneLiner.objects.exists()
        assert context.metadata["one_liner_cache"] == {"hits": 0, "misses": 0}

    @pytest.mark.django_db
    def test_retry_adopts_minted_row_in_place(self, decision_type):
        """Adoption metadata maps the item to the row minted by a previous
        (failed) try — internal retries overwrite it, not mint attempts."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_ADOPT", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )
        ol_config = self._cache_ol_config()

        pipeline_def = PipelineDefinitionFactory()
        step = self._cache_step(pipeline_def)
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        # Row minted by the previous try of the same task (left RUNNING)
        leftover = DecisionOneLiner.objects.create(
            decision=decision,
            extraction=extraction,
            config=ol_config,
            attempt=1,
            status=OneLinerStatus.RUNNING,
        )

        context = self._cache_context(
            decision, extraction,
            extra={"adopt_one_liner_rows": {str(decision.pk): leftover.id}},
        )

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success("Retry one-liner.")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        rows = list(DecisionOneLiner.objects.filter(decision=decision))
        assert len(rows) == 1  # no new attempt minted
        rows[0].refresh_from_db()
        assert rows[0].one_liner == "Retry one-liner."
        assert rows[0].status == OneLinerStatus.COMPLETED

    @pytest.mark.django_db
    def test_single_mode_ignores_cache_flag(self, decision_type):
        """The flag is map-mode only — single-mode steps stay uncached."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decision_one_liner import DecisionOneLiner
        from core.services.pipeline_steps.ai_call import AICallStep

        decision = DecisionFactory(ada="ADA_SINGLE", decision_type=decision_type)
        extraction = DocumentExtractionFactory(
            decision=decision, raw_text="Full document text.",
        )

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=2, step_type=StepType.AI_CALL,
            name="Summarize all",
            config={
                "provider": "OPENROUTER",
                "model": "test/model",
                "map_over_items": False,
                "cache_one_liners": True,
            },
        )
        context = _make_context(
            decisions=[decision],
            per_item_outputs={str(decision.pk): "Full text."},
            steps_output={1: "Joined text"},
        )
        context.metadata["item_extractions"] = {str(decision.pk): extraction.id}
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.ai_call.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = self._success("Single summary.")
            mock_get_provider.return_value = mock_provider

            AICallStep().execute(step, step_run, context, run)

        assert context.steps_output[2] == "Single summary."
        assert not DecisionOneLiner.objects.exists()
        assert "one_liner_cache" not in context.metadata


# ============================================================================
# AggregateStep
# ============================================================================


class TestAggregateStep:
    """Tests for ``AggregateStep.execute``."""

    def test_concat_joins_with_separator(self):
        """Concat strategy joins per-item outputs with ``\\n---\\n``."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge", config={"strategy": "concat"},
        )
        context = _make_context(per_item_outputs={
            "A": "First", "B": "Second",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        AggregateStep().execute(step, step_run, context, run)

        assert context.steps_output[3] == "First\n---\nSecond"

    def test_concat_is_default_strategy(self):
        """When no strategy is specified, concat is used."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge", config={},
        )
        context = _make_context(per_item_outputs={
            "A": "X", "B": "Y",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        AggregateStep().execute(step, step_run, context, run)

        assert context.steps_output[3] == "X\n---\nY"

    def test_summarize_merge_calls_ai(self):
        """Summarize-each-then-merge strategy makes a final AI call."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge",
            config={
                "strategy": "summarize_each_then_merge",
                "provider": "OPENROUTER",
                "model": "test/model",
                "merge_prompt_template": "Merge: {{ text }}",
            },
        )
        context = _make_context(per_item_outputs={
            "A": "Summary A", "B": "Summary B",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.aggregate.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = {
                "success": True,
                "text": "Merged summary",
                "input_tokens": 30,
                "output_tokens": 15,
                "actual_cost_usd": Decimal("0.00005"),
                "latency_ms": 100,
                "provider": "OPENROUTER",
                "model": "test/model",
            }
            mock_get_provider.return_value = mock_provider

            AggregateStep().execute(step, step_run, context, run)

        mock_provider.invoke.assert_called_once()
        assert context.steps_output[3] == "Merged summary"

    def test_summarize_merge_max_tokens_falls_back_to_code_default(self):
        """Merge step with no max_tokens in config passes DEFAULT_MAX_TOKENS to the provider."""
        from core.services.pipeline_steps.aggregate import AggregateStep
        from core.services.pipeline_steps.ai_call import DEFAULT_MAX_TOKENS

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge",
            config={
                "strategy": "summarize_each_then_merge",
                # max_tokens intentionally omitted
            },
        )
        context = _make_context(per_item_outputs={"A": "S1", "B": "S2"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.aggregate.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = {
                "success": True,
                "text": "Merged",
                "input_tokens": 30,
                "output_tokens": 15,
                "actual_cost_usd": Decimal("0.00005"),
                "latency_ms": 100,
                "provider": "OPENROUTER",
                "model": "test/model",
            }
            mock_get_provider.return_value = mock_provider

            AggregateStep().execute(step, step_run, context, run)

        assert mock_provider.invoke.call_args.kwargs["max_tokens"] == DEFAULT_MAX_TOKENS

    def test_summarize_merge_ai_failure_raises(self):
        """When the merge AI call fails, the step fails loudly."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge",
            config={
                "strategy": "summarize_each_then_merge",
                "provider": "OPENROUTER",
                "model": "test/model",
            },
        )
        context = _make_context(per_item_outputs={
            "A": "S1", "B": "S2",
        })
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.aggregate.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = {
                "success": False,
                "error": "Service unavailable",
                "text": "",
                "input_tokens": 0,
                "output_tokens": 0,
                "actual_cost_usd": Decimal("0"),
                "provider": "OPENROUTER",
                "model": "test/model",
            }
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="Aggregate merge call failed"):
                AggregateStep().execute(step, step_run, context, run)

    def test_summarize_merge_empty_items_raises(self):
        """No per-item summaries → fail loudly instead of calling the model."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge",
            config={"strategy": "summarize_each_then_merge"},
        )
        context = _make_context(per_item_outputs={"A": ""})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with pytest.raises(RuntimeError, match="no per-item summaries"):
            AggregateStep().execute(step, step_run, context, run)

    def test_summarize_merge_empty_result_raises(self):
        """A merge 'success' with empty text fails loudly."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge",
            config={
                "strategy": "summarize_each_then_merge",
                "provider": "OPENROUTER",
                "model": "test/model",
            },
        )
        context = _make_context(per_item_outputs={"A": "S1"})
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with patch(
            "core.services.pipeline_steps.aggregate.get_provider"
        ) as mock_get_provider:
            mock_provider = MagicMock()
            mock_provider.invoke.return_value = {
                "success": True,
                "text": "",
                "input_tokens": 30,
                "output_tokens": 15,
                "actual_cost_usd": Decimal("0.00005"),
                "latency_ms": 100,
                "provider": "OPENROUTER",
                "model": "test/model",
            }
            mock_get_provider.return_value = mock_provider

            with pytest.raises(RuntimeError, match="empty response text"):
                AggregateStep().execute(step, step_run, context, run)

    def test_unknown_strategy_raises(self):
        """An unknown strategy raises ``ValueError``."""
        from core.services.pipeline_steps.aggregate import AggregateStep

        pipeline_def = PipelineDefinitionFactory()
        step = PipelineStepFactory(
            pipeline=pipeline_def, order=3, step_type=StepType.AGGREGATE,
            name="Merge", config={"strategy": "bogus"},
        )
        context = _make_context()
        run = _make_run(pipeline_def)
        step_run = _make_step_run(run, step)

        with pytest.raises(ValueError, match="Unknown aggregate strategy"):
            AggregateStep().execute(step, step_run, context, run)
