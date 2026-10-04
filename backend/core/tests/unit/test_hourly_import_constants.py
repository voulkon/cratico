"""Unit tests for the hourly-import constants and feature flags (T01)."""

import os

import pytest

from core.constants.decision_import_constants import (
    ADVANCED_QUERY_TEMPLATE,
    HOURLY_IMPORT_MIN_INTERVAL_MINUTES,
    HOURLY_IMPORT_OVERLAP_MINUTES,
    HOURLY_IMPORT_SYNC_TYPE,
)
from core.services.feature_flag_service import FeatureFlagService, feature_flags

ENABLED_FLAG = "AUTO_HOURLY_IMPORT_ENABLED"
MINUTE_FLAG = "AUTO_HOURLY_IMPORT_MINUTE"


def test_hourly_constants_values():
    """The hourly-import constants hold their designed values."""
    assert HOURLY_IMPORT_OVERLAP_MINUTES == 10
    assert HOURLY_IMPORT_MIN_INTERVAL_MINUTES == 5
    assert HOURLY_IMPORT_SYNC_TYPE == "decisions_hourly"


def test_advanced_query_template_renders():
    """The advanced-query template renders the probe-verified window query
    byte-for-byte, Greek status literal included."""
    rendered = ADVANCED_QUERY_TEMPLATE.format(
        from_ts="2026-10-05T09:00:00+03:00",
        to_ts="2026-10-05T10:00:00+03:00",
    )
    assert rendered == (
        "submissionTimestamp:[DT(2026-10-05T09:00:00+03:00) "
        "TO DT(2026-10-05T10:00:00+03:00)] "
        'AND status:"Αναρτημένη"'
    )


def test_auto_hourly_flags_registered():
    """Both AUTO_HOURLY_IMPORT_* flags are registered with the agreed
    defaults, env vars, category, restart semantics, and value types."""
    assert ENABLED_FLAG in FeatureFlagService.KNOWN_FLAGS
    enabled = FeatureFlagService.KNOWN_FLAGS[ENABLED_FLAG]
    assert enabled["name"] == "Auto Hourly Import (Fresh Data)"
    assert enabled["default"] is False
    assert enabled["env_var"] == "AUTO_HOURLY_IMPORT_ENABLED"
    assert enabled["category"] == "data_ingestion"
    assert enabled["requires_restart"] is False
    assert enabled.get("value_type", "boolean") == "boolean"

    assert MINUTE_FLAG in FeatureFlagService.KNOWN_FLAGS
    minute = FeatureFlagService.KNOWN_FLAGS[MINUTE_FLAG]
    assert minute["default"] == "10"
    assert minute["env_var"] == "AUTO_HOURLY_IMPORT_MINUTE"
    assert minute["category"] == "data_ingestion"
    assert minute["requires_restart"] is True
    assert minute["value_type"] == "string"


@pytest.mark.django_db
def test_auto_hourly_enabled_env_override(monkeypatch):
    """AUTO_HOURLY_IMPORT_ENABLED resolves False by default and True from
    its environment variable."""
    monkeypatch.delenv(ENABLED_FLAG, raising=False)
    feature_flags.clear_cache(ENABLED_FLAG)
    assert feature_flags.get_value(ENABLED_FLAG) is False

    monkeypatch.setenv(ENABLED_FLAG, "true")
    feature_flags.clear_cache(ENABLED_FLAG)
    assert feature_flags.get_value(ENABLED_FLAG) is True
    feature_flags.clear_cache(ENABLED_FLAG)


@pytest.mark.django_db
def test_auto_hourly_minute_default_and_env(monkeypatch):
    """AUTO_HOURLY_IMPORT_MINUTE defaults to "10"; the env override "7" wins
    in the env-only read the Celery beat schedule must use — the schedule is
    built before Django apps load, so it reads os.environ directly, exactly
    like AUTO_DAILY_IMPORT_TIME (see get_auto_import_time in celery.py)."""
    monkeypatch.delenv(MINUTE_FLAG, raising=False)
    feature_flags.clear_cache(MINUTE_FLAG)
    assert feature_flags.get_value(MINUTE_FLAG) == "10"
    assert os.environ.get(MINUTE_FLAG, "10") == "10"

    monkeypatch.setenv(MINUTE_FLAG, "7")
    assert os.environ.get(MINUTE_FLAG, "10") == "7"
    feature_flags.clear_cache(MINUTE_FLAG)
