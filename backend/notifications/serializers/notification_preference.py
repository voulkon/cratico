from rest_framework import serializers

from notifications.models import NotificationPreference


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    email_mode_display = serializers.CharField(
        source="get_email_mode_display", read_only=True
    )
    digest_hours_local = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=23),
        required=False,
        allow_empty=True,
    )

    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "email_enabled",
            "email_mode",
            "email_mode_display",
            "digest_hour_local",
            "digest_hours_local",
            "ai_summary_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate_digest_hours_local(self, value):
        return sorted(set(value))

    def _sync_legacy_hour(self, validated_data):
        hours = validated_data.get("digest_hours_local")
        if hours:
            # Keep the legacy column in sync for older readers/queries.
            validated_data["digest_hour_local"] = hours[0]
        elif "digest_hour_local" in validated_data:
            # Legacy clients still send only the single hour.
            validated_data["digest_hours_local"] = [
                validated_data["digest_hour_local"]
            ]

    def create(self, validated_data):
        self._sync_legacy_hour(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        self._sync_legacy_hour(validated_data)
        return super().update(instance, validated_data)
