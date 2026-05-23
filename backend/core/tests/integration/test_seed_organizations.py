import pytest
import responses
from core.services.seed_service import SeedService

pytestmark = pytest.mark.django_db


@pytest.mark.fast
@responses.activate
def test_seed_organizations_happy_path(
    mock_organizations_json, mock_units_json, mock_positions_json, mock_signers_json
):
    for_endpoints = {
        "units": mock_units_json,
        "positions": mock_positions_json,
        "signers": mock_signers_json,
    }
    for org in mock_organizations_json["organizations"]:
        this_orgs_uid = org["uid"]
        for endpoint, response in for_endpoints.items():
            responses.add(
                responses.GET,
                f"https://diavgeia.gov.gr/opendata/organizations/{this_orgs_uid}/{endpoint}",
                json=response,
                status=200,
            )
    responses.add(
        responses.GET,
        f"https://diavgeia.gov.gr/opendata/organizations",
        json=mock_organizations_json,
        status=200,
    )

    service = SeedService()
    result = service.seed_organizations(force=True)

    assert result["seeded"] is True
    number_of_orgs_in_response = len(mock_organizations_json["organizations"])
    number_of_orgs_seeded = result["count"]
    assert number_of_orgs_seeded == number_of_orgs_in_response
