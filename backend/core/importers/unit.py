from core.importers.base import BaseImporter
from core.models.field_mapping import field_map as imported_field_map
from core.models.organizations import Unit, UnitDomain
from django.db import transaction
from loguru import logger


class UnitImporter(BaseImporter):
    model = Unit
    field_map = imported_field_map["Unit"]

    def _to_defaults(self, dto):
        defaults = super()._to_defaults(dto)

        # Add resolution path if it exists
        if hasattr(dto, "resolution_path"):
            defaults["resolution_path"] = dto.resolution_path

        # **CRITICAL FIX: Handle both parent and parent_id fields**
        parent_value = None

        # Check both possible field names and get the parent value
        if "parent_id" in defaults:
            parent_value = defaults.pop("parent_id")  # Remove it
        if "parent" in defaults:
            parent_value = defaults.pop(
                "parent"
            )  # Remove it and override if both exist

        # Only set parent_id if the parent actually exists as a Unit
        if parent_value:
            from core.models.organizations import Unit

            if Unit.objects.filter(uid=parent_value).exists():
                defaults["parent_id"] = parent_value
                logger.debug(f"Set parent_id={parent_value} for unit {dto.uid}")
            else:
                logger.debug(
                    f"Removed parent relationship for unit {dto.uid} - parent {parent_value} is not a Unit"
                )

        return defaults


class UnitDomainImporter(BaseImporter):
    model = UnitDomain
    field_map = imported_field_map.get("UnitDomain", {})

    @transaction.atomic
    def import_many(self, domain_strings, *, defaults=None):
        """Special implementation for domain strings instead of DTOs"""
        defaults = defaults or {}
        unit = defaults.get("unit")
        if not unit:
            raise ValueError("Unit must be provided in defaults")

        total = 0
        for domain in domain_strings:
            obj, created = self.model.objects.update_or_create(
                domain=domain, unit=unit, defaults=defaults
            )
            total += int(created)
        return total
