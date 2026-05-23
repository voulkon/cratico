import pytest
import responses
from core.services.seed_service import SeedService
from core.tests.utils import load_json_fixture

pytestmark = pytest.mark.django_db


@pytest.mark.fast
@responses.activate
def test_seed_dictionaries_happy_path():
    payload = load_json_fixture("dictionaries_list_lite.json")
    responses.add(
        responses.GET,
        "https://diavgeia.gov.gr/opendata/dictionaries",
        json=payload,
        status=200,
    )

    service = SeedService()
    result = service.seed_dictionaries(force=True)

    assert result["seeded"] is True
    number_of_dictionaries_in_response = len(payload["dictionaries"])
    number_of_dictionaries_seeded = result["count"]
    assert number_of_dictionaries_seeded == number_of_dictionaries_in_response


@pytest.mark.fast
@responses.activate
def test_seed_dictionarys_items_happy_path():

    # 1. First create the dictionary we'll need
    dictionary_uid = "FEKTYPES"
    from core.models import Dictionary

    Dictionary.objects.create(uid=dictionary_uid, label="FEK Types")

    # 2. Set up mock response for dictionary items
    items_payload = load_json_fixture("dictionary_items_fektypes_lite.json")

    responses.add(
        responses.GET,
        f"https://diavgeia.gov.gr/opendata/dictionaries/{dictionary_uid}",
        json=items_payload,
        status=200,
    )

    service = SeedService()
    result = service.seed_dictionary_items(force=True)

    assert result["seeded"] is True
    number_of_dictionary_items_in_response = len(items_payload["items"])
    number_of_dictionary_items_seeded = result["count"]
    assert number_of_dictionary_items_seeded == number_of_dictionary_items_in_response
