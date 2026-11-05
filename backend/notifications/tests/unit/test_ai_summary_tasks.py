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

    @pytest.fixture(autouse=True)
    def enable_user_ai(self, user):
        """The task applies the user-level AI toggle (default: off)."""
        preference = user.notification_preference
        preference.ai_summary_enabled = True
        preference.save(update_fields=["ai_summary_enabled"])

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


class TestSummaryItemsPopulation:
    """``ai_summary_items`` — per-decision one-liners from the map step."""

    @pytest.fixture(autouse=True)
    def enable_user_ai(self, user):
        preference = user.notification_preference
        preference.ai_summary_enabled = True
        preference.save(update_fields=["ai_summary_enabled"])

    def _run_task(self, batch, decision, context, run):
        """Run ``summarize_notification_batch`` with the given context/run."""
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        with patch(
            "core.services.pipeline_engine.PipelineContext",
            return_value=context,
        ), patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.return_value = run
            result = summarize_notification_batch(batch_id=batch.id)
            # The pipeline definition passed to the engine
            pipeline_def = mock_engine.run.call_args[0][0]
        return result, pipeline_def

    def test_populates_items_map_mode(self, user, notification_subscription, decision):
        """A COMPLETED map-mode run stores one-liners keyed by decision."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import (
            _get_or_create_default_pipeline,
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        # The default batch pipeline has an active AI_CALL map step
        _get_or_create_default_pipeline()

        context = PipelineContext(
            decisions=[decision], batch=batch, user=user
        )
        context.per_item_outputs = {
            str(decision.pk): "Εγκρίθηκε δαπάνη 1.000 ευρώ για τον ανάδοχο Χ."
        }
        context.steps_output = {3: "Merged overview."}

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        result, _ = self._run_task(batch, decision, context, run)

        batch.refresh_from_db()
        assert batch.ai_summary == "Merged overview."
        assert batch.ai_summary_items == [
            {
                "decision_id": decision.pk,
                "ada": decision.ada,
                "subject": decision.subject,
                "one_liner": "Εγκρίθηκε δαπάνη 1.000 ευρώ για τον ανάδοχο Χ.",
            }
        ]
        assert result["status"] == "COMPLETED"

    def test_no_items_for_single_mode_pipeline(
        self, user, notification_subscription, decision
    ):
        """
        A pipeline without an active map-mode AI_CALL step must NOT produce
        items — its ``per_item_outputs`` holds raw extracted texts, not
        one-liners.
        """
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import PipelineDefinition, RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory

        notification_subscription.ai_summary_enabled = True
        single_mode_pipeline = PipelineDefinition.objects.create(
            name="single_mode_summary",
            version=1,
            is_active=True,
            trigger_type="notification_batch_summary",
        )
        notification_subscription.ai_summary_pipeline = single_mode_pipeline
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        context = PipelineContext(
            decisions=[decision], batch=batch, user=user
        )
        # Simulate extract-only outputs (raw texts keyed by pk)
        context.per_item_outputs = {str(decision.pk): "FULL RAW TEXT..."}
        context.steps_output = {2: "Single-mode summary."}

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        self._run_task(batch, decision, context, run)

        batch.refresh_from_db()
        assert batch.ai_summary == "Single-mode summary."
        assert batch.ai_summary_items is None

    def test_items_cleared_on_failed_run(
        self, user, notification_subscription, decision
    ):
        """
        A FAILED run must never surface items: per_item_outputs still holds
        raw extract texts at that point.
        """
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import (
            _get_or_create_default_pipeline,
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        _get_or_create_default_pipeline()

        context = PipelineContext(
            decisions=[decision], batch=batch, user=user
        )
        # Extract ran fine; the AI map step blew up afterwards
        context.per_item_outputs = {str(decision.pk): "FULL RAW TEXT..."}
        context.steps_output = {}

        run = PipelineRunFactory(
            status=RunStatus.FAILED,
            error_message="AI call failed",
        )

        self._run_task(batch, decision, context, run)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "FAILED"
        assert batch.ai_summary is None
        assert batch.ai_summary_items is None

    def test_items_skip_decisions_missing_from_map_output(
        self, user, notification_subscription, decision
    ):
        """Decisions absent from per_item_outputs are simply left out."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import (
            _get_or_create_default_pipeline,
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=2,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)
        other_decision = NotificationBatchDecisionFactory(batch=batch).decision

        _get_or_create_default_pipeline()

        context = PipelineContext(
            decisions=[decision, other_decision], batch=batch, user=user
        )
        # Only the first decision made it through the map step
        context.per_item_outputs = {
            str(decision.pk): "One-liner for first."
        }
        context.steps_output = {3: "Merged."}

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        self._run_task(batch, decision, context, run)

        batch.refresh_from_db()
        assert len(batch.ai_summary_items) == 1
        assert batch.ai_summary_items[0]["decision_id"] == decision.pk

    def test_surfaces_one_liner_cache_metadata(
        self, user, notification_subscription, decision
    ):
        """All-cache-hit runs still populate items and report hit/miss counts."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.pipeline import RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import (
            _get_or_create_default_pipeline,
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        _get_or_create_default_pipeline()

        context = PipelineContext(
            decisions=[decision], batch=batch, user=user
        )
        # Every item was a cache hit inside AICallStep
        context.per_item_outputs = {
            str(decision.pk): "Cached one-liner."
        }
        context.steps_output = {3: "Merged."}
        context.metadata["one_liner_cache"] = {"hits": 1, "misses": 0}

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        result, _ = self._run_task(batch, decision, context, run)

        assert result["status"] == "COMPLETED"
        assert result["one_liner_cache"] == {"hits": 1, "misses": 0}
        batch.refresh_from_db()
        assert batch.ai_summary_items == [
            {
                "decision_id": decision.pk,
                "ada": decision.ada,
                "subject": decision.subject,
                "one_liner": "Cached one-liner.",
            }
        ]

    def test_seeds_retry_adoption_rows(
        self, user, notification_subscription, decision
    ):
        """Internal retries adopt rows minted by the previous (failed) try so
        they are overwritten in place instead of minting new attempts."""
        from conftest import NotificationBatchDecisionFactory, NotificationBatchFactory
        from core.models.decision_one_liner import (
            DecisionOneLiner,
            OneLinerStatus,
        )
        from core.models.one_liner_config import OneLinerConfig
        from core.models.pipeline import RunStatus
        from core.services.pipeline_engine import PipelineContext
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import (
            _get_or_create_default_pipeline,
        )

        notification_subscription.ai_summary_enabled = True
        notification_subscription.save()

        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            match_count=1,
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        _get_or_create_default_pipeline()

        # The previous try's failed run minted a RUNNING attempt row
        prev_run = PipelineRunFactory(status=RunStatus.FAILED)
        ol_config = OneLinerConfig.get_or_create_for(
            prompt_kind="batch_one_liner",
            system_prompt="s",
            prompt_template="t",
            provider="OPENROUTER",
            model="test/model",
            temperature=0.3,
            max_tokens=None,
        )
        minted = DecisionOneLiner.objects.create(
            decision=decision,
            config=ol_config,
            attempt=1,
            status=OneLinerStatus.RUNNING,
            pipeline_run=prev_run,
        )
        batch.ai_summary_run = prev_run
        batch.save(update_fields=["ai_summary_run"])

        context = PipelineContext(
            decisions=[decision], batch=batch, user=user
        )
        context.per_item_outputs = {str(decision.pk): "Retry one-liner."}
        context.steps_output = {3: "Merged."}

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED,
            completed_at=timezone.now(),
        )

        self._run_task(batch, decision, context, run)

        assert context.metadata["adopt_one_liner_rows"] == {
            str(decision.pk): minted.id
        }


class TestRetriesExhausted:
    """Chord-safety: exhausted retries must not break the email chord."""

    @pytest.fixture(autouse=True)
    def enable_user_ai(self, user):
        preference = user.notification_preference
        preference.ai_summary_enabled = True
        preference.save(update_fields=["ai_summary_enabled"])

    def test_returns_error_dict_instead_of_raising(
        self, user, notification_subscription, decision
    ):
        """
        When Celery reports retries exhausted (MaxRetriesExceededError from
        ``self.retry``), the task marks the batch FAILED and RETURNS an
        error dict instead of re-raising.
        """
        from celery.exceptions import MaxRetriesExceededError

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

        real_task = summarize_notification_batch._get_current_object()

        with patch.object(
            real_task,
            "retry",
            side_effect=MaxRetriesExceededError("retries exhausted"),
        ), patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.side_effect = RuntimeError("API quota exceeded")

            result = summarize_notification_batch(batch_id=batch.id)

        assert result == {
            "batch_id": batch.id,
            "status": "FAILED",
            "error": "API quota exceeded",
            "retries_exhausted": True,
        }
        batch.refresh_from_db()
        assert batch.ai_summary_status == "FAILED"
        assert "API quota exceeded" in batch.ai_summary_error

    def test_retry_signal_still_propagates_while_retries_remain(
        self, user, notification_subscription, decision
    ):
        """
        While retries remain, ``self.retry`` raising celery's ``Retry``
        must propagate (the worker re-runs the task).
        """
        from celery.exceptions import Retry as CeleryRetry

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

        real_task = summarize_notification_batch._get_current_object()

        with patch.object(
            real_task,
            "retry",
            side_effect=CeleryRetry("retry requested"),
        ), patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine = Mock()
            mock_engine_cls.return_value = mock_engine
            mock_engine.run.side_effect = RuntimeError("transient")

            with pytest.raises(CeleryRetry):
                summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "FAILED"


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

    def test_default_steps_do_not_persist_max_tokens(self):
        """Scalar budget defaults live in code, not in step config rows.

        Omitting ``max_tokens`` keeps the step config clean and lets the
        code-level default (``ai_call.DEFAULT_MAX_TOKENS``) apply — future
        tuning of the default becomes a code change, not a data migration.
        """
        from core.models.pipeline import PipelineDefinition
        from notifications.tasks.ai_summary_tasks import _get_or_create_default_pipeline

        PipelineDefinition.objects.filter(
            name="notification_batch_summary_v1"
        ).delete()

        pipeline = _get_or_create_default_pipeline()

        for step in pipeline.steps.filter(step_type__in=("AI_CALL", "AGGREGATE")):
            assert "max_tokens" not in step.config

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
