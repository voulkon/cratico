import pytest
from core.importers.dictionary import DictionaryItemImporter, DictionaryListImporter
from diavgeia_api.models.dictionaries import DictionaryItem as DictionaryItemDTO
from diavgeia_api.models.dictionaries import DictionaryListItem


@pytest.fixture
def dictionary_dto():
    """Sample dictionary DTO for testing."""
    return DictionaryListItem(
        uid="decision_types",
        label="Decision Types",
    )


@pytest.fixture
def expected_dictionary_defaults():
    """Expected mapping results for dictionary."""
    return {
        "label": "Decision Types",
    }


@pytest.mark.fast
def test_dictionary_to_defaults_mapping(dictionary_dto, expected_dictionary_defaults):
    imp = DictionaryListImporter()
    defaults = imp._to_defaults(dictionary_dto)
    assert (
        defaults == expected_dictionary_defaults
    ), f"Expected {expected_dictionary_defaults}, but got {defaults}"


# Dictionary Item tests
@pytest.fixture
def dictionary_item_dto():
    """Sample dictionary item DTO for testing."""
    return DictionaryItemDTO(
        uid="decision_type_1",
        label="Approval",
        parent="decision_types",
        dictionary="decision_types",
    )


@pytest.fixture
def expected_dictionary_item_defaults():
    """Expected mapping results for dictionary item."""
    return {
        "label": "Approval",
        "parent": "decision_types",
    }


@pytest.mark.fast
def test_dictionary_item_to_defaults_mapping(
    dictionary_item_dto, expected_dictionary_item_defaults
):
    imp = DictionaryItemImporter()
    defaults = imp._to_defaults(dictionary_item_dto)
    are_the_same = defaults == expected_dictionary_item_defaults
    assert (
        are_the_same
    ), f"Expected {expected_dictionary_item_defaults}, but got {defaults}"
