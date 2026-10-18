"""
Unit tests for ``generate_decision_one_liner`` — the explicit per-decision
one-liner generation task (endpoint/backfill worker side).
"""

from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestGenerateDecisionOneLiner:
    def _run_task(self, decision, user, force=False):
        """Run the task with extraction + engine mocked.

        Returns (result, captured) where ``captured`` holds the engine-run
        trigger and the context metadata the task seeded.
        """
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from core.tasks import tasks_decision_ai

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )
        captured = {}

        def _fake_run(pipeline_def, context, trigger=None, trigger_ref=None):
            captured["trigger"] = trigger
            captured["trigger_ref"] = trigger_ref
            captured["metadata"] = context.metadata
            context.per_item_outputs[str(decision.pk)] = "Generated one-liner."
            return run

        with patch.object(
            tasks_decision_ai,
            "extract_decision_text",
            return_value={"status": "already_extracted", "extraction_id": 1},
        ) as mock_extract, patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls, patch(
            "notifications.tasks.ai_summary_tasks._get_or_create_default_pipeline"
        ) as mock_pipeline:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.side_effect = _fake_run

            result = tasks_decision_ai.generate_decision_one_liner(
                decision_id=decision.id, user_id=user.id, force=force
            )

        mock_extract.assert_called_once_with(decision.id)
        mock_pipeline.assert_called_once()
        return result, captured

    def test_not_found(self):
        from core.tasks.tasks_decision_ai import generate_decision_one_liner

        result = generate_decision_one_liner(decision_id=999999, user_id=1)
        assert result == {"decision_id": 999999, "status": "not_found"}

    def test_generates_one_liner(self, user, decision):
        result, captured = self._run_task(decision, user)

        assert result["status"] == "completed"
        assert result["one_liner"] == "Generated one-liner."
        assert result["pipeline_run_id"]
        assert result["error"] is None
        assert captured["trigger"] == "decision_one_liner"
        assert captured["trigger_ref"] == f"decision:{decision.id}"
        assert captured["metadata"]["one_liner_force"] is False

    def test_force_metadata_seeded(self, user, decision):
        """``force=True`` bypasses cache hits inside AICallStep."""
        _, captured = self._run_task(decision, user, force=True)
        assert captured["metadata"]["one_liner_force"] is True

    def test_extraction_failure_short_circuits(self, user, decision):
        """When extraction cannot produce text, no pipeline run happens."""
        from core.tasks import tasks_decision_ai

        with patch.object(
            tasks_decision_ai,
            "extract_decision_text",
            return_value={"status": "failed", "error": "download failed"},
        ), patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            result = tasks_decision_ai.generate_decision_one_liner(
                decision_id=decision.id, user_id=user.id
            )

        assert result["status"] == "extraction_failed"
        assert "download failed" in result["error"]
        mock_engine_cls.assert_not_called()

    def test_pipeline_failure_reports_failed(self, user, decision):
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from core.tasks import tasks_decision_ai

        failed_run = PipelineRunFactory(
            status=RunStatus.FAILED,
            error_message="AI call failed for item X: quota",
        )

        with patch.object(
            tasks_decision_ai,
            "extract_decision_text",
            return_value={"status": "already_extracted"},
        ), patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls, patch(
            "notifications.tasks.ai_summary_tasks._get_or_create_default_pipeline"
        ):
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.return_value = failed_run

            result = tasks_decision_ai.generate_decision_one_liner(
                decision_id=decision.id, user_id=user.id
            )

        assert result["status"] == "failed"
        assert "quota" in result["error"]
        assert result["one_liner"] is None
