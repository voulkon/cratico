from io import StringIO

import pytest
from django.core.cache import cache
from django.core.management import call_command

from core.models.feature_flags import FeatureFlag
from core.services.feature_flag_service import feature_flags

pytestmark = [pytest.mark.django_db, pytest.mark.fast]

INTEGER_FLAG = "SEARCH_DEBOUNCE_MS"
INTEGER_DEFAULT = 300


@pytest.fixture(autouse=True)
def clear_flag_cache():
    cache.delete(feature_flag_key(INTEGER_FLAG))
    yield
    cache.delete(feature_flag_key(INTEGER_FLAG))


@pytest.fixture
def only_integer_flag(monkeypatch):
    known_flags = feature_flags.KNOWN_FLAGS
    monkeypatch.setattr(
        feature_flags, "KNOWN_FLAGS", {INTEGER_FLAG: known_flags[INTEGER_FLAG]}
    )


def feature_flag_key(key: str) -> str:
    return f"feature_flag:{key}"


def _blank_integer_flag(key: str = INTEGER_FLAG) -> FeatureFlag:
    return FeatureFlag.objects.create(
        key=key,
        name="Search Debounce",
        description="",
        value_type="integer",
        string_value="",
    )


def test_backfills_blank_integer_flag(only_integer_flag):
    flag = _blank_integer_flag()
    assert flag.string_value == ""

    call_command("initialize_feature_flags", stdout=StringIO())

    flag.refresh_from_db()
    assert flag.value_type == "integer"
    assert flag.string_value == str(INTEGER_DEFAULT)


def test_creates_integer_flag_with_default_value(only_integer_flag):
    call_command("initialize_feature_flags", stdout=StringIO())

    flag = FeatureFlag.objects.get(key=INTEGER_FLAG)
    assert flag.value_type == "integer"
    assert flag.string_value == str(INTEGER_DEFAULT)


def test_dry_run_does_not_backfill(only_integer_flag):
    flag = _blank_integer_flag()

    call_command("initialize_feature_flags", "--dry-run", stdout=StringIO())

    flag.refresh_from_db()
    assert flag.string_value == ""
