"""
Executable form of the auto-import flag matrix (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §3).

Three flags decide what happens after each import:
  D = AUTO_DAILY_IMPORT_ENABLED
  H = AUTO_HOURLY_IMPORT_ENABLED
  O = POST_IMPORT_ORCHESTRATOR_ENABLED

Every combination is exercised here:
  * ``auto_daily_import_task`` enqueues a DAILY job for yesterday iff D is on.
  * ``auto_hourly_import_task`` enqueues an HOURLY job for today iff H is on
    (subject to the too-soon guard).
  * both orchestrators dispatch verification iff O is on.

Rows 3 and 7 (an AUTO import on, orchestrator off) are the silent-failure
states: data arrives but nothing verifies it, warms the cache, or notifies.
The orchestrator must log a warning at the skip so those rows are observable
(§5.4).

The email path additionally needs POST_IMPORT_NOTIFICATIONS_ENABLED; the last
test parametrizes it together with POST_IMPORT_AMOUNT_VERIFICATION_ENABLED so
the "email needs all three flags" rule of §2 is pinned.
"""

import io
from datetime import date, timedelta
from itertools import product
from unittest.mock import MagicMock, patch

import pytest
from core.constants.decision_import_constants import HOURLY_IMPORT_SYNC_TYPE
from core.models.import_jobs import ImportJobType
from core.models.sync_status import SyncStatus
from core.services.feature_flag_service import feature_flags
from core.tasks.tasks_auto_import import (
    auto_daily_import_task,
    auto_hourly_import_task,
)
from core.tasks.tasks_post_import import (
    post_daily_import_orchestrator,
    post_hourly_import_orchestrator,
    trigger_check_all_subscriptions,
    verify_high_value_amounts,
)
from django.utils import timezone
from loguru import logger

AUTO_DAILY = "AUTO_DAILY_IMPORT_ENABLED"
AUTO_HOURLY = "AUTO_HOURLY_IMPORT_ENABLED"
ORCHESTRATOR = "POST_IMPORT_ORCHESTRATOR_ENABLED"
AMOUNT_VERIFICATION = "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"
NOTIFICATIONS = "POST_IMPORT_NOTIFICATIONS_ENABLED"

QUEUE = "core.tasks.tasks_auto_import.ImportJobQueue"

TAIL_TASKS = [
    "compute_entity_rankings",
    "invalidate_browse_cache",
    "warm_analytics_cache",
    "trigger_check_all_subscriptions",
]

HOURLY_KWARGS = {
    "imported_since_str": "2026-05-29T09:00:00+00:00",
    "imported_until_str": "2026-05-29T10:00:00+00:00",
}


def _flag_values(**overrides):
    """All gate flags off unless the test turns one on."""
    values = {
        AUTO_DAILY: False,
        AUTO_HOURLY: False,
        ORCHESTRATOR: False,
        AMOUNT_VERIFICATION: False,
        NOTIFICATIONS: False,
    }
    values.update(overrides)
    return values


def _is_enabled(values):
    return lambda name: values.get(name, False)


@pytest.fixture
def loguru_capture():
    """Capture loguru output (it bypasses pytest's caplog)."""
    stream = io.StringIO()
    handler_id = logger.add(stream, format="{message}")
    yield stream
    logger.remove(handler_id)


def _seed_hourly_watermark():
    """A watermark old enough to pass the too-soon guard (default 5 min)."""
    return SyncStatus.objects.create(
        sync_type=HOURLY_IMPORT_SYNC_TYPE,
        last_sync_timestamp=timezone.now() - timedelta(minutes=70),
        last_sync_date=(timezone.now() - timedelta(minutes=70)).date(),
        last_run_status="completed",
    )


def _recording_chain(dispatched):
    """A fake ``chain()`` that records the task names it was given."""

    def _name(sig):
        return (getattr(sig, "task", "") or "").rsplit(".", 1)[-1]

    def fake_chain(*args):
        dispatched.extend(_name(s) for s in args)
        mock = MagicMock()
        mock.apply_async.return_value = MagicMock(id="tail-id")
        return mock

    return fake_chain


# ---------------------------------------------------------------------------
# §5.1 / §5.4 — D × H × O
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "auto_daily,auto_hourly,orchestrator",
    list(product([False, True], repeat=3)),
    ids=lambda value: "on" if value else "off",
)
@pytest.mark.django_db
class TestFlagMatrix:
    def test_daily_task_gated_by_auto_daily(self, auto_daily, auto_hourly, orchestrator):
        values = _flag_values(
            **{
                AUTO_DAILY: auto_daily,
                AUTO_HOURLY: auto_hourly,
                ORCHESTRATOR: orchestrator,
            }
        )

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch(QUEUE) as mock_queue,
        ):
            mock_queue.return_value.enqueue_job.return_value = MagicMock(
                id=11, status="PENDING"
            )
            result = auto_daily_import_task()

        if not auto_daily:
            assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
            mock_queue.assert_not_called()
            return

        assert result["status"] == "success"
        assert result["job_id"] == 11
        kwargs = mock_queue.return_value.enqueue_job.call_args.kwargs
        assert kwargs["target_date"] == date.today() - timedelta(days=1)
        assert kwargs["import_type"] == ImportJobType.DAILY

    def test_hourly_task_gated_by_auto_hourly(
        self, auto_daily, auto_hourly, orchestrator
    ):
        _seed_hourly_watermark()
        values = _flag_values(
            **{
                AUTO_DAILY: auto_daily,
                AUTO_HOURLY: auto_hourly,
                ORCHESTRATOR: orchestrator,
            }
        )

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch(QUEUE) as mock_queue,
        ):
            mock_queue.return_value.enqueue_job.return_value = MagicMock(
                id=22, status="PENDING"
            )
            result = auto_hourly_import_task()

        if not auto_hourly:
            assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
            mock_queue.assert_not_called()
            return

        assert result["status"] == "success"
        assert result["job_id"] == 22
        kwargs = mock_queue.return_value.enqueue_job.call_args.kwargs
        assert kwargs["target_date"] == timezone.localdate()
        assert kwargs["import_type"] == ImportJobType.HOURLY

    def test_orchestrators_gated_by_orchestrator_flag(
        self, auto_daily, auto_hourly, orchestrator
    ):
        values = _flag_values(
            **{
                AUTO_DAILY: auto_daily,
                AUTO_HOURLY: auto_hourly,
                ORCHESTRATOR: orchestrator,
            }
        )

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch(
                "core.tasks.tasks_post_import.verify_high_value_amounts.si"
            ) as mock_si,
        ):
            mock_si.return_value.apply_async.return_value = MagicMock(id="verify-id")
            daily_result = post_daily_import_orchestrator(
                job_id=1, reference_date_str="2026-05-29"
            )
            hourly_result = post_hourly_import_orchestrator(
                job_id=2, reference_date_str="2026-05-29", **HOURLY_KWARGS
            )

        if not orchestrator:
            expected = {"status": "skipped", "reason": "feature_flag_disabled"}
            assert daily_result == expected
            assert hourly_result == expected
            mock_si.assert_not_called()
            return

        assert daily_result["status"] == "dispatched"
        assert hourly_result["status"] == "dispatched"
        assert mock_si.call_count == 2

    def test_silent_failure_rows_log_a_warning(
        self, auto_daily, auto_hourly, orchestrator, loguru_capture
    ):
        """Rows 3/7: an AUTO import runs while the orchestrator is off.

        Nothing verifies the data, so the skip must be observable in the log
        rather than an INFO line nobody watches (§5.4).
        """
        if orchestrator or not (auto_daily or auto_hourly):
            pytest.skip("only rows 3 and 7 are silent failure states")

        values = _flag_values(
            **{
                AUTO_DAILY: auto_daily,
                AUTO_HOURLY: auto_hourly,
                ORCHESTRATOR: orchestrator,
            }
        )

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch("core.tasks.tasks_post_import.verify_high_value_amounts.si"),
        ):
            post_daily_import_orchestrator(job_id=1, reference_date_str="2026-05-29")
            post_hourly_import_orchestrator(
                job_id=2, reference_date_str="2026-05-29", **HOURLY_KWARGS
            )

        logged = loguru_capture.getvalue()
        assert logged.count("POST_IMPORT_ORCHESTRATOR_ENABLED is disabled") == 2


# ---------------------------------------------------------------------------
# §5.1 — email path: AMOUNT_VERIFICATION × NOTIFICATIONS
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount_verification,notifications",
    list(product([False, True], repeat=2)),
    ids=lambda value: "on" if value else "off",
)
class TestEmailGate:
    def test_tail_runs_regardless_of_amount_verification(
        self, amount_verification, notifications
    ):
        """Turning verification off must not disable the tail — it only changes
        whether verification children run before it."""
        values = _flag_values(
            **{
                AMOUNT_VERIFICATION: amount_verification,
                NOTIFICATIONS: notifications,
            }
        )
        dispatched = []

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch(
                "core.tasks.tasks_post_import.chain",
                side_effect=_recording_chain(dispatched),
            ),
            patch(
                "core.services.amount_verification_service."
                "AmountVerificationService.get_high_value_candidates",
                return_value=[],
            ),
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
            verify_high_value_amounts(reference_date_str="2026-05-29")

        assert dispatched == TAIL_TASKS

    def test_email_dispatched_iff_notifications_flag(
        self, amount_verification, notifications
    ):
        """``trigger_check_all_subscriptions`` is the only door to email; it
        must fan out iff POST_IMPORT_NOTIFICATIONS_ENABLED is on."""
        values = _flag_values(
            **{
                AMOUNT_VERIFICATION: amount_verification,
                NOTIFICATIONS: notifications,
            }
        )

        with (
            patch.object(feature_flags, "is_enabled", side_effect=_is_enabled(values)),
            patch(
                "notifications.tasks.notification_tasks."
                "check_all_active_subscriptions.delay"
            ) as mock_delay,
        ):
            result = trigger_check_all_subscriptions(
                reference_date_str="2026-05-29"
            )

        if notifications:
            mock_delay.assert_called_once_with()
            assert result["status"] == "dispatched"
        else:
            mock_delay.assert_not_called()
            assert result == {
                "status": "skipped",
                "reason": "feature_flag_disabled",
            }
