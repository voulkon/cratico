import pytest
from core.importers.geo_data import OrganizationGeoDataImporter
from core.models.organizations import Organization, OrganizationGeoData
from core.pydantic_models.geo_data import NominatimResult

pytestmark = pytest.mark.django_db

#
# ---------------------------------------------------------------------------
# fixtures – minimal examples
# ---------------------------------------------------------------------------


@pytest.fixture
def geo_importer() -> OrganizationGeoDataImporter:
    return OrganizationGeoDataImporter()


@pytest.fixture
def sample_org(db) -> Organization:
    return Organization.objects.create(label="Demo Org", uid="ORG-1")


@pytest.fixture
def nominatim_data(fetched_geo_data_success_full: NominatimResult) -> NominatimResult:
    """A second copy we can mutate in tests without touching the first."""
    return fetched_geo_data_success_full.model_copy(deep=True)
    # (pydantic v2’s deepcopy-aware clone)


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


@pytest.mark.impossible
def test_import_one_creates_record(
    geo_importer, sample_org, fetched_geo_data_success_full
):
    assert OrganizationGeoData.objects.count() == 0

    obj, created = geo_importer.import_one(
        dto=fetched_geo_data_success_full, organization=sample_org
    )

    assert created is True
    assert obj.organization == sample_org
    assert obj.place_id == fetched_geo_data_success_full.place_id
    assert float(obj.lat) == fetched_geo_data_success_full.lat
    assert float(obj.lon) == fetched_geo_data_success_full.lon
    assert obj.display_name == fetched_geo_data_success_full.display_name
    assert obj.geojson == fetched_geo_data_success_full.geojson.model_dump(
        mode="python"
    )
    assert OrganizationGeoData.objects.count() == 1
