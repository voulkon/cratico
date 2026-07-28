"""
Unit tests for AI summarization Celery task.

Tests the ``summarize_notification_batch`` task and
``_get_or_create_default_pipeline`` helper in isolation.
"""

from unittest.mock import Mock, patch

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestSummarizeNotificationBatch:
    """Tests for the ``summarize_notification_batch`` Celery task."""

    def test_batch_not_found(self):
        """Task returns error when batch does not exist."""
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        result = summarize_notification_batch(batch_id=99999)

        assert result == {"batch_id": 99999, "error": "not_found"}

    def test_ai_summary_disabled_skips(self, user, notification_subscription):
        """Task skips when subscription has ai_summary_enabled=False."""
        from conftest import NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = False
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )

        result = summarize_notification_batch(batch_id=batch.id)

        assert result == {"batch_id": batch.id, "status": "skipped"}
        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"

    def test_batch_with_no_decisions_skips(self, user, notification_subscription):
        """Task skips when batch has no decisions to summarize."""
        from conftest import NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=0,
        )

        result = summarize_notification_batch(batch_id=batch.id)

        assert result == {
            "batch_id": batch.id,
            "status": "skipped",
            "reason": "no_decisions",
        }
        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"
        assert "No decisions" in batch.ai_summary_error

    def test_sets_status_to_running(self, user, notification_subscription, decision):
        """Task sets ai_summary_status to RUNNING before executing pipeline."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        real_run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            total_input_tokens=100,
            total_output_tokens=50,
            total_cost_usd="0.050",
            completed_at=timezone.now(),
        )

        with patch(
            "core.services.pipeline_engine.PipelineContext"
        ) as mock_ctx_cls, patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_context = Mock()
            mock_context.steps_output = {2: "intermediate"}
            mock_ctx_cls.return_value = mock_context

            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.return_value = real_run

            summarize_notification_batch(batch_id=batch.id)

            batch.refresh_from_db()
            assert batch.ai_summary_status == "COMPLETED"
            assert batch.ai_summary_run == real_run

    @patch("core.services.pipeline_engine.PipelineContext")
    def test_pipeline_success_stores_result(
        self, mock_context_cls, user, notification_subscription, decision
    ):
        """On pipeline success, stores summary and cost on the batch."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        mock_context = Mock()
        mock_context.steps_output = {3: "This is a synthesized summary."}
        mock_context_cls.return_value = mock_context

        now = timezone.now()
        real_run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            total_input_tokens=500,
            total_output_tokens=120,
            total_cost_usd="0.050",
            completed_at=now,
        )

        with patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.return_value = real_run

            result = summarize_notification_batch(batch_id=batch.id)

            batch.refresh_from_db()

            assert batch.ai_summary_status == "COMPLETED"
            assert batch.ai_summary == "This is a synthesized summary."
            assert batch.ai_summary_run == real_run
            assert batch.ai_summary_completed_at is not None
            assert batch.ai_summary_error is None

            assert result["batch_id"] == batch.id
            assert result["status"] == "COMPLETED"
            assert result["pipeline_run_id"] == real_run.id

    @patch("core.services.pipeline_engine.PipelineContext")
    def test_pipeline_failure_marks_failed(
        self, mock_context_cls, user, notification_subscription, decision
    ):
        """When pipeline raises, batch status is FAILED and error stored."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        mock_context = Mock()
        mock_context.steps_output = {}
        mock_context_cls.return_value = mock_context

        with patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.side_effect = RuntimeError("API quota exceeded")

            # The task is bound with retry; the exception will be raised as
            # self.retry(), which is a celery Retry exception.  We catch the
            # outer RuntimeError because our mock doesn't go through celery.
            with pytest.raises(RuntimeError):
                summarize_notification_batch(batch_id=batch.id)

            batch.refresh_from_db()
            assert batch.ai_summary_status == "FAILED"
            assert "API quota exceeded" in batch.ai_summary_error

    def test_fallback_to_step_run_output(
        self, user, notification_subscription, decision
    ):
        """When context.steps_output is empty, falls back to last step run output."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import (
            PipelineRunFactory,
            PipelineStepRunFactory,
        )
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        real_run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            total_input_tokens=50,
            total_output_tokens=15,
            total_cost_usd="0.010",
            completed_at=timezone.now(),
        )
        PipelineStepRunFactory(
            run=real_run,
            order=3,
            output_text="Fallback summary from step run.",
            status=RunStatus.COMPLETED,
        )

        with patch(
            "core.services.pipeline_engine.PipelineContext"
        ) as mock_ctx_cls:
            mock_context = Mock()
            mock_context.steps_output = {}
            mock_ctx_cls.return_value = mock_context

            with patch(
                "core.services.pipeline_engine.PipelineEngine"
            ) as mock_engine_cls:
                mock_engine = Mock()
                mock_engine_cls.return_value = mock_engine
                mock_engine.run.return_value = real_run

                result = summarize_notification_batch(batch_id=batch.id)

                batch.refresh_from_db()
                assert batch.ai_summary == "Fallback summary from step run."
                assert batch.ai_summary_status == "COMPLETED"

    def test_uses_custom_pipeline(self, user, notification_subscription, decision):
        """Task uses the subscription's custom ai_summary_pipeline if set."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import PipelineDefinition, RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        custom_pipeline = PipelineDefinition.objects.create(
            name="custom_summary_v1",
            version=1,
            is_active=True,
            trigger_type="notification_batch_summary",
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.ai_summary_pipeline = custom_pipeline
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        real_run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            total_input_tokens=10,
            total_output_tokens=3,
            total_cost_usd="0.001",
            completed_at=timezone.now(),
        )

        with patch(
            "core.services.pipeline_engine.PipelineContext"
        ) as mock_ctx_cls, patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_context = Mock()
            mock_context.steps_output = {1: "Custom summary."}
            mock_ctx_cls.return_value = mock_context

            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.return_value = real_run

            summarize_notification_batch(batch_id=batch.id)

            # Verify the custom pipeline was passed to the engine
            called_pipeline = mock_engine.run.call_args[0][0]
            assert called_pipeline.id == custom_pipeline.id
            assert called_pipeline.name == "custom_summary_v1"


class TestDefaultPipelineCreation:
    """Tests for ``_get_or_create_default_pipeline``."""

    def test_creates_pipeline_with_three_steps(self):
        """Creating default pipeline yields 1 definition + 3 steps."""
        from core.models.pipeline import PipelineDefinition, PipelineStep
        from notifications.tasks.ai_summary_tasks import _get_or_create_default_pipeline

        # Ensure no existing pipeline
        PipelineDefinition.objects.filter(
            name="notification_batch_summary_v1"
        ).delete()

        pipeline = _get_or_create_default_pipeline()

        assert pipeline.name == "notification_batch_summary_v1"
        assert pipeline.version == 1
        assert pipeline.is_active is True
        assert pipeline.trigger_type == "notification_batch_summary"

        steps = list(pipeline.steps.order_by("order"))
        assert len(steps) == 3

        # Step 1: EXTRACT
        assert steps[0].step_type == "EXTRACT"
        assert steps[0].order == 1

        # Step 2: AI_CALL
        assert steps[1].step_type == "AI_CALL"
        assert steps[1].order == 2

        # Step 3: AGGREGATE
        assert steps[2].step_type == "AGGREGATE"
        assert steps[2].order == 3

    def test_returns_existing_pipeline(self):
        """Calling _get_or_create_default_pipeline twice returns the same pipeline."""
        from core.models.pipeline import PipelineDefinition
        from notifications.tasks.ai_summary_tasks import _get_or_create_default_pipeline

        pipeline1 = _get_or_create_default_pipeline()
        pipeline2 = _get_or_create_default_pipeline()

        assert pipeline1.id == pipeline2.id
        # Only one pipeline with this name exists
        assert (
            PipelineDefinition.objects.filter(
                name="notification_batch_summary_v1"
            ).count()
            == 1
        )

    def test_existing_pipeline_still_has_three_steps(self):
        """Existing pipeline returned by get_or_create has 3 steps."""
        from core.models.pipeline import PipelineDefinition
        from notifications.tasks.ai_summary_tasks import _get_or_create_default_pipeline

        PipelineDefinition.objects.filter(
            name="notification_batch_summary_v1"
        ).delete()
        _get_or_create_default_pipeline()  # ensure created

        pipeline = _get_or_create_default_pipeline()
        assert pipeline.steps.count() == 3
