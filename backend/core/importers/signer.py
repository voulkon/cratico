from core.importers.base import BaseImporter
from core.models.field_mapping import field_map as imported_field_map
from core.models.organizations import Organization, Signer, SignerUnit, Unit
from loguru import logger


class SignerImporter(BaseImporter):
    model = Signer
    field_map = imported_field_map["Signer"]
    special_handling_fields = [
        "organizationId"
    ]  # Add this line to exclude direct mapping

    def _to_defaults(self, dto) -> dict:
        """Override to handle special fields"""
        defaults = super()._to_defaults(dto)

        # Add resolution path if it exists
        if hasattr(dto, "resolution_path"):
            defaults["resolution_path"] = dto.resolution_path

        # Handle organization relationship properly
        if hasattr(dto, "organizationId") and dto.organizationId:
            try:
                # Look up the organization object
                org = Organization.objects.get(uid=dto.organizationId)
                defaults["organization"] = org  # Assign the actual object, not the ID
            except Organization.DoesNotExist:
                logger.warning(
                    f"Organization with ID {dto.organizationId} not found for signer {dto.uid}"
                )
                # Either skip this signer or handle missing organization
                # For now, we'll let it fail to maintain data integrity

        return defaults

    def _handle_units(self, signer, units_dto):
        """
        Link signer to units. If the API gives back the organisation UID,
        we interpret that as ‘organisation-level signer’ and skip the link.
        """
        org_uid = signer.organization.uid

        for unit_dto in units_dto:
            unit_uid = unit_dto["uid"]

            # ── skip the fake unit that equals the organisation ──────────────
            if str(unit_uid) == str(org_uid):
                signer.has_organization_sign_rights = True
                signer.save()
                continue

            unit, _ = Unit.objects.get_or_create(
                uid=unit_uid,
                defaults={
                    "label": unit_dto.get("positionLabel", unit_uid),
                    "organization": signer.organization,
                    "active": True,
                    "category": "UNKNOWN",
                },
            )
            signer.units.add(unit)


class SignerDomainImporter(BaseImporter):
    model = SignerUnit
    field_map = imported_field_map.get("SignerUnit")
