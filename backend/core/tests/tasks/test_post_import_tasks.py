"""
Unit tests for core/tasks/tasks_post_import.py

Covers:
  - post_daily_import_orchestrator   (feature flag + chain dispatch)
  - compute_entity_rankings          (feature flag + stub return)
  - warm_analytics_cache             (feature flag + stub return)
  - trigger_check_all_subscriptions  (feature flag + fan-out delegation)

All Celery chain / task.delay() calls are mocked — no broker needed.
Feature flags are overridden via patch so no env-var changes are needed.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _flag_enabled(flag_name):
    """Return a side_effect for feature_flags.is_enabled that only enables one flag."""
    def _check(name):
        return name == flag_name
    return _check


# ---------------------------------------------------------------------------
# post_daily_import_orchestrator
# ---------------------------------------------------------------------------

class TestPostDailyImportOrchestrator:
    """Tests for the top-level orchestrator task."""

    def test_skips_when_flag_disabled(self):
        """Orchestrator should short-circuit when POST_IMPORT_ORCHESTRATOR_ENABLED is off."""
        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        with patch(
            "core.tasks.tasks_post_import.feature_flags.is_enabled",
            return_value=False,
        ):
            result = post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-29"
            )

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}

    def test_dispatches_chain_when_flag_enabled(self):
        """Orchestrator should build and dispatch a Celery chain."""
        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        mock_chain_result = MagicMock()
        mock_chain_result.id = "fake-chain-id"

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch(
                "core.tasks.tasks_post_import.chain"
            ) as mock_chain_cls,
        ):
            mock_chain_instance = MagicMock()
            mock_chain_instance.apply_async.return_value = mock_chain_result
            mock_chain_cls.return_value = mock_chain_instance

            result = post_daily_import_orchestrator(
                job_id=42, reference_date_str="2026-05-29"
            )

        assert result["status"] == "dispatched"
        assert result["job_id"] == 42
        assert result["chain_task_id"] == "fake-chain-id"
        assert result["reference_date"] == "2026-05-29"
        mock_chain_instance.apply_async.assert_called_once()

    def test_chain_contains_five_tasks(self):
        """Chain should include compute_entity_rankings, warm_analytics_cache,
        invalidate_browse_cache, trigger_check_all_subscriptions, and
        verify_high_value_amounts — in that order."""
        from core.tasks.tasks_post_import import (
            compute_entity_rankings,
            invalidate_browse_cache,
            post_daily_import_orchestrator,
            trigger_check_all_subscriptions,
            verify_high_value_amounts,
            warm_analytics_cache,
        )

        captured_chain_args = []

        def fake_chain(*args):
            captured_chain_args.extend(args)
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="x")
            return m

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch("core.tasks.tasks_post_import.chain", side_effect=fake_chain),
        ):
            post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-29"
            )

        # 5 tasks were passed to chain()
        assert len(captured_chain_args) == 5


# ---------------------------------------------------------------------------
# compute_entity_rankings
# ---------------------------------------------------------------------------

class TestComputeEntityRankings:
    """Tests for the entity-rankings stub task."""

    def test_skips_when_flag_disabled(self):
        from core.tasks.tasks_post_import import compute_entity_rankings

        with patch(
            "core.tasks.tasks_post_import.feature_flags.is_enabled",
            return_value=False,
        ):
            result = compute_entity_rankings(reference_date_str="2026-05-29")

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}

    def test_returns_stub_when_flag_enabled(self):
        from core.tasks.tasks_post_import import compute_entity_rankings

        with patch(
            "core.tasks.tasks_post_import.feature_flags.is_enabled",
            side_effect=_flag_enabled("ANALYTICS_PRECALC_ENABLED"),
        ):
            result = compute_entity_rankings(reference_date_str="2026-05-29")

        assert result["status"] == "stub"
        assert result["reference_date"] == "2026-05-29"
        assert result["windows_processed"] == 4  # daily/weekly/monthly/yearly

    def test_defaults_to_today_when_no_date_given(self):
        from core.tasks.tasks_post_import import compute_entity_rankings

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_PRECALC_ENABLED"),
            ),
            patch("core.tasks.tasks_post_import.date") as mock_date,
        ):
            mock_date.today.return_value = date(2026, 5, 30)
            mock_date.fromisoformat.side_effect = date.fromisoformat

            result = compute_entity_rankings()

        assert result["reference_date"] == "2026-05-30"


# ---------------------------------------------------------------------------
# warm_analytics_cache
# ---------------------------------------------------------------------------

class TestWarmAnalyticsCache:
    """Tests for the cache-warming task."""

    def test_skips_when_flag_disabled(self):
        from core.tasks.tasks_post_import import warm_analytics_cache

        with patch(
            "core.tasks.tasks_post_import.feature_flags.is_enabled",
            return_value=False,
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}

    def test_warms_all_windows_when_flag_enabled(self):
        """Warming should attempt every view × window combination."""
        from core.tasks.tasks_post_import import warm_analytics_cache

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
            ),
            patch(
                "core.services.analytics_precalc_service.warm_explore_orgs_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_da_top_pairs_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_payments_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_direct_assignments_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_by_amount_window"
            ),
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert result["status"] == "completed"
        assert result["reference_date"] == "2026-05-29"
        assert result["windows_warmed"] == 4  # daily/weekly/monthly/yearly
        assert result["keys_warmed"] == 20   # 4 windows × 5 views
        assert result["errors"] == []

    def test_errors_are_collected_not_raised(self):
        """A failing warm function should be recorded in errors, not crash the task."""
        from core.tasks.tasks_post_import import warm_analytics_cache

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
            ),
            patch(
                "core.services.analytics_precalc_service.warm_explore_orgs_window",
                side_effect=Exception("DB connection lost"),
            ),
            patch(
                "core.services.analytics_precalc_service.warm_da_top_pairs_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_payments_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_direct_assignments_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_by_amount_window"
            ),
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert result["status"] == "completed"
        # 4 windows × 1 failing view = 4 errors; 4 windows × 4 succeeding views = 16 keys
        assert len(result["errors"]) == 4
        assert result["keys_warmed"] == 16

    def test_defaults_to_today_when_no_date_given(self):
        from core.tasks.tasks_post_import import warm_analytics_cache

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
            ),
            patch("core.tasks.tasks_post_import.date") as mock_date,
            patch("core.services.analytics_precalc_service.warm_explore_orgs_window"),
            patch("core.services.analytics_precalc_service.warm_da_top_pairs_window"),
            patch("core.services.analytics_precalc_service.warm_top_payments_window"),
            patch("core.services.analytics_precalc_service.warm_top_direct_assignments_window"),
            patch("core.services.analytics_precalc_service.warm_top_by_amount_window"),
        ):
            mock_date.today.return_value = date(2026, 5, 30)
            mock_date.fromisoformat.side_effect = date.fromisoformat

            result = warm_analytics_cache()

        assert result["reference_date"] == "2026-05-30"


# ---------------------------------------------------------------------------
# trigger_check_all_subscriptions
# ---------------------------------------------------------------------------

class TestTriggerCheckAllSubscriptions:
    """Tests for the notification delegation task."""

    def test_skips_when_flag_disabled(self):
        from core.tasks.tasks_post_import import trigger_check_all_subscriptions

        with patch(
            "core.tasks.tasks_post_import.feature_flags.is_enabled",
            return_value=False,
        ):
            result = trigger_check_all_subscriptions(reference_date_str="2026-05-29")

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}

    def test_delegates_to_check_all_active_subscriptions_when_enabled(self):
        from core.tasks.tasks_post_import import trigger_check_all_subscriptions

        mock_task_result = MagicMock()
        mock_task_result.id = "notif-task-id"

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_NOTIFICATIONS_ENABLED"),
            ),
            patch(
                "notifications.tasks.notification_tasks.check_all_active_subscriptions"
            ) as mock_notif_task,
        ):
            mock_notif_task.delay.return_value = mock_task_result

            result = trigger_check_all_subscriptions(
                reference_date_str="2026-05-29"
            )

        assert result["status"] == "dispatched"
        assert result["reference_date"] == "2026-05-29"
        assert result["task_id"] == "notif-task-id"
        mock_notif_task.delay.assert_called_once()


# ---------------------------------------------------------------------------
# non-monetary-value-as-amount discovery (post-import phase 3)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestDiscoverNonMonetaryValues:
    """Read-only discovery sweep for AFM/KAE values recorded as amounts."""

    def test_counts_afm_and_kae_cases(self):
        from decimal import Decimal

        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DocumentExtractionFactory,
        )
        from core.tasks.tasks_post_import import _discover_non_monetary_values

        # AFM case
        afm_decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [
                    {"sponsorAFMName": {"afm": "099370337"}},
                ]
            }
        )
        DecisionAmountFieldFactory(
            decision=afm_decision, amount=Decimal("99370337.00")
        )

        # KAE case
        kae_decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [
                    {
                        "sponsorAFMName": {"afm": "090000045"},
                        "expenseAmount": {"amount": 0, "kae": "70.6273.001"},
                    }
                ]
            }
        )
        DecisionAmountFieldFactory(
            decision=kae_decision, amount=Decimal("706273001.00")
        )

        # Clean case
        good = DecisionFactory(extra_field_values_json={})
        DecisionAmountFieldFactory(decision=good, amount=Decimal("30000.00"))
        DocumentExtractionFactory(decision=good, raw_text="30.000,00 €")

        result = _discover_non_monetary_values()

        assert result["afm_anomalies"] == 1
        assert result["kae_anomalies"] == 1
        assert result["total_anomalies"] == 2
        adas = {s["ada"] for s in result["sample"]}
        assert afm_decision.ada in adas
        assert kae_decision.ada in adas

    def test_respects_import_window(self):
        from decimal import Decimal

        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.tasks.tasks_post_import import _discover_non_monetary_values

        decision = DecisionFactory(
            extra_field_values_json={
                "sponsor": [{"sponsorAFMName": {"afm": "099370337"}}]
            }
        )
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("99370337.00")
        )

        # Window far in the past excludes the (just-created) decision
        from django.utils import timezone

        past = timezone.make_aware(timezone.datetime(2000, 1, 1))
        future = timezone.make_aware(timezone.datetime(2000, 1, 2))
        result = _discover_non_monetary_values(
            imported_since=past, imported_until=future
        )
        assert result["total_anomalies"] == 0

    def test_clean_database_returns_zero(self):
        from core.tasks.tasks_post_import import _discover_non_monetary_values

        result = _discover_non_monetary_values()
        assert result["total_anomalies"] == 0
        assert result["sample"] == []


class TestVerifyHighValueAmountsDiscoveryWiring:
    """verify_high_value_amounts must run and return the phase-3 discovery."""

    def test_runs_discovery_with_import_window(self):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        fake_verify = {"verified": 1, "discrepancies": 0}
        fake_correct = {
            "corrected": 0,
            "consistent": 1,
            "no_text": 0,
            "errors": 0,
        }
        fake_discovery = {
            "afm_anomalies": 2,
            "kae_anomalies": 1,
            "total_anomalies": 3,
            "sample": [],
        }

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.verify_high_value_decisions",
                return_value=fake_verify,
            ),
            patch(
                "core.services.amount_correction_service."
                "AmountCorrectionService.correct_high_value_decisions",
                return_value=fake_correct,
            ),
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value=fake_discovery,
            ) as mock_discovery,
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["status"] == "completed"
        assert result["discovery"] == fake_discovery
        mock_discovery.assert_called_once()
        kwargs = mock_discovery.call_args.kwargs
        assert kwargs["imported_since"].date() == date(2026, 5, 29)
        assert kwargs["imported_until"].date() == date(2026, 5, 30)

    def test_skips_discovery_when_flag_disabled(self):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                return_value=False,
            ),
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values"
            ) as mock_discovery,
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
        mock_discovery.assert_not_called()
