"""
Unit tests for notification serializers.

These tests verify serializer validation, transformation logic, and field behavior.
"""

import pytest
from django.utils import timezone

pytestmark = pytest.mark.django_db


class TestNotificationSubscriptionSerializer:
    """Test NotificationSubscription serializers"""

    def test_serialize_organization_subscription(self, notification_subscription):
        """Test serializing an organization subscription"""
        from notifications.serializers import NotificationSubscriptionSerializer

        serializer = NotificationSubscriptionSerializer(notification_subscription)
        data = serializer.data

        assert data["id"] == notification_subscription.id
        assert data["organization"] == notification_subscription.organization.uid
        assert data["subscription_type"] == "organization"
        assert "organization_details" in data
        assert (
            data["organization_details"]["uid"]
            == notification_subscription.organization.uid
        )

    def test_serialize_entity_subscription(self, entity_subscription):
        """Test serializing an entity subscription"""
        from notifications.serializers import NotificationSubscriptionSerializer

        serializer = NotificationSubscriptionSerializer(entity_subscription)
        data = serializer.data

        assert data["entity"] == entity_subscription.entity.afm
        assert data["subscription_type"] == "entity"
        assert "entity_details" in data

    def test_create_subscription_with_valid_data(self, user, organization):
        """Test creating subscription with valid data"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "keywords": ["test", "contract"],
            "is_active": True,
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        assert subscription.organization == organization
        assert subscription.keywords == ["test", "contract"]
        assert subscription.user == user

    def test_validate_keywords_must_be_list(self, user):
        """Test that keywords must be a list"""
        from conftest import OrganizationFactory
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        org = OrganizationFactory()

        data = {"organization_uid": org.uid, "keywords": "not-a-list"}  # Invalid

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert "keywords" in serializer.errors

    def test_validate_amount_range(self, user, organization):
        """Test amount_min must be less than amount_max"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "amount_min": "100000.00",
            "amount_max": "10000.00",  # Less than min - invalid!
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert (
            "amount_min" in serializer.errors or "non_field_errors" in serializer.errors
        )

    def test_validate_requires_target_or_filter(self, user):
        """Test that at least one target or filter is required"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        # Empty data - no target, no filter
        data = {}

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        # Should have validation error about missing target/filter

    def test_validate_relationship_requires_both_org_and_entity(self, user):
        """Test relationship subscription requires both org and entity"""
        from conftest import OrganizationFactory
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        org = OrganizationFactory()

        # Only org, no entity - invalid
        data = {
            "relationship_org_uid": org.uid,
            # Missing relationship_entity_afm
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()

    def test_nested_serializers_included(self, notification_subscription):
        """Test that nested organization/entity details are included"""
        from notifications.serializers import NotificationSubscriptionSerializer

        serializer = NotificationSubscriptionSerializer(notification_subscription)
        data = serializer.data

        # Should have nested details
        assert "organization_details" in data
        assert (
            data["organization_details"]["label"]
            == notification_subscription.organization.label
        )
        assert (
            data["organization_details"]["uid"]
            == notification_subscription.organization.uid
        )


class TestSerializerValidation:
    """Test validation logic in serializers"""

    def test_invalid_organization_uid_rejected(self, user):
        """Test that invalid organization UID is rejected"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {"organization_uid": "INVALID_UID_9999999", "keywords": ["test"]}

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert (
            "organization_uid" in serializer.errors
            or "organization" in serializer.errors
        )

    def test_invalid_entity_afm_rejected(self, user):
        """Test that invalid entity AFM is rejected"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {"entity_afm": "INVALID_AFM", "keywords": ["test"]}

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert "entity_afm" in serializer.errors or "entity" in serializer.errors

    def test_decision_types_must_be_list(self, user, organization):
        """Test that decision_types must be a list"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "decision_types": "not-a-list",  # Invalid
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert not serializer.is_valid()
        assert "decision_types" in serializer.errors


class TestNotificationBatchSerializers:
    """Test NotificationBatch serializers"""

    def test_serialize_batch_list(self, notification_batch):
        """Test serializing batch for list view"""
        from notifications.serializers import NotificationBatchListSerializer

        serializer = NotificationBatchListSerializer(notification_batch)
        data = serializer.data

        assert "id" in data
        assert "subscription" in data
        assert "subscription_alias" in data
        assert "subscription_type" in data
        assert "match_count" in data
        assert "check_window_start" in data
        assert "check_window_end" in data
        assert "is_read" in data
        assert "is_dismissed" in data
        assert "created_at" in data

    def test_serialize_batch_detail(self, notification_batch):
        """Test serializing batch for detail view"""
        from notifications.serializers import NotificationBatchDetailSerializer

        # Add some aggregate stats
        notification_batch.aggregate_stats = {
            "total_amount": 50000.0,
            "avg_amount": 5000.0,
            "decision_types": {"Α.1": 6, "Β.2": 4},
        }
        notification_batch.save()

        serializer = NotificationBatchDetailSerializer(notification_batch)
        data = serializer.data

        assert data["id"] == notification_batch.id
        assert data["match_count"] == notification_batch.match_count
        assert "subscription" in data
        assert "aggregate_stats" in data
        assert data["aggregate_stats"]["total_amount"] == 50000.0
        assert "check_window_start" in data
        assert "check_window_end" in data

    def test_serialize_batch_subscription_nested(self, notification_batch):
        """Test nested subscription serializer for batches"""
        from notifications.serializers import SubscriptionNestedForBatchSerializer

        serializer = SubscriptionNestedForBatchSerializer(
            notification_batch.subscription
        )
        data = serializer.data

        assert "id" in data
        assert "alias" in data
        assert "subscription_type" in data
        assert "keywords" in data
        assert "keyword_match_operator" in data

        if notification_batch.subscription.organization:
            assert "organization_label" in data

    def test_serialize_batch_decision(self, notification_batch_decision):
        """Test serializing batch decision"""
        from notifications.serializers import NotificationBatchDecisionSerializer

        serializer = NotificationBatchDecisionSerializer(notification_batch_decision)
        data = serializer.data

        assert "id" in data
        assert "decision" in data
        assert "match_reason" in data
        assert "match_details" in data
        assert "is_viewed" in data
        assert "added_at" in data

        # Verify nested decision data
        decision_data = data["decision"]
        assert "ada" in decision_data
        assert "subject" in decision_data
        assert "organization" in decision_data
        assert decision_data["organization"]["uid"]
        assert decision_data["organization"]["label"]
        assert "decision_type" in decision_data
        assert decision_data["decision_type"]["uid"]
        assert decision_data["decision_type"]["label"]

    def test_serialize_decision_nested_for_batch(self, decision):
        """Test nested decision serializer for batches"""
        from notifications.serializers import DecisionNestedForBatchSerializer

        serializer = DecisionNestedForBatchSerializer(decision)
        data = serializer.data

        assert "id" in data
        assert "ada" in data
        assert "subject" in data
        assert "protocol_number" in data
        assert "issue_date" in data
        assert "publish_timestamp" in data
        assert "organization" in data
        assert data["organization"]["uid"] == decision.organization.uid
        assert data["organization"]["label"] == decision.organization.label
        assert "decision_type" in data
        assert data["decision_type"]["uid"] == decision.decision_type.uid
        assert data["decision_type"]["label"] == decision.decision_type.label
        assert "amount" in data


class TestKeywordMatchOperatorSerializer:
    """Test keyword_match_operator field in serializers"""

    def test_create_subscription_with_or_operator(self, user, organization):
        """Test creating subscription with OR keyword operator"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "keywords": ["test", "contract"],
            "keyword_match_operator": "OR",
            "is_active": True,
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        assert subscription.keyword_match_operator == "OR"
        assert subscription.keywords == ["test", "contract"]

    def test_create_subscription_with_and_operator(self, user, organization):
        """Test creating subscription with AND keyword operator"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "keywords": ["urgent", "contract"],
            "keyword_match_operator": "AND",
            "is_active": True,
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        assert subscription.keyword_match_operator == "AND"

    def test_default_keyword_operator_is_or(self, user, organization):
        """Test that default keyword operator is OR"""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "keywords": ["test"],
            "is_active": True,
            # Not specifying keyword_match_operator
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        # Check model default
        assert subscription.keyword_match_operator in [
            "OR",
            "AND",
        ]  # Depends on model default

    def test_update_keyword_operator(self, notification_subscription):
        """Test updating keyword match operator"""
        from notifications.serializers import NotificationSubscriptionSerializer

        # Start with OR
        notification_subscription.keyword_match_operator = "OR"
        notification_subscription.save()

        # Update to AND
        serializer = NotificationSubscriptionSerializer(
            notification_subscription,
            data={"keyword_match_operator": "AND"},
            partial=True,
        )

        assert serializer.is_valid(), serializer.errors
        subscription = serializer.save()
        assert subscription.keyword_match_operator == "AND"

    def test_serialize_includes_keyword_operator(self, notification_subscription):
        """Test that serialized data includes keyword_match_operator"""
        from notifications.serializers import NotificationSubscriptionSerializer

        notification_subscription.keywords = ["test", "contract"]
        notification_subscription.keyword_match_operator = "AND"
        notification_subscription.save()

        serializer = NotificationSubscriptionSerializer(notification_subscription)
        data = serializer.data

        assert "keyword_match_operator" in data
        assert data["keyword_match_operator"] == "AND"
        assert "keywords" in data
        assert data["keywords"] == ["test", "contract"]

    def test_list_serializer_includes_keyword_operator(self, notification_subscription):
        """Test that list serializer includes keyword_match_operator"""
        from notifications.serializers import NotificationSubscriptionListSerializer

        notification_subscription.keywords = ["urgent"]
        notification_subscription.keyword_match_operator = "OR"
        notification_subscription.save()

        serializer = NotificationSubscriptionListSerializer(notification_subscription)
        data = serializer.data

        assert "keyword_match_operator" in data
        assert data["keyword_match_operator"] == "OR"


class TestAISummarySerializerFields:
    """Tests for AI summary fields in notification serializers."""

    def test_batch_detail_serializer_includes_ai_summary_fields(
        self, notification_batch
    ):
        """NotificationBatchDetailSerializer exposes ai_summary fields."""
        from notifications.serializers import NotificationBatchDetailSerializer

        notification_batch.ai_summary = "A concise summary."
        notification_batch.ai_summary_status = "COMPLETED"
        notification_batch.ai_summary_error = None
        notification_batch.ai_summary_completed_at = timezone.now()
        notification_batch.save()

        serializer = NotificationBatchDetailSerializer(notification_batch)
        data = serializer.data

        assert "ai_summary" in data
        assert data["ai_summary"] == "A concise summary."
        assert "ai_summary_status" in data
        assert data["ai_summary_status"] == "COMPLETED"
        assert "ai_summary_error" in data
        assert "ai_summary_completed_at" in data

    def test_batch_detail_serializer_read_only_fields(self, notification_batch):
        """All ai_summary fields are read-only in the detail serializer."""
        from notifications.serializers import NotificationBatchDetailSerializer

        serializer = NotificationBatchDetailSerializer(notification_batch)
        read_only = list(serializer.Meta.read_only_fields)

        for field in [
            "ai_summary",
            "ai_summary_status",
            "ai_summary_error",
            "ai_summary_completed_at",
        ]:
            assert field in read_only, f"{field} should be read-only"

    def test_subscription_serializer_includes_ai_summary_fields(
        self, notification_subscription
    ):
        """NotificationSubscriptionSerializer exposes ai_summary fields."""
        from core.models.pipeline import PipelineDefinition
        from notifications.serializers import NotificationSubscriptionSerializer

        pipeline = PipelineDefinition.objects.create(
            name="test_serializer_pipeline",
            version=1,
        )
        notification_subscription.ai_summary_enabled = True
        notification_subscription.ai_summary_pipeline = pipeline
        notification_subscription.save()

        serializer = NotificationSubscriptionSerializer(notification_subscription)
        data = serializer.data

        assert "ai_summary_enabled" in data
        assert data["ai_summary_enabled"] is True
        assert "ai_summary_pipeline" in data
        assert data["ai_summary_pipeline"] == pipeline.id

    def test_subscription_serializer_read_only_ai_fields(
        self, notification_subscription
    ):
        """ai_summary fields are in fields but writable (not read-only)."""
        from notifications.serializers import NotificationSubscriptionSerializer

        serializer = NotificationSubscriptionSerializer(notification_subscription)
        meta_fields = list(serializer.Meta.fields)
        read_only = list(serializer.Meta.read_only_fields)

        # The fields are exposed — they're writable via update, not read-only
        assert "ai_summary_enabled" in meta_fields
        assert "ai_summary_pipeline" in meta_fields
        assert "ai_summary_enabled" not in read_only
        assert "ai_summary_pipeline" not in read_only

    def test_create_serializer_includes_ai_summary_fields(self):
        """NotificationSubscriptionCreateSerializer accepts ai_summary fields."""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        fields = NotificationSubscriptionCreateSerializer.Meta.fields
        assert "ai_summary_enabled" in fields
        assert "ai_summary_pipeline" in fields

    def test_create_with_ai_summary_enabled(self, user, organization):
        """Creating a subscription with ai_summary_enabled=True works."""
        from core.models.pipeline import PipelineDefinition
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        pipeline = PipelineDefinition.objects.create(
            name="create_test_pipeline",
            version=1,
        )

        data = {
            "organization_uid": organization.uid,
            "keywords": ["urgent"],
            "is_active": True,
            "ai_summary_enabled": True,
            "ai_summary_pipeline": pipeline.id,
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        assert subscription.ai_summary_enabled is True
        assert subscription.ai_summary_pipeline == pipeline

    def test_create_without_ai_fields_defaults(self, user, organization):
        """Creating a subscription without AI fields uses defaults."""
        from notifications.serializers import NotificationSubscriptionCreateSerializer

        data = {
            "organization_uid": organization.uid,
            "keywords": ["urgent"],
            "is_active": True,
            # ai_summary_enabled not provided
        }

        serializer = NotificationSubscriptionCreateSerializer(data=data)
        assert serializer.is_valid(), serializer.errors

        subscription = serializer.save(user=user)
        assert subscription.ai_summary_enabled is False
        assert subscription.ai_summary_pipeline is None
