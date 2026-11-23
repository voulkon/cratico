"""
Step 4 cache tests for ``organization_top_counterparts_api``.

The endpoint's cache key must include the URL path ``organization_uid``;
otherwise one organization's counterparts are served for another.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from django.urls import reverse

from core.schemas.financial.organization_finance import (
    CounterpartPage,
    CounterpartResult,
)
from core.services.response_cache_service import response_cache

_SERVICE_PATH = (
    "api.views.organization_entity_relationships.summary_amounts."
    "financial_service.get_top_counterparts_for_organization"
)


@pytest.fixture(autouse=True)
def _clear_counterparts_cache():
    """Isolate the endpoint's cache entries across tests."""
    response_cache.invalidate_prefix("top_org_counterparts")
    yield
    response_cache.invalidate_prefix("top_org_counterparts")


def _url(organization):
    return reverse("organization_top_counterparts", args=[organization.uid])


def _params(**extra):
    params = {
        "start_date": "2024-01-01T00:00:00Z",
        "end_date": "2024-12-31T00:00:00Z",
        "limit": "5",
        "offset": "0",
    }
    params.update(extra)
    return params


def _page(afm, name="Vendor", total="100.00"):
    return CounterpartPage(
        results=[
            CounterpartResult(
                entity_afm=afm,
                entity_name=name,
                entity_type="company",
                total_amount=total,
                decision_count=1,
            )
        ],
        total_count=1,
        has_more=False,
    )


@pytest.mark.django_db
class TestOrganizationTopCounterpartsCache:
    @patch(_SERVICE_PATH)
    def test_identical_org_and_filters_hit_cache(
        self, mock_service, authenticated_client, organization
    ):
        mock_service.return_value = _page("111111111")

        first = authenticated_client.get(_url(organization), _params())
        second = authenticated_client.get(_url(organization), _params())

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json() == second.json()
        assert mock_service.call_count == 1

    @patch(_SERVICE_PATH)
    def test_different_organization_misses_cache(
        self, mock_service, authenticated_client, organization
    ):
        from conftest import OrganizationFactory

        other = OrganizationFactory()

        def _side_effect(organization, **kwargs):
            return _page(f"AFM{organization.uid}")

        mock_service.side_effect = _side_effect

        first = authenticated_client.get(_url(organization), _params())
        cached = authenticated_client.get(_url(organization), _params())
        different = authenticated_client.get(_url(other), _params())

        assert first.status_code == 200
        assert cached.status_code == 200
        assert different.status_code == 200
        assert mock_service.call_count == 2
        assert first.json()["results"][0]["entity_afm"] == f"AFM{organization.uid}"
        assert different.json()["results"][0]["entity_afm"] == f"AFM{other.uid}"

    @patch(_SERVICE_PATH)
    def test_different_filters_miss_cache(
        self, mock_service, authenticated_client, organization
    ):
        mock_service.side_effect = lambda organization, **kwargs: _page(
            f"LIMIT{kwargs['limit']}"
        )

        authenticated_client.get(_url(organization), _params(limit="5"))
        authenticated_client.get(_url(organization), _params(limit="10"))

        assert mock_service.call_count == 2

    def test_new_decision_appears_after_ttl(
        self, authenticated_client, organization, decision_type
    ):
        from conftest import (
            AFMEntityFactory,
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            DecisionFactory,
        )

        def add_counterpart(afm, amount):
            entity = AFMEntityFactory(afm=afm)
            decision = DecisionFactory(
                organization=organization,
                decision_type=decision_type,
                issue_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            )
            relationship = DecisionEntityRelationshipFactory(
                decision=decision, entity=entity, role="grantee"
            )
            DecisionAmountFieldFactory(
                decision=decision,
                associated_relationship=relationship,
                amount=amount,
                parent_key_path="sponsor[0].expenseAmount",
            )

        add_counterpart("111111111", 100)

        params = _params(limit="10")
        first = authenticated_client.get(_url(organization), params)
        assert first.json()["pagination"]["total_count"] == 1

        add_counterpart("222222222", 200)

        # Still cached: the new counterpart is not visible yet.
        cached = authenticated_client.get(_url(organization), params)
        assert cached.json()["pagination"]["total_count"] == 1

        # Simulate TTL expiry.
        response_cache.invalidate_prefix("top_org_counterparts")

        refreshed = authenticated_client.get(_url(organization), params)
        assert refreshed.json()["pagination"]["total_count"] == 2
