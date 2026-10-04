"""Unit tests for the hourly-import Celery beat entry and minute helper (T10).

The beat entry ``auto-hourly-import`` fires every hour at a configurable minute
(default :10).  The minute is read from the environment at module import time
(the schedule is built before Django apps load), so these tests assert against
``get_auto_hourly_import_minute()`` rather than re-parsing the environment.
"""

import pytest
from celery.schedules import crontab
from diavgeia_project.celery import (
    app,
    auto_hourly_import_minute,
    get_auto_hourly_import_minute,
)

TASK_NAME = "core.tasks.tasks_auto_import.auto_hourly_import_task"


def test_beat_schedule_contains_hourly_import():
    """The beat entry references the registered task name and fires every hour
    at the minute returned by the helper."""
    entry = app.conf.beat_schedule["auto-hourly-import"]
    assert entry["task"] == TASK_NAME

    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    assert schedule._orig_minute == get_auto_hourly_import_minute()
    assert schedule.minute == {get_auto_hourly_import_minute()}
    assert schedule._orig_hour == "*"
    assert schedule.hour == set(range(24))


def test_hourly_task_is_registered():
    """The task referenced by beat resolves to a registered Celery task.

    Referencing an unregistered name would be silently dropped (see the
    ``daily-amount-correction`` comment in celery.py)."""
    assert TASK_NAME in app.tasks


def test_minute_helper_parses_env(monkeypatch):
    """A valid env override wins over the default."""
    monkeypatch.setenv("AUTO_HOURLY_IMPORT_MINUTE", "7")
    assert get_auto_hourly_import_minute() == 7


@pytest.mark.parametrize("garbage", ["abc", "", "1:2", "None"])
def test_minute_helper_falls_back_on_garbage(monkeypatch, garbage):
    """Unparseable values fall back to 10."""
    monkeypatch.setenv("AUTO_HOURLY_IMPORT_MINUTE", garbage)
    assert get_auto_hourly_import_minute() == 10


def test_minute_helper_default_when_unset(monkeypatch):
    """Absent env falls back to 10."""
    monkeypatch.delenv("AUTO_HOURLY_IMPORT_MINUTE", raising=False)
    assert get_auto_hourly_import_minute() == 10


def test_module_binding_matches_helper():
    """The module-level binding used by the beat schedule comes from the helper."""
    assert auto_hourly_import_minute == get_auto_hourly_import_minute()


def test_daily_beat_entries_unchanged():
    """Regression: the pre-existing daily entries are untouched."""
    schedule = app.conf.beat_schedule

    daily = schedule["auto-daily-import"]
    assert daily["task"] == "core.tasks.tasks_auto_import.auto_daily_import_task"
    assert isinstance(daily["schedule"], crontab)

    correction = schedule["daily-amount-correction"]
    assert correction["task"] == "amount_correction.daily"
    correction_schedule = correction["schedule"]
    assert isinstance(correction_schedule, crontab)
    assert correction_schedule._orig_hour == 3
    assert correction_schedule._orig_minute == 30
