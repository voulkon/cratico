from core.models.decisions import Decision
from notifications.models import (
    NotificationBatch,
    NotificationBatchDecision,
    NotificationSubscription,
)
from rest_framework import serializers


class SubscriptionNestedForBatchSerializer(serializers.ModelSerializer):
    """Lightweight serializer for nested subscription details in batches."""

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
            "alias",
            "subscription_type",
            "organization_label",
            "entity_name",
            "entity_afm",
            "keywords",
            "keyword_match_operator",
        ]
        read_only_fields = fields


class DecisionNestedForBatchSerializer(serializers.ModelSerializer):
    """
    Enhanced serializer for nested decision details in batch decisions.
    Includes all fields needed by DecisionCard component in the frontend.
    """

    # Convert amount from Decimal to float for consistency with other API endpoints
    amount = serializers.SerializerMethodField()

    # Nested organization object
    organization = serializers.SerializerMethodField()

    # Nested decision_type object
    decision_type = serializers.SerializerMethodField()

    # Signers array
    signers = serializers.SerializerMethodField()

    # KAE amounts array
    kae_amounts = serializers.SerializerMethodField()

    # KAE total (calculated from kae_amounts)
    kae_total = serializers.SerializerMethodField()

    # Amount discrepancy flags (calculated)
    has_amount_discrepancy = serializers.SerializerMethodField()
    discrepancy_percentage = serializers.SerializerMethodField()

    # Has document content flag
    has_document_content = serializers.SerializerMethodField()

    # Entity data flags to prevent N+1 queries in frontend
    # Adding these fields (even as null) tells DecisionCard not to auto-fetch entities
    entity_amount = serializers.SerializerMethodField()
    main_recipient = serializers.SerializerMethodField()

    class Meta:
        model = Decision
        fields = [
            "id",
            "ada",
            "subject",
            "protocol_number",
            "issue_date",
            "publish_timestamp",
            "organization",
            "decision_type",
            "signers",
            "amount",
            "kae_amounts",
            "kae_total",
            "has_amount_discrepancy",
            "discrepancy_percentage",
            "has_document_content",
            "document_url",
            "status",
            "entity_amount",
            "main_recipient",
        ]
        read_only_fields = fields

    def get_amount(self, obj):
        """Convert DecimalField amount to float for consistency with other API endpoints."""
        return float(obj.amount) if obj.amount else None

    def get_organization(self, obj):
        """Return organization as nested object."""
        if obj.organization:
            return {
                "uid": obj.organization.uid,
                "label": obj.organization.label,
            }
        return None

    def get_decision_type(self, obj):
        """Return decision_type as nested object."""
        if obj.decision_type:
            return {
                "uid": obj.decision_type.uid,
                "label": obj.decision_type.label,
            }
        return None

    def get_signers(self, obj):
        """Return signers array with uid, first_name, last_name."""
        return [
            {
                "uid": signer.uid,
                "first_name": signer.first_name,
                "last_name": signer.last_name,
            }
            for signer in obj.signers.all()
        ]

    def get_kae_amounts(self, obj):
        """Return KAE amounts array."""
        return [
            {
                "kae": kae.kae,
                "amount": float(kae.amount) if kae.amount else None,
            }
            for kae in obj.kae_amounts.all()
        ]

    def get_kae_total(self, obj):
        """Calculate total from KAE amounts."""
        if hasattr(obj, "kae_amounts") and obj.kae_amounts.exists():
            total = sum(kae.amount for kae in obj.kae_amounts.all() if kae.amount)
            return float(total) if total else None
        return None

    def get_has_amount_discrepancy(self, obj):
        """Check if there's a discrepancy between decision amount and KAE total."""
        kae_total = self.get_kae_total(obj)
        primary_amount = float(obj.amount) if obj.amount else 0

        if kae_total and primary_amount and kae_total != primary_amount:
            return True
        return False

    def get_discrepancy_percentage(self, obj):
        """Calculate percentage discrepancy between decision amount and KAE total."""
        kae_total = self.get_kae_total(obj)
        primary_amount = float(obj.amount) if obj.amount else 0

        if kae_total and primary_amount and kae_total != primary_amount:
            percentage = abs((float(kae_total) - primary_amount) / primary_amount * 100)
            return round(percentage, 2)
        return 0

    def get_has_document_content(self, obj):
        """Check if decision has document extraction content."""
        return hasattr(obj, "document_extraction")

    def get_entity_amount(self, obj):
        """
        Return None to indicate entity data is available (prevents auto-fetch).
        For batch notifications, we don't preload full entity data to keep responses light.
        """
        return None

    def get_main_recipient(self, obj):
        """
        Return None to indicate entity data is available (prevents auto-fetch).
        For batch notifications, we don't preload full entity data to keep responses light.
        """
        return None


class NotificationBatchDecisionSerializer(serializers.ModelSerializer):
    """
    Serializer for individual decisions within a batch.
    Used for the decisions list endpoint.
    """

    decision = DecisionNestedForBatchSerializer(read_only=True)

    class Meta:
        model = NotificationBatchDecision
        fields = [
            "id",
            "decision",
            "match_reason",
            "match_details",
            "is_viewed",
            "viewed_at",
            "added_at",
        ]
        read_only_fields = fields


class NotificationBatchListSerializer(serializers.ModelSerializer):
    """
    Optimized serializer for batch list view with lighter payload.
    Minimal nested data for performance.
    """

    subscription_alias = serializers.CharField(
        source="subscription.alias", read_only=True
    )
    subscription_type = serializers.CharField(
        source="subscription.subscription_type", read_only=True
    )

    class Meta:
        model = NotificationBatch
        fields = [
            "id",
            "subscription",
            "subscription_alias",
            "subscription_type",
            "match_count",
            "check_window_start",
            "check_window_end",
            "is_read",
            "is_dismissed",
            "created_at",
        ]
        read_only_fields = fields


class NotificationBatchDetailSerializer(serializers.ModelSerializer):
    """
    Full serializer for NotificationBatch with nested details.
    Used for retrieve operation.
    """

    subscription = SubscriptionNestedForBatchSerializer(read_only=True)

    class Meta:
        model = NotificationBatch
        fields = [
            "id",
            "user",
            "subscription",
            "check_window_start",
            "check_window_end",
            "match_count",
            "aggregate_stats",
            "is_read",
            "is_dismissed",
            "created_at",
            "read_at",
            "dismissed_at",
        ]
        read_only_fields = fields
