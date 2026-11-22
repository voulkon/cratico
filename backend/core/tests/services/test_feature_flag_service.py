import pytest
from django.core.cache import cache
from django.utils import timezone

from core.models.feature_flags import FeatureFlag
from core.services.feature_flag_service import FeatureFlagService

pytestmark = [pytest.mark.django_db, pytest.mark.fast]

INTEGER_FLAG = "SEARCH_DEBOUNCE_MS"
INTEGER_DEFAULT = 300


@pytest.fixture(autouse=True)
def clear_flag_cache():
    cache.delete(feature_flag_key(INTEGER_FLAG))
    yield
    cache.delete(feature_flag_key(INTEGER_FLAG))


def feature_flag_key(key: str) -> str:
    return f"feature_flag:{key}"


def _blank_integer_flag(key: str = INTEGER_FLAG) -> FeatureFlag:
    return FeatureFlag.objects.create(
        key=key,
        name="Search Debounce",
        description="",
        value_type="integer",
        string_value="",
        last_checked_at=timezone.now(),
    )


def test_blank_integer_flag_returns_default_and_caches_it(
    django_assert_num_queries,
):
    _blank_integer_flag()
    service = FeatureFlagService()

    assert service.get_value(INTEGER_FLAG) == INTEGER_DEFAULT

    with django_assert_num_queries(0):
        assert service.get_value(INTEGER_FLAG) == INTEGER_DEFAULT


def test_populated_integer_flag_value_is_returned_and_cached(
    django_assert_num_queries,
):
    flag = _blank_integer_flag()
    flag.string_value = "450"
    flag.save(update_fields=["string_value"])
    service = FeatureFlagService()

    assert service.get_value(INTEGER_FLAG) == 450

    with django_assert_num_queries(0):
        assert service.get_value(INTEGER_FLAG) == 450
