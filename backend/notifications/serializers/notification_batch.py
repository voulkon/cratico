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

    # Human-readable target name (alias, org label, entity, person, etc.)
    display_name = serializers.SerializerMethodField()

    # Formatted check-window period (e.g. "May 1–15, 2026")
    period_label = serializers.SerializerMethodField()

    class Meta:
        model = NotificationBatch
        fields = [
            "id",
            "subscription",
            "subscription_alias",
            "subscription_type",
            "display_name",
            "period_label",
            "match_count",
            "check_window_start",
            "check_window_end",
            "is_read",
            "is_dismissed",
            "created_at",
        ]
        read_only_fields = fields

    @staticmethod
    def _get_target_name(sub):
        """Extract the subscription's target name (no period)."""
        if sub.alias:
            return sub.alias
        if sub.organization_id:
            return (
                sub.organization.label
                if sub.organization and sub.organization.label
                else f"Organization #{sub.organization_id}"
            )
        if sub.entity_id:
            return (
                sub.entity.name or sub.entity.afm
                if sub.entity
                else f"Entity #{sub.entity_id}"
            )
        if sub.relationship_org_id and sub.relationship_entity_id:
            org_label = (
                sub.relationship_org.label
                if sub.relationship_org and sub.relationship_org.label
                else f"Org #{sub.relationship_org_id}"
            )
            ent_label = (
                sub.relationship_entity.name or sub.relationship_entity.afm
                if sub.relationship_entity
                else f"Entity #{sub.relationship_entity_id}"
            )
            return f"{org_label} × {ent_label}"
        if sub.person_name:
            return sub.person_name
        if sub.signer_name:
            return sub.signer_name
        return f"Subscription #{sub.id}"

    def get_display_name(self, obj):
        """
        Human-readable label for the subscription target.

        Examples: "Δήμος Αθηναίων", "My Alias", "123456789"
        """
        return self._get_target_name(obj.subscription)

    def get_period_label(self, obj):
        """
        Formatted check-window period.

        Examples: "May 1–15, 2026", "Jun 10, 2026"
        """
        return _format_date_range(obj.check_window_start, obj.check_window_end)


def _format_date_range(start, end):
    """
    Format a date range into a compact human-readable string.

    Examples:
        Same day:      "Jun 10, 2026"
        Same month:    "May 1–15, 2026"
        Same year:     "May 1 – Jun 5, 2026"
        Across years:  "Dec 20, 2025 – Jan 5, 2026"
    """
    if start is None and end is None:
        return ""
    if start is None:
        return end.strftime("%b %d, %Y")
    if end is None:
        return start.strftime("%b %d, %Y")

    same_day = start.date() == end.date()
    same_month = start.year == end.year and start.month == end.month
    same_year = start.year == end.year

    if same_day:
        return start.strftime("%b %d, %Y")

    if same_month:
        return f"{start.strftime('%b %d')}–{end.strftime('%d, %Y')}"

    if same_year:
        return f"{start.strftime('%b %d')} – {end.strftime('%b %d, %Y')}"

    return f"{start.strftime('%b %d, %Y')} – {end.strftime('%b %d, %Y')}"


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
