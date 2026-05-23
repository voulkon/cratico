from typing import Any, Dict

from core.importers.base import BaseImporter
from core.models.field_mapping import field_map as imported_field_map
from core.models.types import ActType, ExtraField
from django.db import transaction
from loguru import logger


class ActTypeImporter(BaseImporter):
    model = ActType
    field_map = imported_field_map["TypeSummary"]

    @transaction.atomic
    def import_details(self, type_details) -> Dict[str, Any]:
        """
        Import full details for an act type, including parent relationship.
        Returns the created/updated act type and stats.
        """
        # Extract basic type info
        mapped = self._to_defaults(type_details)

        # Handle parent relationship if present
        parent = None
        if hasattr(type_details, "parent") and type_details.parent:
            # Try to find parent type
            try:
                parent = ActType.objects.get(uid=type_details.parent)
                mapped["parent"] = parent
            except ActType.DoesNotExist:
                logger.warning(
                    f"Parent type {type_details.parent} not found for {type_details.uid}"
                )

        # Create or update the ActType
        act_type, created = ActType.objects.update_or_create(
            uid=type_details.uid, defaults=mapped
        )

        return {"act_type": act_type, "created": created, "updated": not created}


class ExtraFieldImporter(BaseImporter):
    model = ExtraField
    field_map = imported_field_map["ExtraField"]
    special_handling_fields = ["nestedFields"]

    @transaction.atomic
    def import_for_type(self, type_details) -> Dict[str, int]:
        """
        Import all extra fields for a specific act type.
        Handles the nested field structure recursively.

        Returns stats on created and updated fields.
        """
        stats = {"created": 0, "updated": 0}

        if not hasattr(type_details, "extraFields"):
            logger.warning(f"No extra fields found for type {type_details.uid}")
            return stats

        # Get or create the act type to link fields to
        act_type, _ = ActType.objects.get_or_create(
            uid=type_details.uid,
            defaults={
                "label": type_details.label,
                "allowed_in_decisions": type_details.allowedInDecisions,
            },
        )

        # Process each extra field
        for extra_field in type_details.extraFields:
            result = self._import_field(extra_field, act_type)
            stats["created"] += int(result["created"])
            stats["updated"] += int(result["updated"])

        return stats

    def _import_field(self, field_dto, act_type, parent_field=None) -> Dict[str, Any]:
        """
        Recursively import a field and its nested fields.
        Returns the created field and stats.
        """
        # Map basic field properties
        mapped = self._to_defaults(field_dto)
        mapped["act_type"] = act_type

        # Set parent field if this is a nested field
        if parent_field:
            mapped["parent_field"] = parent_field

        # Create or update the field
        field, created = ExtraField.objects.update_or_create(
            uid=field_dto.uid, act_type=act_type, defaults=mapped
        )

        result = {
            "field": field,
            "created": created,
            "updated": not created,
            "help_created": 0,
        }

        # Recursively handle nested fields
        if hasattr(field_dto, "nestedFields") and field_dto.nestedFields:
            for nested_field in field_dto.nestedFields:
                nested_result = self._import_field(nested_field, act_type, field)
                result["created"] += nested_result["created"]
                result["updated"] += nested_result["updated"]

        return result
