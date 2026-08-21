"""Shared nested-field helpers for Decision serializers.

Keeps the nested decision shape consistent across all notification
serializers and aligned with the canonical serializer
``api.views.search.base.serialize_decision_with_content_info``.

The canonical shape is:

    {
        "organization": {"uid": ..., "label": ...},   # or None
        "decision_type": {"uid": ..., "label": ...},   # or None
    }
"""


class DecisionNestedFieldsMixin:
    """Mixin providing get_organization / get_decision_type methods.

    Serializers using this mixin should declare the corresponding fields:

        organization = serializers.SerializerMethodField()
        decision_type = serializers.SerializerMethodField()
    """

    def get_organization(self, obj):
        """Return organization as a nested {uid, label} object."""
        if obj.organization:
            return {
                "uid": obj.organization.uid,
                "label": obj.organization.label,
            }
        return None

    def get_decision_type(self, obj):
        """Return decision_type as a nested {uid, label} object."""
        if obj.decision_type:
            return {
                "uid": obj.decision_type.uid,
                "label": obj.decision_type.label,
            }
        return None
