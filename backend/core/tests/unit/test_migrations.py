"""
Tests for data migrations that strip persisted ``max_tokens`` overrides.

Migration functions are plain callables of ``(apps, schema_editor)``, so they
are exercised directly against the live ORM rather than via a full
``MigrationExecutor`` round-trip.  The fields they touch (``config``,
``step_type``, ``pipeline__name``) are unchanged since the migration was
written, so the current model is a faithful stand-in for the historical one.
"""

import importlib

import pytest

from core.models.pipeline import PipelineDefinition, PipelineStep, StepType

pytestmark = pytest.mark.django_db


def _load_migration(name):
    return importlib.import_module(f"core.migrations.{name}")


class _FakeApps:
    """Minimal ``apps`` stand-in returning the live ``PipelineStep`` model."""

    def get_model(self, app_label, model_name):
        assert (app_label, model_name) == ("core", "PipelineStep")
        return PipelineStep


class Test0093StopPersistingSimpleSummaryMaxTokens:
    """``max_tokens`` on ``simple_summary_v1`` AI_CALL steps."""

    def _make_pipeline(self, name="simple_summary_v1"):
        return PipelineDefinition.objects.create(name=name)

    def _make_step(self, pipeline, order, config):
        return PipelineStep.objects.create(
            pipeline=pipeline,
            order=order,
            step_type=StepType.AI_CALL,
            name=f"Step {order}",
            config=config,
        )

    def _run(self):
        migration = _load_migration(
            "0093_stop_persisting_simple_summary_max_tokens"
        )
        migration.stop_persisting_simple_summary_max_tokens(_FakeApps(), None)

    def test_strips_exact_legacy_value(self):
        pipeline = self._make_pipeline()
        step = self._make_step(pipeline, 1, {"max_tokens": 1000, "model": "x"})

        self._run()

        step.refresh_from_db()
        assert "max_tokens" not in step.config
        assert step.config["model"] == "x"

    def test_leaves_deliberate_override_alone(self):
        pipeline = self._make_pipeline()
        step = self._make_step(pipeline, 1, {"max_tokens": 2048})

        self._run()

        step.refresh_from_db()
        assert step.config["max_tokens"] == 2048

    def test_leaves_absent_value_alone(self):
        pipeline = self._make_pipeline()
        step = self._make_step(pipeline, 1, {"model": "x"})

        self._run()

        step.refresh_from_db()
        assert "max_tokens" not in step.config

    def test_ignores_other_pipelines(self):
        other = self._make_pipeline(name="other_pipeline")
        step = self._make_step(other, 1, {"max_tokens": 1000})

        self._run()

        step.refresh_from_db()
        assert step.config["max_tokens"] == 1000
