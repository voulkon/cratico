"""Cache-aware AI summary budget, skip reasons, and shared-cache behavior."""

from unittest.mock import Mock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _enable_user_ai(user, enabled=True):
    preference = user.notification_preference
    preference.ai_summary_enabled = enabled
    preference.save(update_fields=["ai_summary_enabled"])
    return preference


def _completed_one_liner(decision, prompt_kind="batch_one_liner"):
    from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
    from core.models.one_liner_config import OneLinerConfig

    config = OneLinerConfig.get_or_create_for(
        prompt_kind=prompt_kind,
        system_prompt="s",
        prompt_template="t",
        provider="OPENROUTER",
        model="test/model",
        temperature=0.3,
        max_tokens=None,
    )
    return DecisionOneLiner.objects.create(
        decision=decision,
        config=config,
        attempt=1,
        status=OneLinerStatus.COMPLETED,
        one_liner="Shared cached one-liner.",
        completed_at=timezone.now(),
    )


class TestSkipReasons:
    def test_user_disabled_writes_reason(
        self, user, notification_subscription
    ):
        from conftest import NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        _enable_user_ai(user, enabled=False)
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save(update_fields=["ai_summary_enabled"])

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=1
        )
        summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"
        assert batch.ai_summary_skip_reason == "USER_DISABLED"

    def test_subscription_disabled_writes_reason(
        self, user, notification_subscription
    ):
        from conftest import NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        _enable_user_ai(user, enabled=True)
        notification_subscription.ai_summary_enabled = False
        notification_subscription.save(update_fields=["ai_summary_enabled"])

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=1
        )
        summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"
        assert batch.ai_summary_skip_reason == "SUBSCRIPTION_DISABLED"

    def test_no_decisions_writes_reason(self, user, notification_subscription):
        from conftest import NotificationBatchFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        _enable_user_ai(user, enabled=True)
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save(update_fields=["ai_summary_enabled"])

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=0
        )
        summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"
        assert batch.ai_summary_skip_reason == "NO_DECISIONS"

    @override_settings(NOTIFICATION_AI_NEW_DECISIONS_PER_SUBSCRIPTION_PER_DAY=0)
    def test_budget_exhausted_without_cache_skips(
        self, user, notification_subscription, decision
    ):
        from conftest import (
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        _enable_user_ai(user, enabled=True)
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save(update_fields=["ai_summary_enabled"])

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=1
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)

        summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "SKIPPED"
        assert batch.ai_summary_skip_reason == "BUDGET_EXHAUSTED"
        assert batch.ai_summary_new_count == 0

    @override_settings(NOTIFICATION_AI_NEW_DECISIONS_PER_SUBSCRIPTION_PER_DAY=0)
    def test_cached_items_still_shown_when_budget_exhausted(
        self, user, notification_subscription, decision
    ):
        """A cached one-liner is free: budget 0 still yields PARTIAL + bullets."""
        from conftest import (
            NotificationBatchDecisionFactory,
            NotificationBatchFactory,
        )
        from core.models.pipeline import RunStatus
        from core.tests.services.conftest import PipelineRunFactory
        from notifications.tasks.ai_summary_tasks import summarize_notification_batch

        _enable_user_ai(user, enabled=True)
        notification_subscription.ai_summary_enabled = True
        notification_subscription.save(update_fields=["ai_summary_enabled"])

        batch = NotificationBatchFactory(
            user=user, subscription=notification_subscription, match_count=1
        )
        NotificationBatchDecisionFactory(batch=batch, decision=decision)
        _completed_one_liner(decision)

        run = PipelineRunFactory(
            status=RunStatus.COMPLETED, completed_at=timezone.now()
        )

        def fake_engine_run(pipeline_def, context, **kwargs):
            # The cache hit is the only available bullet; the merge is skipped.
            context.per_item_outputs = {
                str(decision.pk): "Shared cached one-liner."
            }
            context.steps_output = {3: ""}
            return run

        with patch(
            "core.services.pipeline_engine.PipelineEngine"
        ) as mock_engine_cls:
            mock_engine_cls.return_value.run.side_effect = fake_engine_run
            summarize_notification_batch(batch_id=batch.id)

        batch.refresh_from_db()
        assert batch.ai_summary_status == "PARTIAL"
        assert batch.ai_summary_skip_reason == "BUDGET_EXHAUSTED"
        assert batch.ai_summary_cached_count == 1
        assert batch.ai_summary_new_count == 0
        assert batch.ai_summary_items[0]["one_liner"] == "Shared cached one-liner."


class TestSharedOneLinerCache:
    def _config(self, prompt_kind):
        from core.models.one_liner_config import OneLinerConfig

        return OneLinerConfig.get_or_create_for(
            prompt_kind=prompt_kind,
            system_prompt="s",
            prompt_template="t",
            provider="OPENROUTER",
            model="other/model",
            temperature=0.3,
            max_tokens=None,
        )

    def test_cross_config_shareable_kind_is_reused(self, decision):
        from core.services.pipeline_steps.ai_call import AICallStep

        _completed_one_liner(decision, prompt_kind="batch_one_liner")
        context = Mock()
        context.metadata = {"one_liner_cache": {"hits": 0, "misses": 0}}

        row = AICallStep()._one_liner_cache_get(
            context,
            decision,
            self._config("batch_one_liner"),
            extraction_id=None,
        )

        assert row is not None
        assert row.one_liner == "Shared cached one-liner."
        assert context.metadata["one_liner_cache"]["shared_hits"] == 1

    def test_non_shareable_kind_is_not_reused(self, decision):
        from core.services.pipeline_steps.ai_call import AICallStep

        _completed_one_liner(decision, prompt_kind="decision_analysis")
        context = Mock()
        context.metadata = {"one_liner_cache": {"hits": 0, "misses": 0}}

        row = AICallStep()._one_liner_cache_get(
            context,
            decision,
            self._config("batch_one_liner"),
            extraction_id=None,
        )

        assert row is None


class TestBudgetAllowance:
    @override_settings(NOTIFICATION_AI_NEW_DECISIONS_PER_SUBSCRIPTION_PER_DAY=25)
    def test_counts_new_decisions_not_batches(
        self, user, notification_subscription
    ):
        from conftest import NotificationBatchFactory
        from notifications.services.ai_budget import (
            subscription_new_decision_allowance,
        )

        _enable_user_ai(user, enabled=True)
        NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            ai_summary_new_count=5,
        )
        NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            ai_summary_new_count=3,
        )

        assert (
            subscription_new_decision_allowance(notification_subscription) == 17
        )

    @override_settings(NOTIFICATION_AI_NEW_DECISIONS_PER_SUBSCRIPTION_PER_DAY=25)
    def test_excluded_batch_does_not_consume_own_budget(
        self, user, notification_subscription
    ):
        from conftest import NotificationBatchFactory
        from notifications.services.ai_budget import (
            subscription_new_decision_allowance,
        )

        _enable_user_ai(user, enabled=True)
        batch = NotificationBatchFactory(
            user=user,
            subscription=notification_subscription,
            ai_summary_new_count=10,
        )

        assert subscription_new_decision_allowance(
            notification_subscription, exclude_batch_id=batch.id
        ) == 25
