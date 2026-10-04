"""Unit tests for the SyncStatus hourly watermark (T02)."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.constants.decision_import_constants import HOURLY_IMPORT_SYNC_TYPE
from core.models.sync_status import SyncStatus


@pytest.mark.django_db
def test_get_last_hourly_sync_missing_defaults_to_one_hour():
    """No decisions_hourly row -> the watermark defaults to ~1 hour ago,
    never the 30-day default of the decisions variant."""
    before = timezone.now()
    result = SyncStatus.get_last_hourly_sync()
    after = timezone.now()

    assert before - timedelta(hours=1) - timedelta(seconds=5) <= result
    assert result <= after - timedelta(hours=1) + timedelta(seconds=5)
    # And definitely not ~30 days in the past
    assert result > timezone.now() - timedelta(hours=2)


@pytest.mark.django_db
def test_get_last_hourly_sync_returns_stored():
    """A stored decisions_hourly row is returned verbatim."""
    stored = timezone.now() - timedelta(minutes=90)
    SyncStatus.objects.create(
        sync_type=HOURLY_IMPORT_SYNC_TYPE,
        last_sync_timestamp=stored,
        last_sync_date=stored.date(),
    )
    assert SyncStatus.get_last_hourly_sync() == stored


@pytest.mark.django_db
def test_update_hourly_sync_creates_row():
    """update_hourly_sync creates the decisions_hourly row; a second call
    overwrites the watermark and accumulates total_processed while
    round-tripping status/error_message."""
    ts1 = timezone.now() - timedelta(hours=2)
    obj = SyncStatus.update_hourly_sync(ts1, processed_count=10)
    assert obj.sync_type == HOURLY_IMPORT_SYNC_TYPE
    assert obj.last_sync_timestamp == ts1
    assert obj.total_processed == 10
    assert obj.last_run_status == "completed"
    assert obj.error_message == ""

    ts2 = timezone.now() - timedelta(hours=1)
    obj = SyncStatus.update_hourly_sync(
        ts2, processed_count=5, status="failed", error="boom"
    )
    assert SyncStatus.objects.filter(sync_type=HOURLY_IMPORT_SYNC_TYPE).count() == 1
    assert obj.last_sync_timestamp == ts2
    assert obj.total_processed == 15
    assert obj.last_run_status == "failed"
    assert obj.error_message == "boom"


@pytest.mark.django_db
def test_hourly_row_independent_of_decisions_row():
    """A decisions row never satisfies the hourly watermark and vice versa."""
    decisions_ts = timezone.now() - timedelta(days=30)
    SyncStatus.objects.update_or_create(
        sync_type="decisions",
        defaults={
            "last_sync_timestamp": decisions_ts,
            "last_sync_date": decisions_ts.date(),
        },
    )

    hourly_default = SyncStatus.get_last_hourly_sync()
    # decisions row (30 days old) must not leak into the hourly watermark
    assert hourly_default > timezone.now() - timedelta(hours=2)

    hourly_ts = timezone.now() - timedelta(minutes=30)
    SyncStatus.update_hourly_sync(hourly_ts, processed_count=1)

    # the decisions watermark is unaffected by the hourly row
    assert SyncStatus.get_last_decisions_sync() == decisions_ts
    assert SyncStatus.get_last_hourly_sync() == hourly_ts
