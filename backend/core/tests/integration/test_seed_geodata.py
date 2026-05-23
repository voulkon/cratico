import pytest
import responses
from core.fetchers.nominatim_fetcher import IS_NOMINATIM_FETCHER_READY, NominatimFetcher
from core.models.organizations import Organization, OrganizationGeoData
from core.pydantic_models.geo_data import NominatimResult  # , GeoJson
from core.services.seed_service import SeedService
from core.tests.utils import load_pickle_fixture

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_organizations_in_db(db):
    org1 = Organization.objects.create(
        uid="6174",
        label="ΔΗΜΟΣ ΛΗΜΝΟΥ",
        latin_name="dimos_limnou",
        status="active",
        category="MUNICIPALITY",
    )
    # org2 = Organization.objects.create(
    #     uid="17265",
    #     label="ΔΗΜΟΤΟΛΟΓΙΟ ΔΗΜΟΥ ΔΩΔΩΝΗΣ Ν. ΙΩΑΝΝΙΝΩΝ",
    #     latin_name="dodoni2",
    #     status="active",
    #     category="OTHERTYPE",
    # )
    # org3 = Organization.objects.create(
    #     uid="9999",
    #     label="Org Without Geo Result",
    #     latin_name="nogeo",
    #     status="active",
    #     category="TEST",
    # )

    return [
        org1,
        # org2,
        # org3
    ]


@pytest.mark.skipif(
    not IS_NOMINATIM_FETCHER_READY,
    reason="Nominatim is not implemented yet, this is a placeholder test for when it is",
)
@pytest.fixture
def mock_nominatim_response_limnos_valid() -> list[dict]:
    """Loads the full response for Limnos and prepares it for responses mock."""
    return load_pickle_fixture("dimos_limnou_geo_data_whole.pkl")


@pytest.mark.skipif(
    not IS_NOMINATIM_FETCHER_READY,
    reason="Nominatim is not implemented yet, this is a placeholder test for when it is",
)
@pytest.fixture
def mock_nominatim_response_dodoni_valid() -> list[dict]:
    """Provides a valid mock response dictionary list for Dodoni."""
    return [
        {
            "place_id": 67890,
            "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
            "osm_type": "relation",
            "osm_id": 12345,
            "lat": "39.55",
            "lon": "20.75",
            "category": "boundary",
            "type": "administrative",
            "place_rank": 14,
            "importance": 0.4,
            "addresstype": "municipality",
            "name": "Dodoni",
            "display_name": "Dodoni...",
            "boundingbox": ["39.4", "39.7", "20.6", "20.9"],
            "geojson": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [20.6, 39.4],
                        [20.9, 39.4],
                        [20.9, 39.7],
                        [20.6, 39.7],
                        [20.6, 39.4],
                    ]
                ],
            },
        }
    ]


@pytest.mark.skipif(
    not IS_NOMINATIM_FETCHER_READY,
    reason="Nominatim is not implemented yet, this is a placeholder test for when it is",
)
@responses.activate
def test_seed_organization_geodata_happy_path(
    mock_organizations_in_db,
    mock_nominatim_response_limnos_valid,
    mock_nominatim_response_dodoni_valid,
):
    responses.add(
        method=responses.GET,
        url=NominatimFetcher.BASE_URL,
        match=[
            responses.matchers.query_param_matcher(
                {
                    "q": "ΔΗΜΟΣ ΛΗΜΝΟΥ",
                    "polygon_geojson": "1",
                    "format": "jsonv2",
                    "limit": "5",
                }
            )
        ],
        json=mock_nominatim_response_limnos_valid,
        status=200,
    )

    service = SeedService()
    result = service.seed_organization_geodata(force=True)

    assert result["status"] == "success"
    assert result["seeded"] is True
    assert result["count"] == 1
    assert "Created: 1" in result["message"]
    assert "Skipped: 0" in result["message"]

    assert OrganizationGeoData.objects.count() == 1
    geo1 = OrganizationGeoData.objects.get(organization__uid="6174")
    assert geo1.place_id == mock_nominatim_response_limnos_valid[0]["place_id"]
    assert geo1.display_name == mock_nominatim_response_limnos_valid[0]["display_name"]

    assert not OrganizationGeoData.objects.filter(organization__uid="9999").exists()

    nominatim_calls = [
        call
        for call in responses.calls
        if call.request.url.startswith(NominatimFetcher.BASE_URL)
    ]
    assert len(nominatim_calls) == len(mock_organizations_in_db)
