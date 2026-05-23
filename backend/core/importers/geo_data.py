from decimal import Decimal

from core.importers.base import BaseImporter
from core.models.organizations import Organization, OrganizationGeoData
from core.pydantic_models.geo_data import NominatimResult
from django.db import transaction


class OrganizationGeoDataImporter(BaseImporter):
    """Create / update the 1-to-1 geo record for an Organization."""

    model = OrganizationGeoData

    # dto-attr → model-field (only include the ones that differ in name)
    field_map = {
        "place_rank": "place_rank",
        "display_name": "display_name",
    }

    # we don’t use uid_field because PK is the FK relation
    uid_field = ""  # <- easier to see it’s unused

    @transaction.atomic
    def import_one(
        self,
        dto: NominatimResult,  # <-- already validated
        organization: Organization,
    ) -> tuple[OrganizationGeoData, bool]:

        defaults = self._to_defaults(dto)

        # ---- post-processing that *is* still needed ------------------------
        # 1. store lat / lon as Decimal to keep Django’s precision
        defaults["lat"] = Decimal(str(dto.lat))
        defaults["lon"] = Decimal(str(dto.lon))

        # 2. boundingbox → list for JSONField
        defaults["boundingbox"] = [
            dto.boundingbox.south,
            dto.boundingbox.north,
            dto.boundingbox.west,
            dto.boundingbox.east,
        ]
        # 3. geojson can be dumped exactly as is
        defaults["geojson"] = dto.geojson.model_dump(mode="python")
        # -------------------------------------------------------------------

        obj, created = self.model.objects.update_or_create(
            organization=organization,
            defaults=defaults,
        )
        return obj, created
