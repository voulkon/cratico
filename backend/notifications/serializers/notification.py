from core.models.decisions import Decision
from notifications.models import Notification, NotificationSubscription
from notifications.serializers.decision_nested import DecisionNestedFieldsMixin
from rest_framework import serializers


class DecisionNestedSerializer(DecisionNestedFieldsMixin, serializers.ModelSerializer):
    """Lightweight serializer for nested decision details in notifications."""

    organization = serializers.SerializerMethodField()
    decision_type = serializers.SerializerMethodField()

    class Meta:
        model = Decision
        fields = [
            "id",
            "ada",
            "subject",
            "protocol_number",
            "issue_date",
            "organization",
            "decision_type",
        ]
        read_only_fields = fields


class SubscriptionNestedSerializer(serializers.ModelSerializer):
    """Lightweight serializer for nested subscription details in notifications."""

    subscription_type = serializers.CharField(read_only=True)

    class Meta:
        model = NotificationSubscription
        fields = ["id", "subscription_type"]
        read_only_fields = fields


class NotificationListSerializer(serializers.ModelSerializer):
    """
    Optimized serializer for list view with lighter payload.
    Minimal nested data for performance.
    """

    subscription_type = serializers.CharField(
        source="subscription.subscription_type", read_only=True
    )
    decision_ada = serializers.CharField(source="decision.ada", read_only=True)
    decision_subject = serializers.CharField(source="decision.subject", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "subscription_type",
            "decision_ada",
            "decision_subject",
            "match_reason",
            "is_read",
            "is_dismissed",
            "created_at",
        ]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    """
    Full serializer for Notification with nested details.
    Used for list and basic retrieve operations.
    """

    subscription = SubscriptionNestedSerializer(read_only=True)
    decision = DecisionNestedSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "subscription",
            "decision",
            "match_reason",
            "match_details",
            "is_read",
            "is_dismissed",
            "created_at",
            "read_at",
        ]
        read_only_fields = fields


class SubscriptionDetailSerializer(serializers.ModelSerializer):
    """More detailed subscription serializer for notification detail view."""

    subscription_type = serializers.CharField(read_only=True)
    organization_label = serializers.CharField(
        source="organization.label", read_only=True
    )
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    entity_afm = serializers.CharField(source="entity.afm", read_only=True)

    class Meta:
        model = NotificationSubscription
        fields = [
            "id",
            "subscription_type",
            "organization_label",
            "entity_name",
            "entity_afm",
            "person_name",
            "signer_name",
            "keywords",
            "amount_min",
            "amount_max",
            "decision_types",
        ]
        read_only_fields = fields


class DecisionDetailSerializer(DecisionNestedFieldsMixin, serializers.ModelSerializer):
    """More detailed decision serializer for notification detail view."""

    organization = serializers.SerializerMethodField()
    decision_type = serializers.SerializerMethodField()

    class Meta:
        model = Decision
        fields = [
            "id",
            "ada",
            "subject",
            "protocol_number",
            "issue_date",
            "submission_timestamp",
            "organization",
            "decision_type",
            "has_private_data",
        ]
        read_only_fields = fields


class NotificationDetailSerializer(serializers.ModelSerializer):
    """
    Extended serializer with full subscription and decision details.
    Used for single notification retrieval.
    """

    subscription = SubscriptionDetailSerializer(read_only=True)
    decision = DecisionDetailSerializer(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "user",
            "subscription",
            "decision",
            "match_reason",
            "match_details",
            "is_read",
            "is_dismissed",
            "created_at",
            "read_at",
        ]
        read_only_fields = fields
