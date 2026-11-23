"""
Step 4 cache tests: entity aggregates on the unified decisions endpoint.

Covers:
  - source=entity is cacheable for date_range / decision_types only
  - cache keys include entity identity and the aggregate facet inputs
  - entity aggregates use a short 5-minute TTL
  - entity requests never take the temporal defer-on-miss (202) path
  - a new decision appears once the cache entry expires
  - the temporal warmup writes the exact key the view looks up
"""

from datetime import date, datetime, timezone
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.test import RequestFactory, override_settings

from api.redis_keys import API_CACHE_EXPIRE_CURRENT, UNIFIED_AGGREGATE_CACHE_PARAMS
from api.views.decisions_unified import (
    _should_cache_unified,
    _should_defer_unified,
    _unified_ttl,
    decisions_unified_api,
)
from core.services.response_cache_service import response_cache

_LOCMEM_CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unified-entity-aggregate-cache-tests",
    }
}


@pytest.fixture(autouse=True)
def _use_locmem_cache():
    """Keep cache assertions deterministic and independent of Redis."""
    with override_settings(CACHES=_LOCMEM_CACHES):
        cache.clear()
        yield
        cache.clear()


def _entity_request(organization, view_name, **extra):
    params = {
        "source": "entity",
        "entity_type": "organization",
        "entity_id": organization.uid,
        "view": view_name,
    }
    params.update(extra)
    return RequestFactory().get("/api/decisions/unified/", params)


def _expected_unified_key(view_name, entity_id, **extra):
    params = {
        "source": "entity",
        "view": view_name,
        "entity_type": "organization",
        "entity_id": entity_id,
    }
    params.update(extra)
    return response_cache.build_key(
        "unified",
        **{name: params.get(name, "") for name in UNIFIED_AGGREGATE_CACHE_PARAMS},
    )


@pytest.mark.django_db
class TestUnifiedAggregateCachePolicy:
    def test_entity_aggregates_are_cacheable(self, organization):
        assert _should_cache_unified(_entity_request(organization, "date_range"))
        assert _should_cache_unified(_entity_request(organization, "decision_types"))

    def test_entity_non_aggregates_are_not_cacheable(self, organization):
        assert not _should_cache_unified(_entity_request(organization, "decisions"))
        assert not _should_cache_unified(_entity_request(organization, "statistics"))

    def test_temporal_policy_unchanged(self, organization):
        for view_name in ("date_range", "statistics", "decision_types"):
            request = _entity_request(organization, view_name, source="temporal")
            assert _should_cache_unified(request)

    def test_entity_aggregates_use_five_minute_ttl(self, organization):
        assert _unified_ttl(_entity_request(organization, "date_range")) == (
            API_CACHE_EXPIRE_CURRENT
        )

    def test_temporal_keeps_smart_ttl(self, organization):
        request = _entity_request(organization, "date_range", source="temporal")
        assert _unified_ttl(request) is None

    def test_only_temporal_requests_defer(self, organization):
        assert (
            _should_defer_unified(_entity_request(organization, "date_range")) is False
        )
        request = _entity_request(organization, "date_range", source="temporal")
        assert _should_defer_unified(request) is True


@pytest.mark.django_db
class TestUnifiedEntityAggregateCaching:
    def test_entity_date_range_hits_cache(self, organization, decision_type):
        from conftest import DecisionFactory

        DecisionFactory(organization=organization, decision_type=decision_type)

        import api.views.decisions_unified as unified

        with patch.object(
            unified, "compute_date_range", wraps=unified.compute_date_range
        ) as compute_spy:
            first = decisions_unified_api(_entity_request(organization, "date_range"))
            second = decisions_unified_api(_entity_request(organization, "date_range"))

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.data == second.data
        assert compute_spy.call_count == 1

    def test_cache_key_separates_organizations(self, organization, decision_type):
        from conftest import DecisionFactory, OrganizationFactory

        other = OrganizationFactory()
        DecisionFactory(organization=organization, decision_type=decision_type)
        DecisionFactory(organization=other, decision_type=decision_type)

        import api.views.decisions_unified as unified

        with patch.object(
            unified, "compute_date_range", wraps=unified.compute_date_range
        ) as compute_spy:
            decisions_unified_api(_entity_request(organization, "date_range"))
            decisions_unified_api(_entity_request(organization, "date_range"))
            decisions_unified_api(_entity_request(other, "date_range"))

        assert compute_spy.call_count == 2

    def test_cache_key_includes_aggregate_filters(self, organization, decision_type):
        from conftest import DecisionFactory

        DecisionFactory(organization=organization, decision_type=decision_type)

        import api.views.decisions_unified as unified

        with patch.object(
            unified, "compute_date_range", wraps=unified.compute_date_range
        ) as compute_spy:
            decisions_unified_api(_entity_request(organization, "date_range"))
            decisions_unified_api(
                _entity_request(
                    organization, "date_range", direct_assignments_only="true"
                )
            )

        assert compute_spy.call_count == 2

    def test_new_decision_appears_after_ttl(self, organization, decision_type):
        from conftest import DecisionFactory

        def add_decision(ada):
            DecisionFactory(
                ada=ada,
                organization=organization,
                decision_type=decision_type,
                issue_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            )

        add_decision("CACHE_1")

        first = decisions_unified_api(_entity_request(organization, "date_range"))
        assert first.data["summary"]["total_decisions"] == 1

        add_decision("CACHE_2")

        # Still served from cache: the second decision is not visible yet.
        cached = decisions_unified_api(_entity_request(organization, "date_range"))
        assert cached.data["summary"]["total_decisions"] == 1

        # Simulate TTL expiry.
        cache.delete(_expected_unified_key("date_range", organization.uid))

        add_decision("CACHE_3")
        refreshed = decisions_unified_api(_entity_request(organization, "date_range"))
        assert refreshed.data["summary"]["total_decisions"] == 3

    def test_decision_types_are_cached(self, organization, decision_type):
        from conftest import DecisionFactory

        DecisionFactory(organization=organization, decision_type=decision_type)

        import api.views.decisions_unified as unified

        with patch.object(
            unified,
            "aggregate_decision_types",
            wraps=unified.aggregate_decision_types,
        ) as compute_spy:
            first = decisions_unified_api(
                _entity_request(organization, "decision_types")
            )
            second = decisions_unified_api(
                _entity_request(organization, "decision_types")
            )

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.data == second.data
        assert compute_spy.call_count == 1


@pytest.mark.django_db
def test_temporal_warmup_writes_the_key_the_view_reads():
    """warm_unified_window and @cached_view must build identical keys."""
    from core.services.analytics_precalc.unified import warm_unified_window

    warm_unified_window("2024-01-01", "2024-12-31", date(2024, 12, 31))

    request = RequestFactory().get(
        "/api/decisions/unified/",
        {
            "source": "temporal",
            "view": "date_range",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
        },
    )
    expected_key = response_cache.build_key(
        "unified",
        **{name: request.GET.get(name, "") for name in UNIFIED_AGGREGATE_CACHE_PARAMS},
    )

    assert response_cache.get(expected_key) is not None
