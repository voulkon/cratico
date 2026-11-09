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

from collections import Counter
from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, call, patch

import pytest
from freezegun import freeze_time


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

    def test_dispatches_amount_verification_only(self):
        """The orchestrator must queue ONLY amount verification.

        Amount verification owns the rest of the post-import work: it
        dispatches the tail (rankings → invalidate → warm → notifications)
        either inline (no candidates / flag off) or from the chord body once
        every verification child finished.  Queueing the tail here as well ran
        each of those tasks twice per import — see
        ``test_post_import_tail_is_dispatched_exactly_once``.
        """
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch("core.tasks.tasks_post_import.chain") as mock_chain_cls,
            patch.object(
                tasks_post_import.verify_high_value_amounts, "si"
            ) as mock_si,
        ):
            mock_si.return_value.apply_async.return_value = MagicMock(
                id="verify-task-id"
            )

            result = post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-29"
            )

        assert result["status"] == "dispatched"
        assert result["chain_task_id"] == "verify-task-id"
        mock_chain_cls.assert_not_called()
        mock_si.assert_called_once_with(reference_date_str="2026-05-29")

    def test_post_import_tail_is_dispatched_exactly_once(self):
        """REGRESSION: duplicate notification batches (2026-09-15).

        The orchestrator used to queue the four tail tasks while
        ``finalize_amount_verification`` queued them once more, so every tail
        task — ``trigger_check_all_subscriptions`` included — ran twice per
        daily import.  The two notification fan-outs raced each other and each
        created its own ``NotificationBatch`` for the same decision.
        """
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import (
            finalize_amount_verification,
            post_daily_import_orchestrator,
        )

        tail_tasks = (
            "recover_self_counterparts",
            "compute_entity_rankings",
            "invalidate_browse_cache",
            "warm_analytics_cache",
            "trigger_check_all_subscriptions",
        )
        dispatched: list[str] = []

        def _name(sig):
            return (getattr(sig, "task", "") or "").rsplit(".", 1)[-1]

        # Every chain() the post-import code builds is recorded…
        def fake_chain(*args):
            dispatched.extend(_name(s) for s in args)
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="chain-id")
            return m

        # …and so is a direct single-task dispatch (the orchestrator's shape).
        def fake_si(*args, **kwargs):
            dispatched.append("verify_high_value_amounts")
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="verify-id")
            return m

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch("core.tasks.tasks_post_import.chain", side_effect=fake_chain),
            patch.object(
                tasks_post_import.verify_high_value_amounts,
                "si",
                side_effect=fake_si,
            ),
        ):
            post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-29"
            )

        # The chord body runs once all verification children finished.
        with (
            patch("core.tasks.tasks_post_import.chain", side_effect=fake_chain),
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ),
        ):
            finalize_amount_verification.run(
                [], reference_date_str="2026-05-29"
            )

        counts = Counter(dispatched)
        assert counts["verify_high_value_amounts"] == 1
        for task_name in tail_tasks:
            assert counts[task_name] == 1, (
                f"{task_name} was queued {counts[task_name]}× "
                f"in a single post-import run"
            )
        assert len(dispatched) == 6


class TestDailyOrchestratorImportWindow:
    """§4.2 / §5.3: the DAILY run verifies its OWN import window.

    Before the fix the daily orchestrator passed only the reference calendar
    day (yesterday), so decisions inserted by that same run (after 00:00 today)
    were not candidates — every decision was verified about 24 h late.
    """

    def test_forwards_import_window_to_verification(self):
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch.object(
                tasks_post_import.verify_high_value_amounts, "si"
            ) as mock_si,
        ):
            mock_si.return_value.apply_async.return_value = MagicMock(
                id="verify-id"
            )

            post_daily_import_orchestrator(
                job_id=1,
                reference_date_str="2026-05-28",
                imported_since_str="2026-05-29T00:30:00+00:00",
                imported_until_str="2026-05-29T00:50:00+00:00",
            )

        mock_si.assert_called_once_with(
            reference_date_str="2026-05-28",
            imported_since_str="2026-05-29T00:30:00+00:00",
            imported_until_str="2026-05-29T00:50:00+00:00",
        )

    def test_without_window_keeps_calendar_day_scope(self):
        """Tasks queued during a deploy (no window kwargs) keep working."""
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch.object(
                tasks_post_import.verify_high_value_amounts, "si"
            ) as mock_si,
        ):
            mock_si.return_value.apply_async.return_value = MagicMock(
                id="verify-id"
            )

            post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-28"
            )

        mock_si.assert_called_once_with(reference_date_str="2026-05-28")


class TestParseImportWindow:
    def test_default_window_is_the_reference_day(self):
        from django.utils import timezone as dj_timezone
        from core.tasks.tasks_post_import import _parse_import_window

        ref, since, until = _parse_import_window("2026-05-28", None, None)

        assert ref == date(2026, 5, 28)
        # Local midnight (Europe/Athens), not UTC midnight.
        assert since == dj_timezone.make_aware(
            datetime(2026, 5, 28, 0, 0)
        )
        assert until - since == timedelta(days=1)

    def test_explicit_window_is_returned_unchanged(self):
        from core.tasks.tasks_post_import import _parse_import_window

        _, since, until = _parse_import_window(
            "2026-05-28",
            "2026-05-29T00:30:00+00:00",
            "2026-05-29T00:50:00+00:00",
        )

        assert since == datetime.fromisoformat("2026-05-29T00:30:00+00:00")
        assert until == datetime.fromisoformat("2026-05-29T00:50:00+00:00")


@pytest.mark.django_db
class TestDailyRunVerifiesItsOwnInserts:
    def test_decision_inserted_by_the_daily_run_is_a_candidate(self):
        """The wanted behaviour: verification sees the run's own inserts.

        A DAILY job created 00:30 UTC imports yesterday's issue dates but
        inserts the rows after midnight today.  With the job's own window they
        are candidates of the same run; the previous day's inserts are not.
        """
        from decimal import Decimal

        from conftest import DecisionAmountFieldFactory, DecisionFactory
        from core.services.amount_verification_service import (
            AmountVerificationService,
        )
        from core.tasks.tasks_post_import import _parse_import_window

        with freeze_time("2026-05-28 12:00:00"):
            before = DecisionFactory(ada="DAILY-BEFORE")
            DecisionAmountFieldFactory(
                decision=before, amount=Decimal("200000.00")
            )

        with freeze_time("2026-05-29 00:40:00"):
            inside = DecisionFactory(ada="DAILY-INSIDE")
            DecisionAmountFieldFactory(
                decision=inside, amount=Decimal("200000.00")
            )

        ref, since, until = _parse_import_window(
            "2026-05-28",
            "2026-05-29T00:30:00+00:00",
            "2026-05-29T00:50:00+00:00",
        )
        assert ref == date(2026, 5, 28)

        candidates = AmountVerificationService().get_high_value_candidates(
            imported_since=since, imported_until=until
        )
        candidate_ids = {decision.id for decision in candidates}

        assert inside.id in candidate_ids
        assert before.id not in candidate_ids


class TestTailChainShape:
    """T07c: the tail has a daily shape (recovery + rankings + invalidation +
    warming + notifications) and an hourly shape (window-scoped recovery +
    warm today + notifications)."""

    @staticmethod
    def _task_name(sig):
        return (getattr(sig, "task", "") or "").rsplit(".", 1)[-1]

    def test_hourly_tail_chain_composition(self):
        from core.tasks.tasks_post_import import _post_verification_tail_chain

        with patch("core.tasks.tasks_post_import.chain") as mock_chain:
            _post_verification_tail_chain(
                "2026-05-29",
                imported_since_str="2026-05-29T10:00:00+00:00",
                imported_until_str="2026-05-29T11:00:00+00:00",
                tail_kind="hourly",
            )

        signatures = mock_chain.call_args.args
        assert [self._task_name(s) for s in signatures] == [
            "recover_self_counterparts",
            "warm_today_window",
            "trigger_check_all_subscriptions",
        ]
        assert signatures[0].kwargs["reference_date_str"] == "2026-05-29"
        assert (
            signatures[0].kwargs["imported_since_str"]
            == "2026-05-29T10:00:00+00:00"
        )
        assert (
            signatures[0].kwargs["imported_until_str"]
            == "2026-05-29T11:00:00+00:00"
        )
        assert signatures[0].kwargs["tail_kind"] == "hourly"
        assert signatures[1].kwargs["reference_date_str"] == "2026-05-29"
        assert signatures[2].kwargs["reference_date_str"] == "2026-05-29"

    def test_daily_tail_chain_includes_recovery_first(self):
        """Recovery runs before rankings/cache warming/notifications."""
        from core.tasks.tasks_post_import import _post_verification_tail_chain

        with patch("core.tasks.tasks_post_import.chain") as mock_chain:
            _post_verification_tail_chain("2026-05-29")

        signatures = mock_chain.call_args.args
        assert [self._task_name(s) for s in signatures] == [
            "recover_self_counterparts",
            "compute_entity_rankings",
            "invalidate_browse_cache",
            "warm_analytics_cache",
            "trigger_check_all_subscriptions",
        ]


class TestPostHourlyImportOrchestrator:
    """T07c: the hourly orchestrator queues ONLY verification, carrying the
    import-time window and tail_kind='hourly'."""

    def test_flag_disabled_skips(self):
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import (
            post_hourly_import_orchestrator,
        )

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                return_value=False,
            ),
            patch.object(
                tasks_post_import.verify_high_value_amounts, "si"
            ) as mock_si,
        ):
            result = post_hourly_import_orchestrator(
                job_id=1,
                reference_date_str="2026-05-29",
                imported_since_str="2026-05-29T09:00:00+00:00",
                imported_until_str="2026-05-29T10:00:00+00:00",
            )

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
        mock_si.assert_not_called()

    def test_dispatches_verification_with_window_and_hourly_tail(self):
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import (
            post_hourly_import_orchestrator,
        )

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch.object(
                tasks_post_import.verify_high_value_amounts, "si"
            ) as mock_si,
            patch("core.tasks.tasks_post_import.chain") as mock_chain,
        ):
            mock_si.return_value.apply_async.return_value = MagicMock(
                id="verify-hourly-id"
            )

            result = post_hourly_import_orchestrator(
                job_id=7,
                reference_date_str="2026-05-29",
                imported_since_str="2026-05-29T09:00:00+00:00",
                imported_until_str="2026-05-29T10:00:00+00:00",
            )

        assert result["status"] == "dispatched"
        assert result["job_id"] == 7
        assert result["chain_task_id"] == "verify-hourly-id"
        mock_si.assert_called_once_with(
            reference_date_str="2026-05-29",
            imported_since_str="2026-05-29T09:00:00+00:00",
            imported_until_str="2026-05-29T10:00:00+00:00",
            tail_kind="hourly",
        )
        # The orchestrator never queues a tail task itself.
        mock_chain.assert_not_called()


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
            patch(
                "core.services.analytics_precalc_service.warm_top_banded_da_receivers_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_banded_da_givers_window"
            ),
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert result["status"] == "completed"
        assert result["reference_date"] == "2026-05-29"
        assert result["windows_warmed"] == 4  # daily/weekly/monthly/yearly
        assert result["keys_warmed"] == 28   # 4 windows × 7 views
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
            patch(
                "core.services.analytics_precalc_service.warm_top_banded_da_receivers_window"
            ),
            patch(
                "core.services.analytics_precalc_service.warm_top_banded_da_givers_window"
            ),
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert result["status"] == "completed"
        # 4 windows × 1 failing view = 4 errors; 4 windows × 6 succeeding views = 24 keys
        assert len(result["errors"]) == 4
        assert result["keys_warmed"] == 24

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
            patch("core.services.analytics_precalc_service.warm_top_banded_da_receivers_window"),
            patch("core.services.analytics_precalc_service.warm_top_banded_da_givers_window"),
        ):
            mock_date.today.return_value = date(2026, 5, 30)
            mock_date.fromisoformat.side_effect = date.fromisoformat

            result = warm_analytics_cache()

        assert result["reference_date"] == "2026-05-30"

    def test_warm_analytics_cache_uses_warm_window_helper(self):
        """The per-window body is factored into _warm_window; the task still
        iterates the same 4 calendar windows with the same (start, end)."""
        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import (
            _calendar_windows,
            warm_analytics_cache,
        )

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
            ),
            patch.object(
                tasks_post_import,
                "_warm_window",
                return_value={"keys_warmed": 7, "errors": []},
            ) as mock_warm,
        ):
            result = warm_analytics_cache(reference_date_str="2026-05-29")

        assert mock_warm.call_args_list == [
            call(label, start, end)
            for label, start, end in _calendar_windows(date(2026, 5, 29))
        ]
        assert result["windows_warmed"] == 4
        assert result["keys_warmed"] == 28
        assert result["errors"] == []


class TestWarmTodayWindow:
    """T07b: the hourly warm covers exactly the (today, today) window."""

    WARM_FN_TARGETS = (
        "core.services.analytics_precalc_service.warm_explore_orgs_window",
        "core.services.analytics_precalc_service.warm_da_top_pairs_window",
        "core.services.analytics_precalc_service.warm_top_payments_window",
        "core.services.analytics_precalc_service."
        "warm_top_direct_assignments_window",
        "core.services.analytics_precalc_service.warm_top_by_amount_window",
        "core.services.analytics_precalc_service."
        "warm_top_banded_da_receivers_window",
        "core.services.analytics_precalc_service."
        "warm_top_banded_da_givers_window",
    )

    EXPECTED_KWARGS = (
        {"max_limit": 200, "page_size": 6},
        {"max_limit": 50, "page_size": 6},
        {"max_limit": 100, "page_size": 5},
        {"max_limit": 100, "page_size": 5},
        {"max_limit": 100, "page_size": 5},
        {"max_limit": 100, "page_size": 5},
        {"max_limit": 100, "page_size": 5},
    )

    def _patch_warm_fns(self, stack):
        return [
            stack.enter_context(patch(target))
            for target in self.WARM_FN_TARGETS
        ]

    def test_warm_today_window_single_today_window(self):
        from contextlib import ExitStack

        from django.utils import timezone

        from core.tasks.tasks_post_import import warm_today_window

        today = timezone.localdate()

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "core.tasks.tasks_post_import.feature_flags.is_enabled",
                    side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
                )
            )
            stack.enter_context(
                patch(
                    "core.services.response_cache_service."
                    "ResponseCacheService.set_warmup_status"
                )
            )
            stack.enter_context(
                patch(
                    "core.services.response_cache_service."
                    "ResponseCacheService.clear_warmup_status"
                )
            )
            warm_mocks = self._patch_warm_fns(stack)

            result = warm_today_window(reference_date_str="2026-05-01")

        assert result["status"] == "completed"
        assert result["windows_warmed"] == 1
        assert result["keys_warmed"] == 7
        assert result["reference_date"] == today.isoformat()
        assert result["errors"] == []

        for mock_warm, expected in zip(warm_mocks, self.EXPECTED_KWARGS):
            mock_warm.assert_called_once_with(
                start_date_str=today.isoformat(),
                end_date_str=today.isoformat(),
                end_date=today,
                **expected,
            )

    def test_warm_today_window_sentinel_lifecycle(self):
        """One failing view clears its sentinel; the other six are marked
        ready and the task reports the error without raising."""
        from contextlib import ExitStack

        from core.tasks.tasks_post_import import warm_today_window

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "core.tasks.tasks_post_import.feature_flags.is_enabled",
                    side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
                )
            )
            mock_set = stack.enter_context(
                patch(
                    "core.services.response_cache_service."
                    "ResponseCacheService.set_warmup_status"
                )
            )
            mock_clear = stack.enter_context(
                patch(
                    "core.services.response_cache_service."
                    "ResponseCacheService.clear_warmup_status"
                )
            )
            warm_mocks = self._patch_warm_fns(stack)
            warm_mocks[0].side_effect = Exception("db connection lost")

            result = warm_today_window()

        assert result["status"] == "completed"
        assert result["keys_warmed"] == 6
        assert len(result["errors"]) == 1
        assert result["errors"][0]["view"] == "explore_orgs"

        assert mock_clear.call_count == 1
        statuses = [c.args[1] for c in mock_set.call_args_list]
        assert statuses.count("in_progress") == 7
        assert statuses.count("ready") == 6

    def test_warm_today_window_flag_disabled(self):
        from core.tasks.tasks_post_import import warm_today_window

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                return_value=False,
            ),
            patch("core.tasks.tasks_post_import._warm_window") as mock_warm,
        ):
            result = warm_today_window(reference_date_str="2026-05-29")

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
        mock_warm.assert_not_called()

    def test_warm_today_window_ignores_reference_date_mismatch(self):
        from django.utils import timezone

        import core.tasks.tasks_post_import as tasks_post_import
        from core.tasks.tasks_post_import import warm_today_window

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_WARMUP_ENABLED"),
            ),
            patch.object(
                tasks_post_import,
                "_warm_window",
                return_value={"keys_warmed": 7, "errors": []},
            ) as mock_warm,
        ):
            result = warm_today_window(reference_date_str=yesterday.isoformat())

        mock_warm.assert_called_once_with("daily", today, today)
        assert result["reference_date"] == today.isoformat()


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
    """verify_high_value_amounts (fan-out parent) must dispatch the chord and
    the finalize body must run discovery + cache invalidation + continuation."""

    def test_dispatches_chord_with_batches(self):
        from core.tasks import tasks_post_import
        from core.tasks.tasks_post_import import verify_high_value_amounts

        candidates = [MagicMock(id=i) for i in range(60)]  # → 3 batches of 25

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=candidates,
            ),
            # Pin the batch size so the test doesn't depend on the
            # VERIFY_AMOUNT_BATCH_SIZE env default (currently 50).
            patch.object(tasks_post_import, "VERIFY_BATCH_SIZE", 25),
            patch(
                "core.tasks.tasks_post_import.chord"
            ) as mock_chord_cls,
        ):
            mock_chord_instance = MagicMock()
            mock_chord_instance.return_value = MagicMock(id="chord-id")
            mock_chord_cls.return_value = mock_chord_instance

            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["status"] == "dispatched"
        assert result["total_candidates"] == 60
        assert result["batches_dispatched"] == 3
        # chord(header) returns the chord instance; calling it with the body
        # signature attaches the callback — two separate calls.
        (header,) = mock_chord_cls.call_args.args
        (body,) = mock_chord_instance.call_args.args
        assert len(header) == 3
        assert body.task.endswith("finalize_amount_verification")

    def test_empty_candidates_run_finalize_inline(self):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[],
            ),
            patch(
                "core.tasks.tasks_post_import.finalize_amount_verification"
            ) as mock_finalize,
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["total_candidates"] == 0
        assert result["batches_dispatched"] == 0
        mock_finalize.run.assert_called_once()

    @staticmethod
    def _tail_task_names():
        return [
            "recover_self_counterparts",
            "compute_entity_rankings",
            "invalidate_browse_cache",
            "warm_analytics_cache",
            "trigger_check_all_subscriptions",
        ]

    @classmethod
    def _recording_chain(cls, dispatched):
        """A fake celery.chain() that records the task names it was given."""
        def _name(sig):
            return (getattr(sig, "task", "") or "").rsplit(".", 1)[-1]

        def fake_chain(*args):
            dispatched.extend(_name(s) for s in args)
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="tail-id")
            return m

        return fake_chain

    def test_skips_when_flag_disabled(self):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                return_value=False,
            ),
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values"
            ) as mock_discovery,
            # The post-import tail is still dispatched — dedicated test below.
            patch("core.tasks.tasks_post_import.chain"),
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["status"] == "skipped"
        assert result["reason"] == "feature_flag_disabled"
        mock_discovery.assert_not_called()

    def test_flag_disabled_still_dispatches_the_tail(self):
        """REGRESSION: amount verification owns the post-import tail, so
        turning verification OFF must not silently disable entity rankings,
        cache warming and notifications."""
        from core.tasks.tasks_post_import import verify_high_value_amounts

        dispatched = []

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                return_value=False,
            ),
            patch(
                "core.tasks.tasks_post_import.chain",
                side_effect=self._recording_chain(dispatched),
            ),
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["status"] == "skipped"
        assert dispatched == self._tail_task_names()

    def test_candidate_query_failure_still_dispatches_the_tail(self):
        """A failing candidate query must not take the rest of the post-import
        work down with it — amounts are untouched, so the tail is still safe
        (and nothing else will queue it)."""
        from core.tasks.tasks_post_import import verify_high_value_amounts

        dispatched = []

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                side_effect=RuntimeError("db is gone"),
            ),
            patch(
                "core.tasks.tasks_post_import.chain",
                side_effect=self._recording_chain(dispatched),
            ),
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        # @log_task_run(swallow_errors=True) reports the failure instead of
        # raising, so the worker keeps going…
        assert result["status"] == "error"
        assert "db is gone" in result["error"]
        # …and the tail still runs.
        assert dispatched == self._tail_task_names()

    def test_chord_body_carries_an_errback_that_dispatches_the_tail(self):
        """If a verification child fails permanently (killed past max_retries,
        broker loss), Celery marks the chord failed and the body never runs —
        the link_error errback is the only thing left that can queue the tail."""
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[MagicMock(id=1)],
            ),
            patch("core.tasks.tasks_post_import.chord") as mock_chord_cls,
        ):
            mock_chord_instance = MagicMock()
            mock_chord_instance.return_value = MagicMock(id="chord-id")
            mock_chord_cls.return_value = mock_chord_instance

            verify_high_value_amounts(reference_date_str="2026-05-29")

        (body,) = mock_chord_instance.call_args.args
        errbacks = body.options.get("link_error") or []
        assert len(errbacks) == 1
        assert errbacks[0].task.endswith("amount_verification_chord_error_tail")
        assert errbacks[0].kwargs["reference_date_str"] == "2026-05-29"

    def test_chord_dispatch_failure_still_dispatches_the_tail(self):
        """A broker hiccup while QUEUEING the chord must not take the rest of
        the post-import work down — no amount was touched yet, so the tail is
        safe (and nothing else will queue it)."""
        from core.tasks.tasks_post_import import verify_high_value_amounts

        dispatched = []

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[MagicMock(id=1)],
            ),
            patch(
                "core.tasks.tasks_post_import.chord",
                side_effect=RuntimeError("broker down"),
            ),
            patch(
                "core.tasks.tasks_post_import.chain",
                side_effect=self._recording_chain(dispatched),
            ),
        ):
            result = verify_high_value_amounts(reference_date_str="2026-05-29")

        assert result["status"] == "error"
        assert "broker down" in result["error"]
        assert dispatched == self._tail_task_names()


class TestVerifyWindowThreading:
    """T07a: an explicit import-time window overrides the reference calendar day
    while the default (no window strings) stays byte-for-byte unchanged."""

    @staticmethod
    def _run_verify(**kwargs):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[],
            ) as mock_candidates,
            patch(
                "core.tasks.tasks_post_import.finalize_amount_verification"
            ),
        ):
            verify_high_value_amounts(**kwargs)

        return mock_candidates

    def test_verify_window_strings_override_day_scope(self):
        from datetime import datetime

        mock_candidates = self._run_verify(
            reference_date_str="2026-05-29",
            imported_since_str="2026-05-29T09:00:00+00:00",
            imported_until_str="2026-05-29T10:00:00+00:00",
        )

        kwargs = mock_candidates.call_args.kwargs
        assert kwargs["imported_since"] == datetime.fromisoformat(
            "2026-05-29T09:00:00+00:00"
        )
        assert kwargs["imported_until"] == datetime.fromisoformat(
            "2026-05-29T10:00:00+00:00"
        )
        # The reference date no longer forces [00:00, +1 day).
        assert kwargs["imported_since"].hour == 9
        assert kwargs["imported_until"].hour == 10

    def test_verify_naive_window_strings_made_aware(self):
        from django.utils import timezone as dj_timezone

        mock_candidates = self._run_verify(
            reference_date_str="2026-05-29",
            imported_since_str="2026-05-29T09:00:00",
            imported_until_str="2026-05-29T10:00:00",
        )

        kwargs = mock_candidates.call_args.kwargs
        assert dj_timezone.is_aware(kwargs["imported_since"])
        assert dj_timezone.is_aware(kwargs["imported_until"])
        assert kwargs["imported_since"].hour == 9
        assert kwargs["imported_until"].hour == 10

    def test_verify_default_day_scope_unchanged(self):
        mock_candidates = self._run_verify(reference_date_str="2026-05-29")

        kwargs = mock_candidates.call_args.kwargs
        assert kwargs["imported_since"].date() == date(2026, 5, 29)
        assert kwargs["imported_since"].hour == 0
        assert kwargs["imported_until"].date() == date(2026, 5, 30)
        assert kwargs["imported_until"].hour == 0

    def test_finalize_receives_threaded_window(self):
        from datetime import datetime

        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ) as mock_discovery,
            patch(
                "core.tasks.tasks_post_import._dispatch_post_verification_tail",
                return_value="tail-id",
            ) as mock_dispatch,
        ):
            finalize_amount_verification.run(
                [],
                reference_date_str="2026-05-29",
                imported_since_str="2026-05-29T09:00:00+00:00",
                imported_until_str="2026-05-29T10:00:00+00:00",
            )

        discovery_kwargs = mock_discovery.call_args.kwargs
        assert discovery_kwargs["imported_since"] == datetime.fromisoformat(
            "2026-05-29T09:00:00+00:00"
        )
        assert discovery_kwargs["imported_until"] == datetime.fromisoformat(
            "2026-05-29T10:00:00+00:00"
        )
        dispatch_kwargs = mock_dispatch.call_args.kwargs
        assert (
            dispatch_kwargs["imported_since_str"]
            == "2026-05-29T09:00:00+00:00"
        )
        assert (
            dispatch_kwargs["imported_until_str"]
            == "2026-05-29T10:00:00+00:00"
        )

    def test_finalize_default_day_scope_unchanged(self):
        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ) as mock_discovery,
            patch(
                "core.tasks.tasks_post_import._dispatch_post_verification_tail",
                return_value="tail-id",
            ),
        ):
            finalize_amount_verification.run(
                [], reference_date_str="2026-05-29"
            )

        kwargs = mock_discovery.call_args.kwargs
        assert kwargs["imported_since"].date() == date(2026, 5, 29)
        assert kwargs["imported_since"].hour == 0
        assert kwargs["imported_until"].date() == date(2026, 5, 30)
        assert kwargs["imported_until"].hour == 0

    def test_chord_body_and_errback_carry_window(self):
        from core.tasks.tasks_post_import import verify_high_value_amounts

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled(
                    "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
                ),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[MagicMock(id=1)],
            ),
            patch("core.tasks.tasks_post_import.chord") as mock_chord_cls,
        ):
            mock_chord_instance = MagicMock()
            mock_chord_instance.return_value = MagicMock(id="chord-id")
            mock_chord_cls.return_value = mock_chord_instance

            verify_high_value_amounts(
                reference_date_str="2026-05-29",
                imported_since_str="2026-05-29T09:00:00+00:00",
                imported_until_str="2026-05-29T10:00:00+00:00",
            )

        (body,) = mock_chord_instance.call_args.args
        assert body.kwargs["imported_since_str"] == "2026-05-29T09:00:00+00:00"
        assert body.kwargs["imported_until_str"] == "2026-05-29T10:00:00+00:00"
        errbacks = body.options.get("link_error") or []
        assert len(errbacks) == 1
        assert (
            errbacks[0].kwargs["imported_since_str"]
            == "2026-05-29T09:00:00+00:00"
        )
        assert (
            errbacks[0].kwargs["imported_until_str"]
            == "2026-05-29T10:00:00+00:00"
        )


class TestAmountVerificationChordErrorTail:
    """The chord errback dispatches the tail when the chord fails hard."""

    def test_dispatches_tail_and_reports_chord_error(self):
        from core.tasks.tasks_post_import import (
            amount_verification_chord_error_tail,
        )

        dispatched = []

        def fake_chain(*args):
            dispatched.extend(
                (getattr(s, "task", "") or "").rsplit(".", 1)[-1]
                for s in args
            )
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="tail-id")
            return m

        with patch(
            "core.tasks.tasks_post_import.chain", side_effect=fake_chain
        ):
            # Celery calls errbacks as (request, exc, traceback).
            result = amount_verification_chord_error_tail.run(
                MagicMock(id="body-request"),
                RuntimeError("child lost"),
                "traceback",
                reference_date_str="2026-05-29",
            )

        assert result["status"] == "tail_dispatched"
        assert result["reason"] == "amount_verification_chord_error"
        assert "child lost" in result["chord_error"]
        assert result["tail_task_id"] == "tail-id"
        assert dispatched == [
            "recover_self_counterparts",
            "compute_entity_rankings",
            "invalidate_browse_cache",
            "warm_analytics_cache",
            "trigger_check_all_subscriptions",
        ]

    def test_errback_dispatch_failure_does_not_raise(self):
        """If even the tail dispatch fails, the errback must not raise —
        Celery errbacks that raise produce noisy, unactionable tracebacks."""
        from core.tasks.tasks_post_import import (
            amount_verification_chord_error_tail,
        )

        with patch(
            "core.tasks.tasks_post_import.chain",
            side_effect=RuntimeError("broker still down"),
        ):
            result = amount_verification_chord_error_tail.run(
                MagicMock(id="body-request"),
                RuntimeError("child lost"),
                "traceback",
                reference_date_str="2026-05-29",
            )

        # @log_task_run(swallow_errors=True) converts it to an error result.
        assert result["status"] == "error"
        assert "broker still down" in result["error"]

    def test_errback_forwards_import_window(self):
        """T07a: the errback carries the import-time window to the tail
        dispatch, exactly as the chord body does."""
        from core.tasks.tasks_post_import import (
            amount_verification_chord_error_tail,
        )

        with patch(
            "core.tasks.tasks_post_import._dispatch_post_verification_tail",
            return_value="tail-id",
        ) as mock_dispatch:
            result = amount_verification_chord_error_tail.run(
                MagicMock(id="body-request"),
                RuntimeError("child lost"),
                "traceback",
                reference_date_str="2026-05-29",
                imported_since_str="2026-05-29T09:00:00+00:00",
                imported_until_str="2026-05-29T10:00:00+00:00",
            )

        assert result["status"] == "tail_dispatched"
        kwargs = mock_dispatch.call_args.kwargs
        assert kwargs["imported_since_str"] == "2026-05-29T09:00:00+00:00"
        assert kwargs["imported_until_str"] == "2026-05-29T10:00:00+00:00"

    def test_errback_forwards_tail_kind(self):
        """T07c: a failed hourly chord errback dispatches the hourly tail."""
        from core.tasks.tasks_post_import import (
            amount_verification_chord_error_tail,
        )

        with patch(
            "core.tasks.tasks_post_import._dispatch_post_verification_tail",
            return_value="tail-id",
        ) as mock_dispatch:
            result = amount_verification_chord_error_tail.run(
                MagicMock(id="body-request"),
                RuntimeError("child lost"),
                "traceback",
                reference_date_str="2026-05-29",
                tail_kind="hourly",
            )

        assert result["status"] == "tail_dispatched"
        assert mock_dispatch.call_args.kwargs["tail_kind"] == "hourly"


class TestFinalizeAmountVerification:
    """The chord body aggregates child results, invalidates caches, runs
    discovery, and dispatches the post-import continuation chain."""

    def test_runs_discovery_with_import_window(self):
        from core.tasks.tasks_post_import import finalize_amount_verification

        fake_discovery = {
            "afm_anomalies": 2,
            "kae_anomalies": 1,
            "total_anomalies": 3,
            "sample": [],
        }

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value=fake_discovery,
            ) as mock_discovery,
            patch(
                "core.tasks.tasks_post_import.chain"
            ) as mock_chain_cls,
        ):
            mock_chain_instance = MagicMock()
            mock_chain_instance.apply_async.return_value = MagicMock(id="c")
            mock_chain_cls.return_value = mock_chain_instance

            result = finalize_amount_verification.run(
                [{"verified": 1, "discrepancies": 0}],
                reference_date_str="2026-05-29",
            )

        assert result["status"] == "completed"
        assert result["totals"]["verified"] == 1
        assert result["discovery"] == fake_discovery
        mock_discovery.assert_called_once()
        kwargs = mock_discovery.call_args.kwargs
        assert kwargs["imported_since"].date() == date(2026, 5, 29)
        assert kwargs["imported_until"].date() == date(2026, 5, 30)

    def test_tail_kind_threaded_to_finalize_dispatch(self):
        """T07c: the chord body forwards tail_kind to the tail dispatch."""
        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ),
            patch(
                "core.tasks.tasks_post_import._dispatch_post_verification_tail",
                return_value="tail-id",
            ) as mock_dispatch,
        ):
            finalize_amount_verification.run(
                [], reference_date_str="2026-05-29", tail_kind="hourly"
            )

        assert mock_dispatch.call_args.kwargs["tail_kind"] == "hourly"

    def test_continuation_chain_contains_five_tasks_in_order(self):
        """After the chord, the remaining post-import tasks must run in order
        (recovery → rankings → invalidate → warm → notifications)."""
        from core.tasks.tasks_post_import import finalize_amount_verification

        captured_chain_args = []

        def fake_chain(*args):
            captured_chain_args.extend(args)
            m = MagicMock()
            m.apply_async.return_value = MagicMock(id="x")
            return m

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={"afm_anomalies": 0, "kae_anomalies": 0,
                              "total_anomalies": 0, "sample": []},
            ),
            patch(
                "core.tasks.tasks_post_import.chain",
                side_effect=fake_chain,
            ),
        ):
            finalize_amount_verification.run(
                [], reference_date_str="2026-05-29"
            )

        assert len(captured_chain_args) == 5

        def _name(sig):
            return (getattr(sig, "task", "") or "").rsplit(".", 1)[-1]

        assert [_name(s) for s in captured_chain_args] == [
            "recover_self_counterparts",
            "compute_entity_rankings",
            "invalidate_browse_cache",
            "warm_analytics_cache",
            "trigger_check_all_subscriptions",
        ]

    @staticmethod
    def _run(overrides, tail_kind="daily"):
        from core.tasks.tasks_post_import import finalize_amount_verification

        batch = {
            "verified": 0,
            "discrepancies": 0,
            "corrected": 0,
            "consistent": 0,
            "no_text": 0,
            "skipped": 0,
            "errors": 0,
        }
        batch.update(overrides)

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ),
            patch(
                "core.tasks.tasks_post_import.chain"
            ) as mock_chain_cls,
            patch(
                "core.services.response_cache_service."
                "ResponseCacheService.invalidate_prefix",
                return_value=3,
            ) as mock_invalidate,
        ):
            mock_chain_instance = MagicMock()
            mock_chain_instance.apply_async.return_value = MagicMock(id="c")
            mock_chain_cls.return_value = mock_chain_instance

            finalize_amount_verification.run(
                [batch],
                reference_date_str="2026-05-29",
                tail_kind=tail_kind,
            )

        return mock_invalidate

    def test_corrected_amounts_invalidate_analytics_caches(self):
        """A correction must drop the amount-dependent analytics caches."""
        mock_invalidate = self._run({"corrected": 1})

        prefixes = {c.args[0] for c in mock_invalidate.call_args_list}
        assert prefixes == {"top_", "da_top_pairs", "explore_orgs"}

    def test_flagged_amounts_invalidate_analytics_caches(self):
        """Writing the invalid-amount marker also changes the facet layer."""
        mock_invalidate = self._run({"flagged": 1})

        assert mock_invalidate.call_count == 3

    def test_discrepancies_invalidate_analytics_caches(self):
        """A detected discrepancy also drops the amount-dependent caches."""
        mock_invalidate = self._run({"discrepancies": 1})

        assert mock_invalidate.call_count == 3

    def test_no_invalidation_when_nothing_changed(self):
        mock_invalidate = self._run({})

        mock_invalidate.assert_not_called()

    def test_hourly_tail_does_not_invalidate_daily_window_caches(self):
        """The hourly tail only re-warms today, so it must not drop the
        weekly/monthly/yearly keys the nightly daily tail built — for any of
        the three counters that trigger daily invalidation."""
        for trigger in (
            {"corrected": 1},
            {"discrepancies": 1},
            {"flagged": 1},
        ):
            mock_invalidate = self._run(trigger, tail_kind="hourly")
            mock_invalidate.assert_not_called()

    def test_hourly_invalidation_skip_still_dispatches_the_tail(self):
        """Skipping the hourly invalidation must not skip the tail (it is the
        only place that re-warms today and triggers notifications)."""
        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ),
            patch(
                "core.tasks.tasks_post_import._dispatch_post_verification_tail",
                return_value="tail-id",
            ) as mock_dispatch,
        ):
            result = finalize_amount_verification.run(
                [{"corrected": 1}],
                reference_date_str="2026-05-29",
                tail_kind="hourly",
            )

        assert result["status"] == "completed"
        assert result["continuation_task_id"] == "tail-id"
        assert mock_dispatch.call_args.kwargs["tail_kind"] == "hourly"

    def test_discovery_failure_still_dispatches_the_tail(self):
        """Discovery is observability-only — its failure must not skip the
        post-import tail (nothing else queues it)."""
        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                side_effect=RuntimeError("db gone"),
            ),
            patch("core.tasks.tasks_post_import.chain") as mock_chain_cls,
        ):
            mock_chain_instance = MagicMock()
            mock_chain_instance.apply_async.return_value = MagicMock(
                id="tail-id"
            )
            mock_chain_cls.return_value = mock_chain_instance

            result = finalize_amount_verification.run(
                [], reference_date_str="2026-05-29"
            )

        assert result["status"] == "completed"
        assert result["discovery"]["status"] == "error"
        assert "db gone" in result["discovery"]["error"]
        assert result["continuation_task_id"] == "tail-id"
        mock_chain_cls.assert_called_once()

    def test_cache_invalidation_failure_still_dispatches_the_tail(self):
        """A Redis failure during post-correction invalidation must not skip
        discovery or the tail dispatch."""
        from core.tasks.tasks_post_import import finalize_amount_verification

        with (
            patch(
                "core.tasks.tasks_post_import._discover_non_monetary_values",
                return_value={
                    "afm_anomalies": 0,
                    "kae_anomalies": 0,
                    "total_anomalies": 0,
                    "sample": [],
                },
            ) as mock_discovery,
            patch("core.tasks.tasks_post_import.chain") as mock_chain_cls,
            patch(
                "core.services.response_cache_service."
                "ResponseCacheService.invalidate_prefix",
                side_effect=RuntimeError("redis down"),
            ),
        ):
            mock_chain_instance = MagicMock()
            mock_chain_instance.apply_async.return_value = MagicMock(
                id="tail-id"
            )
            mock_chain_cls.return_value = mock_chain_instance

            result = finalize_amount_verification.run(
                [{"corrected": 1}], reference_date_str="2026-05-29"
            )

        assert result["status"] == "completed"
        assert result["continuation_task_id"] == "tail-id"
        # Discovery still ran despite the invalidation failure before it.
        mock_discovery.assert_called_once()
        mock_chain_cls.assert_called_once()


# ---------------------------------------------------------------------------
# @log_task_run decorator
# ---------------------------------------------------------------------------

class TestTaskRunLogging:
    """The decorator gives every post-import task a start/finish line even
    though Celery's own lifecycle signals are disabled in this project."""

    def test_summarize_result_surfaces_counts(self):
        from core.tasks.tasks_post_import import _summarize_result

        summary = _summarize_result(
            {
                "status": "completed",
                "reference_date": "2026-09-10",
                "verification": {"verified": 3, "discrepancies": 1},
                "correction": {
                    "corrected": 2,
                    "results": [{"huge": "per-decision payload"}],
                },
                "discovery": {"total_anomalies": 5},
            }
        )

        assert "status=completed" in summary
        assert "reference_date=2026-09-10" in summary
        assert "verification.verified=3" in summary
        assert "correction.corrected=2" in summary
        assert "discovery.total_anomalies=5" in summary
        # The per-decision payload must never reach the log line.
        assert "results" not in summary

    def test_summarize_result_handles_non_dict(self):
        from core.tasks.tasks_post_import import _summarize_result

        assert _summarize_result(None) == "result=None"

    def test_decorator_passes_result_through_and_keeps_name(self):
        from core.tasks.tasks_post_import import log_task_run

        @log_task_run
        def sample(x):
            return {"status": "ok", "x": x}

        assert sample.__name__ == "sample"
        assert sample(7) == {"status": "ok", "x": 7}

    def test_decorator_reraises_and_keeps_name(self):
        import pytest

        from core.tasks.tasks_post_import import log_task_run

        @log_task_run
        def boom():
            raise ValueError("nope")

        assert boom.__name__ == "boom"
        with pytest.raises(ValueError, match="nope"):
            boom()

    def test_decorator_swallows_errors_when_requested(self):
        from core.tasks.tasks_post_import import log_task_run

        @log_task_run(swallow_errors=True)
        def boom():
            raise RuntimeError("db down")

        result = boom()

        assert result["status"] == "error"
        assert "db down" in result["error"]

    def test_decorator_supports_both_call_styles(self):
        """Bare and parenthesised usage must both return a callable wrapper."""
        from core.tasks.tasks_post_import import log_task_run

        @log_task_run
        def bare():
            return {"status": "ok"}

        @log_task_run(swallow_errors=True)
        def with_args():
            return {"status": "ok"}

        assert bare() == {"status": "ok"}
        assert with_args() == {"status": "ok"}

    def test_chain_task_swallows_internal_failure(self):
        """A hard failure inside a chain task must NOT stop the chain — it is
        logged and returned as an error status instead of raising."""
        from core.tasks.tasks_post_import import compute_entity_rankings

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("ANALYTICS_PRECALC_ENABLED"),
            ),
            patch(
                "core.tasks.tasks_post_import._calendar_windows",
                side_effect=RuntimeError("boom"),
            ),
        ):
            result = compute_entity_rankings(reference_date_str="2026-05-29")

        assert result["status"] == "error"
        assert "boom" in result["error"]

    def test_orchestrator_still_raises(self):
        """The orchestrator is not part of the chain, so its failures must
        surface normally rather than be swallowed."""
        import pytest

        from core.tasks.tasks_post_import import post_daily_import_orchestrator

        with (
            patch(
                "core.tasks.tasks_post_import.feature_flags.is_enabled",
                side_effect=_flag_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"),
            ),
            patch(
                "core.tasks.tasks_post_import.date",
            ) as mock_date,
        ):
            mock_date.fromisoformat.side_effect = ValueError("bad date")
            with pytest.raises(ValueError, match="bad date"):
                post_daily_import_orchestrator(
                    job_id=1, reference_date_str="not-a-date"
                )
