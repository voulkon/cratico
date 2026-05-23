from core.models.entities import AFMEntity
from core.models.organizations import Organization
from notifications.models import NotificationSubscription
from rest_framework import serializers


class OrganizationNestedSerializer(serializers.ModelSerializer):
    """Lightweight serializer for nested organization details."""

    class Meta:
        model = Organization
        fields = ["uid", "label", "latin_name"]
        read_only_fields = fields


class AFMEntityNestedSerializer(serializers.ModelSerializer):
    """Lightweight serializer for nested AFM entity details."""

    class Meta:
        model = AFMEntity
        fields = ["afm", "name", "entity_type"]
        read_only_fields = fields


class NotificationSubscriptionSerializer(serializers.ModelSerializer):
    """
    Full serializer for NotificationSubscription with nested details.
    Used for retrieve and list operations.
    """

    # Use slug fields to return natural keys (uid/afm) instead of IDs
    organization = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Organization.objects.all(),
        required=False,
        allow_null=True,
    )
    entity = serializers.SlugRelatedField(
        slug_field="afm",
        queryset=AFMEntity.objects.all(),
        required=False,
        allow_null=True,
    )
    relationship_org = serializers.SlugRelatedField(
        slug_field="uid",
        queryset=Organization.objects.all(),
        required=False,
        allow_null=True,
    )
    relationship_entity = serializers.SlugRelatedField(
        slug_field="afm",
        queryset=AFMEntity.objects.all(),
        required=False,
        allow_null=True,
    )

    # Nested serializers for read operations
    organization_details = OrganizationNestedSerializer(
        source="organization", read_only=True
    )
    entity_details = AFMEntityNestedSerializer(source="entity", read_only=True)
    relationship_org_details = OrganizationNestedSerializer(
        source="relationship_org", read_only=True
    )
    relationship_entity_details = AFMEntityNestedSerializer(
        source="relationship_entity", read_only=True
    )

    # Computed field
    subscription_type = serializers.CharField(read_only=True)

    class Meta:
        model = NotificationSubscription
        fields = [
            "id",
            "user",
            "organization",
            "organization_details",
            "entity",
            "entity_details",
            "relationship_org",
            "relationship_org_details",
            "relationship_entity",
            "relationship_entity_details",
            "person_name",
            "signer_name",
            "alias",
            "keywords",
            "keyword_match_operator",
            "amount_min",
            "amount_max",
            "decision_types",
            "is_active",
            "check_frequency",
            "subscription_type",
            "created_at",
            "last_checked",
        ]
        read_only_fields = [
            "id",
            "user",
            "created_at",
            "last_checked",
            "subscription_type",
        ]

    def validate_keywords(self, value):
        """Ensure keywords is a list if provided."""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("Keywords must be a list.")
        return value

    def validate_decision_types(self, value):
        """Ensure decision_types is a list if provided."""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("Decision types must be a list.")
        return value

    def validate(self, data):
        """
        Validate that:
        1. At least one target OR at least one filter is provided (only for creation, not partial updates)
        2. amount_min < amount_max if both provided
        """
        # For partial updates (PATCH), skip the target/filter validation if only updating other fields
        # The instance already has valid targets/filters
        is_partial_update = self.instance is not None and self.partial

        if not is_partial_update:
            # Check for targets
            has_target = any(
                [
                    data.get("organization") is not None,
                    data.get("entity") is not None,
                    data.get("relationship_org") is not None
                    and data.get("relationship_entity") is not None,
                    data.get("person_name"),
                    data.get("signer_name"),
                ]
            )

            # Check for filters
            has_filter = any(
                [
                    data.get("keywords"),
                    data.get("amount_min") is not None,
                    data.get("amount_max") is not None,
                    data.get("decision_types"),
                ]
            )

            if not has_target and not has_filter:
                raise serializers.ValidationError(
                    "Must specify at least one of: target (organization, entity, relationship, person, or signer) "
                    "OR at least one filter (keywords, amounts, decision types)."
                )

        # Validate amount range
        amount_min = data.get("amount_min")
        amount_max = data.get("amount_max")
        if amount_min is not None and amount_max is not None:
            if amount_min >= amount_max:
                raise serializers.ValidationError(
                    {"amount_min": "amount_min must be less than amount_max"}
                )

        # Validate relationship subscription has both org and entity
        relationship_org = data.get("relationship_org")
        relationship_entity = data.get("relationship_entity")
        if relationship_org is not None and relationship_entity is None:
            raise serializers.ValidationError(
                "Relationship subscription requires both organization and entity."
            )
        if relationship_entity is not None and relationship_org is None:
            raise serializers.ValidationError(
                "Relationship subscription requires both organization and entity."
            )

        return data


class NotificationSubscriptionCreateSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for creating subscriptions.
    Accepts organization UID and entity AFM as strings and converts them.
    """

    organization_uid = serializers.CharField(
        required=False, allow_null=True, write_only=True
    )
    entity_afm = serializers.CharField(required=False, allow_null=True, write_only=True)
    relationship_org_uid = serializers.CharField(
        required=False, allow_null=True, write_only=True
    )
    relationship_entity_afm = serializers.CharField(
        required=False, allow_null=True, write_only=True
    )

    class Meta:
        model = NotificationSubscription
        fields = [
            "organization_uid",
            "entity_afm",
            "relationship_org_uid",
            "relationship_entity_afm",
            "person_name",
            "signer_name",
            "alias",
            "keywords",
            "keyword_match_operator",
            "amount_min",
            "amount_max",
            "decision_types",
            "is_active",
            "check_frequency",
        ]

    def validate_keywords(self, value):
        """Ensure keywords is a list if provided."""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("Keywords must be a list.")
        return value

    def validate_decision_types(self, value):
        """Ensure decision_types is a list if provided."""
        if value is not None and not isinstance(value, list):
            raise serializers.ValidationError("Decision types must be a list.")
        return value

    def validate(self, data):
        """
        Validate that:
        1. At least one target OR at least one filter is provided
        2. amount_min < amount_max if both provided
        3. UIDs and AFMs are valid
        """
        # Check for targets
        has_target = any(
            [
                data.get("organization_uid"),
                data.get("entity_afm"),
                data.get("relationship_org_uid")
                and data.get("relationship_entity_afm"),
                data.get("person_name"),
                data.get("signer_name"),
            ]
        )

        # Check for filters
        has_filter = any(
            [
                data.get("keywords"),
                data.get("amount_min") is not None,
                data.get("amount_max") is not None,
                data.get("decision_types"),
            ]
        )

        if not has_target and not has_filter:
            raise serializers.ValidationError(
                "Must specify at least one of: target (organization, entity, relationship, person, or signer) "
                "OR at least one filter (keywords, amounts, decision types)."
            )

        # Validate amount range
        amount_min = data.get("amount_min")
        amount_max = data.get("amount_max")
        if amount_min is not None and amount_max is not None:
            if amount_min >= amount_max:
                raise serializers.ValidationError(
                    {"amount_min": "amount_min must be less than amount_max"}
                )

        # Validate relationship subscription has both org and entity
        relationship_org_uid = data.get("relationship_org_uid")
        relationship_entity_afm = data.get("relationship_entity_afm")
        if relationship_org_uid and not relationship_entity_afm:
            raise serializers.ValidationError(
                "Relationship subscription requires both organization and entity."
            )
        if relationship_entity_afm and not relationship_org_uid:
            raise serializers.ValidationError(
                "Relationship subscription requires both organization and entity."
            )

        # Validate organization UID if provided
        if data.get("organization_uid"):
            try:
                Organization.objects.get(uid=data["organization_uid"])
            except Organization.DoesNotExist:
                raise serializers.ValidationError(
                    {
                        "organization_uid": f"Organization with UID '{data['organization_uid']}' does not exist."
                    }
                )

        # Validate entity AFM if provided
        if data.get("entity_afm"):
            try:
                AFMEntity.objects.get(afm=data["entity_afm"])
            except AFMEntity.DoesNotExist:
                raise serializers.ValidationError(
                    {
                        "entity_afm": f"Entity with AFM '{data['entity_afm']}' does not exist."
                    }
                )

        # Validate relationship org UID if provided
        if data.get("relationship_org_uid"):
            try:
                Organization.objects.get(uid=data["relationship_org_uid"])
            except Organization.DoesNotExist:
                raise serializers.ValidationError(
                    {
                        "relationship_org_uid": f"Organization with UID '{data['relationship_org_uid']}' does not exist."
                    }
                )

        # Validate relationship entity AFM if provided
        if data.get("relationship_entity_afm"):
            try:
                AFMEntity.objects.get(afm=data["relationship_entity_afm"])
            except AFMEntity.DoesNotExist:
                raise serializers.ValidationError(
                    {
                        "relationship_entity_afm": f"Entity with AFM '{data['relationship_entity_afm']}' does not exist."
                    }
                )

        return data

    def create(self, validated_data):
        """
        Convert UIDs/AFMs to FK relationships and create subscription.
        """
        # Extract and convert UIDs/AFMs
        organization_uid = validated_data.pop("organization_uid", None)
        entity_afm = validated_data.pop("entity_afm", None)
        relationship_org_uid = validated_data.pop("relationship_org_uid", None)
        relationship_entity_afm = validated_data.pop("relationship_entity_afm", None)

        # Convert to FK relationships
        if organization_uid:
            validated_data["organization"] = Organization.objects.get(
                uid=organization_uid
            )
        if entity_afm:
            validated_data["entity"] = AFMEntity.objects.get(afm=entity_afm)
        if relationship_org_uid:
            validated_data["relationship_org"] = Organization.objects.get(
                uid=relationship_org_uid
            )
        if relationship_entity_afm:
            validated_data["relationship_entity"] = AFMEntity.objects.get(
                afm=relationship_entity_afm
            )

        # Add user from request context if not already provided
        # (user can be provided via serializer.save(user=user) for testing)
        if "user" not in validated_data:
            # Get user from request context (for production API calls)
            if "request" in self.context:
                validated_data["user"] = self.context["request"].user

        # Create subscription
        return NotificationSubscription.objects.create(**validated_data)


class NotificationSubscriptionListSerializer(serializers.ModelSerializer):
    """
    Optimized serializer for list view with lighter payload.
    """

    subscription_type = serializers.CharField(read_only=True)

    # Target IDs (for linking)
    organization_uid = serializers.CharField(source="organization.uid", read_only=True)
    entity_afm = serializers.CharField(source="entity.afm", read_only=True)
    relationship_org_uid = serializers.CharField(
        source="relationship_org.uid", read_only=True
    )
    relationship_entity_afm = serializers.CharField(
        source="relationship_entity.afm", read_only=True
    )

    # Target labels (for display)
    organization_label = serializers.CharField(
        source="organization.label", read_only=True
    )
    entity_name = serializers.CharField(source="entity.name", read_only=True)
    relationship_org_label = serializers.CharField(
        source="relationship_org.label", read_only=True
    )
    relationship_entity_name = serializers.CharField(
        source="relationship_entity.name", read_only=True
    )

    # Computed target name for display
    target_name = serializers.SerializerMethodField()

    # Notification count
    notification_count = serializers.SerializerMethodField()

    # Rename last_checked to match frontend expectation
    last_checked_at = serializers.DateTimeField(source="last_checked", read_only=True)

    def get_target_name(self, obj):
        """Get a display name for the subscription target."""
        if obj.organization:
            return obj.organization.label or obj.organization.uid
        elif obj.entity:
            return obj.entity.name or obj.entity.afm
        elif obj.relationship_org and obj.relationship_entity:
            org_label = obj.relationship_org.label or obj.relationship_org.uid
            entity_name = obj.relationship_entity.name or obj.relationship_entity.afm
            return f"{org_label} × {entity_name}"
        elif obj.person_name:
            return obj.person_name
        elif obj.signer_name:
            return obj.signer_name
        else:
            return obj.alias or f"Subscription #{obj.id}"

    def get_notification_count(self, obj):
        """Get the count of notifications for this subscription."""
        return obj.notifications.count()

    class Meta:
        model = NotificationSubscription
        fields = [
            "id",
            "subscription_type",
            "alias",
            "organization_uid",
            "organization_label",
            "entity_afm",
            "entity_name",
            "relationship_org_uid",
            "relationship_org_label",
            "relationship_entity_afm",
            "relationship_entity_name",
            "person_name",
            "signer_name",
            "target_name",
            "keywords",
            "keyword_match_operator",
            "amount_min",
            "amount_max",
            "decision_types",
            "is_active",
            "check_frequency",
            "notification_count",
            "last_checked_at",
            "created_at",
        ]
        read_only_fields = fields
