"""
Tests for notification metadata endpoints.

These endpoints provide schema and available values for building
subscription UIs.
"""

import pytest
from rest_framework import status

pytestmark = pytest.mark.django_db


class TestSubscriptionMetadataEndpoint:
    """Test /api/notifications/meta/metadata/ endpoint."""

    def test_metadata_returns_subscription_types(self, authenticated_client):
        """Should return all 6 subscription types with details."""
        response = authenticated_client.get("/api/notifications/meta/metadata/")

        assert response.status_code == status.HTTP_200_OK

        data = response.data
        assert "subscription_types" in data
        assert "filter_parameters" in data
        assert "check_frequency_options" in data
        assert "endpoints" in data

        # Verify all 6 types are present
        types = {t["type"] for t in data["subscription_types"]}
        assert types == {
            "organization",
            "entity",
            "relationship",
            "person",
            "signer",
            "filter",
        }

    def test_metadata_includes_filter_parameters(self, authenticated_client):
        """Should include details about filter parameters."""
        response = authenticated_client.get("/api/notifications/meta/metadata/")

        filter_params = response.data["filter_parameters"]

        assert "keywords" in filter_params
        assert "amount_min" in filter_params
        assert "amount_max" in filter_params
        assert "decision_types" in filter_params

        # Check structure
        assert filter_params["keywords"]["type"] == "array"
        assert "validation" in filter_params["keywords"]
        assert "example" in filter_params["keywords"]

    def test_metadata_includes_check_frequency_options(self, authenticated_client):
        """Should include check frequency options."""
        response = authenticated_client.get("/api/notifications/meta/metadata/")

        options = response.data["check_frequency_options"]

        values = {opt["value"] for opt in options}
        assert values == {"daily", "weekly", "manual"}

    def test_metadata_includes_endpoint_urls(self, authenticated_client):
        """Should include relevant endpoint URLs."""
        response = authenticated_client.get("/api/notifications/meta/metadata/")

        endpoints = response.data["endpoints"]

        assert "search_organizations" in endpoints
        assert "decision_types" in endpoints
        assert "create_subscription" in endpoints

    def test_metadata_requires_authentication(self, api_client):
        """Should require authentication."""
        response = api_client.get("/api/notifications/meta/metadata/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestDecisionTypesListEndpoint:
    """Test /api/notifications/meta/metadata/decision-types/ endpoint."""

    def test_returns_decision_types(self, authenticated_client, decision_type):
        """Should return list of decision types."""
        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/"
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.data
        assert "count" in data
        assert "total_count" in data
        assert "decision_types" in data

        # Should have at least the fixture decision type
        assert data["count"] >= 1

    def test_decision_type_structure(self, authenticated_client, decision_type):
        """Should return properly structured decision type objects."""
        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/"
        )

        types = response.data["decision_types"]

        # Find our test decision type
        test_type = next((t for t in types if t["uid"] == decision_type.uid), None)

        assert test_type is not None
        assert "uid" in test_type
        assert "label" in test_type
        assert "allowed_in_decisions" in test_type
        assert "has_children" in test_type

    def test_search_parameter(self, authenticated_client):
        """Should filter by search term."""
        from conftest import DecisionTypeFactory

        # Create some test decision types
        DecisionTypeFactory(uid="TEST1", label="Προμήθειες υλικών")
        DecisionTypeFactory(uid="TEST2", label="Διορισμοί")

        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/?search=Προμήθ"
        )

        types = response.data["decision_types"]
        labels = [t["label"] for t in types]

        # Should contain the matching type
        assert any("Προμήθ" in label for label in labels)

    def test_limit_parameter(self, authenticated_client):
        """Should respect limit parameter."""
        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/?limit=5"
        )

        types = response.data["decision_types"]
        assert len(types) <= 5

    def test_allowed_only_parameter(self, authenticated_client):
        """Should filter by allowed_in_decisions."""
        from conftest import DecisionTypeFactory

        # Create allowed and not-allowed types
        DecisionTypeFactory(uid="ALLOWED", allowed_in_decisions=True)
        DecisionTypeFactory(uid="NOTALLOWED", allowed_in_decisions=False)

        # Default should be allowed_only=true
        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/"
        )

        types = response.data["decision_types"]
        uids = [t["uid"] for t in types]

        assert "ALLOWED" in uids
        assert "NOTALLOWED" not in uids

        # Explicitly request all types
        response = authenticated_client.get(
            "/api/notifications/meta/metadata/decision-types/?allowed_only=false"
        )

        types = response.data["decision_types"]
        uids = [t["uid"] for t in types]

        assert "NOTALLOWED" in uids


class TestPopularDecisionTypesEndpoint:
    """Test /api/notifications/meta/metadata/popular-decision-types/ endpoint."""

    def test_returns_popular_types(self, authenticated_client, decision_type):
        """Should return decision types ordered by usage."""
        from conftest import DecisionFactory

        # Create some decisions with our test type
        for _ in range(5):
            DecisionFactory(decision_type=decision_type)

        response = authenticated_client.get(
            "/api/notifications/meta/metadata/popular-decision-types/"
        )

        assert response.status_code == status.HTTP_200_OK

        data = response.data
        assert "popular_types" in data
        assert "total_decisions" in data

    def test_popular_type_structure(self, authenticated_client, decision_type):
        """Should return properly structured popular type objects."""
        from conftest import DecisionFactory

        # Create decisions
        DecisionFactory(decision_type=decision_type)

        response = authenticated_client.get(
            "/api/notifications/meta/metadata/popular-decision-types/"
        )

        types = response.data["popular_types"]

        if types:  # May be empty if no decisions exist
            first_type = types[0]
            assert "uid" in first_type
            assert "label" in first_type
            assert "decision_count" in first_type
            assert "percentage" in first_type

    def test_ordering_by_popularity(self, authenticated_client):
        """Should order types by decision count (descending)."""
        from conftest import DecisionFactory, DecisionTypeFactory

        # Create types with different usage counts
        type1 = DecisionTypeFactory(uid="POPULAR")
        type2 = DecisionTypeFactory(uid="RARE")

        # Create more decisions for type1
        for _ in range(10):
            DecisionFactory(decision_type=type1)

        for _ in range(2):
            DecisionFactory(decision_type=type2)

        response = authenticated_client.get(
            "/api/notifications/meta/metadata/popular-decision-types/?limit=10"
        )

        types = response.data["popular_types"]

        if len(types) >= 2:
            # First should have more decisions than second
            assert types[0]["decision_count"] >= types[1]["decision_count"]

    def test_limit_parameter(self, authenticated_client):
        """Should respect limit parameter."""
        from conftest import DecisionFactory, DecisionTypeFactory

        # Create several types with decisions
        for i in range(15):
            dt = DecisionTypeFactory(uid=f"TYPE{i}")
            DecisionFactory(decision_type=dt)

        response = authenticated_client.get(
            "/api/notifications/meta/metadata/popular-decision-types/?limit=5"
        )

        types = response.data["popular_types"]
        assert len(types) <= 5
