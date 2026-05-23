from core.importers.base import BaseImporter
from core.models import Dictionary, DictionaryItem
from core.models.field_mapping import field_map as imported_field_map


class DictionaryListImporter(BaseImporter):
    model = Dictionary
    field_map = imported_field_map["DictionaryListItem"]


class DictionaryItemImporter(BaseImporter):
    model = DictionaryItem
    field_map = imported_field_map["DictionaryItem"]
