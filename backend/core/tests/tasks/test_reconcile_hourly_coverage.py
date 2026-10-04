"""
Task-level tests for ``reconcile_hourly_coverage_task`` (T11).

The task is a report-only daily safety net: gate on AUTO_HOURLY_IMPORT_ENABLED,
count our ``publish_date_day`` rows for yesterday, compare against the official
Diavgeia submission-date count, log INFO always and WARNING above tolerance, and
return a result dict.  It must never auto-repair or raise.
"""

import io
from datetime import datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from celery.schedules import crontab
from core.models.decisions import Decision
from core.tasks.tasks_auto_import import (
    RECONCILE_WARNING_TOLERANCE_PCT,
    reconcile_hourly_coverage_task,
)
from diavgeia_project.celery import app
from django.conf import settings
from django.utils import timezone
from loguru import logger

ATHENS = ZoneInfo(settings.TIME_ZONE)

FLAGS = "core.tasks.tasks_auto_import.feature_flags"
DECISION = "core.tasks.tasks_auto_import.Decision"
OFFICIAL = (
    "core.tasks.tasks_auto_import.DecisionFetchReconcileService"
    ".get_official_count_for_date"
)

BEAT_KEY = "reconcile-hourly-coverage"
TASK_NAME = "core.tasks.tasks_auto_import.reconcile_hourly_coverage_task"


@pytest.fixture
def loguru_capture():
    """Capture loguru output via an in-memory sink.

    loguru writes directly to stderr and bypasses pytest's caplog capture,
    so we attach our own sink to collect messages.
    """
    stream = io.StringIO()
    handler_id = logger.add(stream, format="{message}")
    yield stream
    logger.remove(handler_id)


def _athens_noon(day):
    """A timezone-aware datetime whose Athens calendar date is ``day``."""
    return datetime.combine(day, time(12, 0), tzinfo=ATHENS)


def _create_on(day, count):
    from conftest import DecisionFactory

    return DecisionFactory.create_batch(count, publish_timestamp=_athens_noon(day))


@pytest.mark.django_db
class TestReconcileHourlyCoverageTask:
    def test_flag_disabled_skips(self):
        with (
            patch(FLAGS) as mock_flags,
            patch(DECISION) as mock_decision,
            patch(OFFICIAL) as mock_official,
        ):
            mock_flags.is_enabled.return_value = False

            result = reconcile_hourly_coverage_task()

        assert result == {"status": "skipped", "reason": "feature_flag_disabled"}
        mock_decision.objects.filter.assert_not_called()
        mock_official.assert_not_called()

    def test_official_none_skips(self):
        with (
            patch(FLAGS) as mock_flags,
            patch(OFFICIAL, return_value=None),
        ):
            mock_flags.is_enabled.return_value = True

            result = reconcile_hourly_coverage_task()

        assert result == {"status": "skipped", "reason": "no_official_data"}

    def test_counts_match_no_warning(self, loguru_capture):
        yesterday = timezone.localdate() - timedelta(days=1)
        _create_on(yesterday, 5)

        with (
            patch(FLAGS) as mock_flags,
            patch(OFFICIAL, return_value=5),
        ):
            mock_flags.is_enabled.return_value = True

            result = reconcile_hourly_coverage_task()

        assert result["status"] == "completed"
        assert result["date"] == str(yesterday)
        assert result["our_count"] == 5
        assert result["official_count"] == 5
        assert result["difference"] == 0
        assert result["percentage_diff"] == 0

        output = loguru_capture.getvalue()
        assert "reconciliation" in output
        assert "drift" not in output

    def test_diff_above_tolerance_warns(self, loguru_capture):
        yesterday = timezone.localdate() - timedelta(days=1)
        _create_on(yesterday, 100)

        # official = our_count + 10% → |diff%| ≈ 9.1% > tolerance
        with (
            patch(FLAGS) as mock_flags,
            patch(OFFICIAL, return_value=111),
        ):
            mock_flags.is_enabled.return_value = True

            result = reconcile_hourly_coverage_task()

        assert result["status"] == "completed"
        assert abs(result["percentage_diff"]) > RECONCILE_WARNING_TOLERANCE_PCT
        assert "drift" in loguru_capture.getvalue()

    def test_uses_publish_date_day_yesterday(self):
        yesterday = timezone.localdate() - timedelta(days=1)
        today = timezone.localdate()
        day_before = yesterday - timedelta(days=1)

        _create_on(yesterday, 3)
        _create_on(today, 2)
        _create_on(day_before, 4)

        with (
            patch(FLAGS) as mock_flags,
            patch(OFFICIAL, return_value=3),
        ):
            mock_flags.is_enabled.return_value = True

            result = reconcile_hourly_coverage_task()

        # Only the 3 rows on yesterday count; today/day-before are decoys.
        assert result["our_count"] == 3
        assert Decision.objects.filter(publish_date_day=yesterday).count() == 3


def test_beat_entry_present():
    entry = app.conf.beat_schedule[BEAT_KEY]
    assert entry["task"] == TASK_NAME

    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    assert schedule._orig_hour == 1
    assert schedule._orig_minute == 0
    assert schedule.hour == {1}
    assert schedule.minute == {0}


def test_task_is_registered():
    assert TASK_NAME in app.tasks
