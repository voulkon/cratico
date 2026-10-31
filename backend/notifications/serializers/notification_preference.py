from rest_framework import serializers

from notifications.models import NotificationPreference


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    email_mode_display = serializers.CharField(
        source="get_email_mode_display", read_only=True
    )

    class Meta:
        model = NotificationPreference
        fields = [
            "id",
            "email_enabled",
            "email_mode",
            "email_mode_display",
            "digest_hour_local",
            "ai_summary_enabled",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
