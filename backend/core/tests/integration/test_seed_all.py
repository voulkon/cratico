import re

import pytest
import responses
from core.services.seed_service import SeedService

pytestmark = pytest.mark.django_db

# Pattern that ONLY matches the main organizations endpoint
MAIN_ORG_PATTERN = re.compile(
    r"^https://diavgeia\.gov\.gr/opendata/organizations(\?.*)?$"
)

# Pattern that matches any Nominatim geocoding request
NOMINATIM_PATTERN = re.compile(
    r"^https://nominatim\.openstreetmap\.org/search\.php\?.*$"
)

# A minimal, valid Nominatim result used to simulate a successful geocode.
nominatim_geo_result = {
    "place_id": 55566353,
    "lat": "39.9088688",
    "lon": "25.1499608",
    "category": "boundary",
    "type": "administrative",
    "place_rank": 14,
    "importance": 0.29,
    "addresstype": "municipality",
    "name": "Δήμος Λήμνου",
    "display_name": "Δήμος Λήμνου",
    "boundingbox": ["39.7817004", "40.0360390", "25.0331782", "25.4472239"],
    "geojson": {"type": "Point", "coordinates": [25.1499608, 39.9088688]},
}


def _run_seed_all(mock_organizations_json, nominatim_payload):
    """Run seed_all with only the organizations endpoint mocked.

    All other Diavgeia calls pass through to the live API, while Nominatim is
    stubbed with `nominatim_payload` so geocoding is deterministic.
    """
    with responses.RequestsMock(
        assert_all_requests_are_fired=False,
        passthru_prefixes=["https://diavgeia.gov.gr"],
    ) as rsps:
        rsps.add(
            responses.GET,
            MAIN_ORG_PATTERN,
            json=mock_organizations_json,
            status=200,
        )
        rsps.add(
            responses.GET,
            NOMINATIM_PATTERN,
            json=nominatim_payload,
            status=200,
        )
        return SeedService().seed_all(force=True)


@pytest.mark.super_slow
@pytest.mark.parametrize(
    "nominatim_payload, expected_overall_status, expected_geodata_status",
    [
        ([nominatim_geo_result], "success", "success"),
        ([], "partial_success", "partial_success"),
    ],
    ids=["geodata-found", "geodata-not-found"],
)
def test_seed_all_happy_path(
    mock_organizations_json,
    nominatim_payload,
    expected_overall_status,
    expected_geodata_status,
):
    """Seed all data and verify the outcome matches the geocoding behaviour."""
    result = _run_seed_all(mock_organizations_json, nominatim_payload)
    expected_orgs = len(mock_organizations_json["organizations"])

    # Organizations are always imported from the mocked endpoint
    org_result = result["results"]["organizations"]
    assert org_result["status"] == "success"
    assert org_result["count"] == expected_orgs

    # Geodata status reflects whether Nominatim found a match
    geodata_result = result["results"]["organization_geodata"]
    assert geodata_result["status"] == expected_geodata_status
    assert geodata_result["count"] == (
        expected_orgs if expected_geodata_status == "success" else 0
    )

    # Overall status rolls up to partial_success if any step failed
    assert result["status"] == expected_overall_status
