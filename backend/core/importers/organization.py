import re

from core.importers.base import BaseImporter
from core.models import Organization
from core.models.field_mapping import field_map as imported_field_map


class OrganizationImporter(BaseImporter):
    model = Organization
    field_map = imported_field_map["Organization"]
    do_not_update_fields = ["created_at", "updated_at"]

    def _to_defaults(self, dto) -> dict:
        """Override to clean VAT number before saving"""
        defaults = super()._to_defaults(dto)

        # Clean VAT number if present
        if "vat_number" in defaults and defaults["vat_number"]:
            # Extract only digits at the beginning of the string
            match = re.search(r"\d{9}", defaults["vat_number"])
            if match:
                defaults["vat_number"] = match.group(0)

        return defaults
