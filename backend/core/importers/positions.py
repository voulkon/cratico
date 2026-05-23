from core.importers.base import BaseImporter
from core.models.field_mapping import field_map as imported_field_map
from core.models.organizations import Position


class PositionImporter(BaseImporter):
    model = Position
    field_map = imported_field_map.get("Position", {})
