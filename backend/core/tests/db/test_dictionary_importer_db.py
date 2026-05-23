import pytest
from core.importers.dictionary import DictionaryItemImporter, DictionaryListImporter
from core.models import Dictionary, DictionaryItem
from diavgeia_api.models.dictionaries import DictionaryItem as DictionaryItemDTO
from diavgeia_api.models.dictionaries import DictionaryListItem

pytestmark = pytest.mark.django_db


@pytest.mark.fast
def test_create_and_update_dictionaries():
    imp = DictionaryListImporter()

    # first call creates
    created = imp.import_many([DictionaryListItem(uid="dict1", label="Decision Types")])
    assert created == 1
    dictionary = Dictionary.objects.get(uid="dict1")
    assert dictionary.label == "Decision Types"

    # second call updates, no new row
    created = imp.import_many(
        [DictionaryListItem(uid="dict1", label="Updated Decision Types")]
    )
    assert created == 0
    dictionary.refresh_from_db()
    assert dictionary.label == "Updated Decision Types"


@pytest.mark.fast
def test_create_and_update_items():
    # Create parent dictionary first
    Dictionary.objects.create(uid="parent_dict", label="Parent Dictionary")

    imp = DictionaryItemImporter()

    # first call creates
    created = imp.import_many(
        [DictionaryItemDTO(uid="item1", label="Item One", dictionary="parent_dict")],
        defaults={"dictionary": Dictionary.objects.get(uid="parent_dict")},
    )
    assert created == 1
    item = DictionaryItem.objects.get(uid="item1")
    assert item.label == "Item One"

    # second call updates, no new row
    created = imp.import_many(
        [
            DictionaryItemDTO(
                uid="item1", label="Updated Item", dictionary="parent_dict"
            )
        ],
        defaults={"dictionary": Dictionary.objects.get(uid="parent_dict")},
    )
    assert created == 0
    item.refresh_from_db()
    assert item.label == "Updated Item"
