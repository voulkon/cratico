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


class DecisionNestedForBatchSerializer(serializers.Serializer):
    """
    Nested decision payload aligned with the unified decision-card shape
    (``api.views.search.base.serialize_decision_with_entities``).

    Entity relationships and calculated amounts are bulk-computed by the view
    and passed via serializer context (``entity_relationships_by_decision`` and
    ``calculated_amount_by_decision``) to avoid N+1 queries.
    """

    def to_representation(self, instance):
        from api.views.search.base import serialize_decision_with_entities

        entity_relationships_by_decision = self.context.get(
            "entity_relationships_by_decision", {}
        )
        calculated_amount_by_decision = self.context.get(
            "calculated_amount_by_decision", {}
        )

        entity_rels = entity_relationships_by_decision.get(instance.id, [])
        data = serialize_decision_with_entities(instance, entity_rels)

        # The unified view=decisions payload overrides `amount` with the
        # verified calculated amount; match that here.
        calculated = calculated_amount_by_decision.get(instance.id)
        if calculated is not None:
            data["amount"] = calculated

        # Preserve extra fields not produced by the canonical serializer.
        data["protocol_number"] = instance.protocol_number
        data["publish_timestamp"] = instance.publish_timestamp

        return data


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
            "ai_summary",
            "ai_summary_status",
            "ai_summary_error",
            "ai_summary_completed_at",
        ]
        read_only_fields = fields
