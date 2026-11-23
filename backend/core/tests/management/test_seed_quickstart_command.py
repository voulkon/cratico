from datetime import date
from io import StringIO
from types import SimpleNamespace

import pytest
from django.core.management import call_command

from core.management.commands import seed_quickstart
from core.models.import_jobs import ImportJobType

pytestmark = [pytest.mark.django_db, pytest.mark.fast]

TODAY = date(2026, 11, 21)


class _FakeDiscovery:
    def __init__(self):
        self.rows = []
        self.discovery_called = False

    def get_all_official_daily_counts(self):
        self.discovery_called = True
        return list(self.rows)


class _QueueRecorder:
    calls = []

    def enqueue_job(self, **kwargs):
        type(self).calls.append(kwargs)
        return SimpleNamespace(id=7, status="FETCHING", refresh_from_db=lambda: None)


@pytest.fixture
def discovery(monkeypatch):
    fake = _FakeDiscovery()
    _QueueRecorder.calls = []
    monkeypatch.setattr(seed_quickstart, "DecisionFetchReconcileService", lambda: fake)
    monkeypatch.setattr(seed_quickstart, "ImportJobQueue", _QueueRecorder)
    monkeypatch.setattr(seed_quickstart, "enable_post_import_flags", lambda: [])
    monkeypatch.setattr(seed_quickstart.timezone, "localdate", lambda: TODAY)
    return fake


def test_picks_most_recent_completed_day_in_range(discovery):
    discovery.rows = [
        {"date": date(2026, 11, 21), "count": 495},
        {"date": date(2026, 11, 20), "count": 27287},
        {"date": date(2026, 11, 15), "count": 569},
        {"date": date(2026, 11, 14), "count": 421},
    ]

    call_command("seed_quickstart", stdout=StringIO())

    assert len(_QueueRecorder.calls) == 1
    kwargs = _QueueRecorder.calls[0]
    assert kwargs["target_date"] == date(2026, 11, 15)
    assert kwargs["import_type"] == ImportJobType.DAILY


def test_skips_today(discovery):
    discovery.rows = [
        {"date": TODAY, "count": 200},
        {"date": date(2026, 11, 14), "count": 421},
    ]

    call_command("seed_quickstart", stdout=StringIO())

    assert _QueueRecorder.calls[0]["target_date"] == date(2026, 11, 14)


def test_above_range_uses_smallest_above(discovery):
    discovery.rows = [
        {"date": date(2026, 11, 20), "count": 9000},
        {"date": date(2026, 11, 15), "count": 2000},
        {"date": date(2026, 11, 14), "count": 1500},
    ]

    call_command("seed_quickstart", stdout=StringIO())

    assert _QueueRecorder.calls[0]["target_date"] == date(2026, 11, 14)


def test_explicit_date_skips_discovery(discovery):
    discovery.rows = [{"date": date(2026, 11, 15), "count": 569}]

    call_command("seed_quickstart", "--date", "2026-11-15", stdout=StringIO())

    assert not discovery.discovery_called
    assert _QueueRecorder.calls[0]["target_date"] == date(2026, 11, 15)


def test_dry_run_does_not_enqueue(discovery):
    discovery.rows = [{"date": date(2026, 11, 15), "count": 569}]

    call_command("seed_quickstart", "--dry-run", stdout=StringIO())

    assert _QueueRecorder.calls == []


def test_falls_back_to_yesterday_without_official_counts(discovery):
    discovery.rows = []

    call_command("seed_quickstart", stdout=StringIO())

    assert _QueueRecorder.calls[0]["target_date"] == date(2026, 11, 20)
