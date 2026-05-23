from pathlib import Path
from urllib.parse import quote

import pytest
import responses
from core.fetchers.nominatim_fetcher import NominatimFetcher
from core.models.decisions import Decision
from core.pydantic_models.geo_data import NominatimResult
from core.services.extractors.pymupdf import PyMuPDFExtractor
from core.tests.utils import load_json_fixture, load_pickle_fixture
from django.conf import settings


def pytest_collection_modifyitems(config, items):
    """
    Skip PostgreSQL tests if we're not using PostgreSQL
    This runs after test collection but before test execution
    """
    skip_pg = pytest.mark.skip(
        reason="PostgreSQL required but not enabled (set PG_TEST=1)"
    )

    for item in items:
        if "requires_postgresql" in item.keywords:
            # Check if we're running with PostgreSQL
            if not getattr(settings, "USING_POSTGRESQL_FOR_TESTS", False):
                item.add_marker(skip_pg)


@pytest.fixture
def an_ada() -> str:
    return "6ΩΡΥ46ΜΤΛΠ-ΑΙΙ"


@pytest.fixture
def a_pdf_url(an_ada) -> str:
    return f"https://diavgeia.gov.gr/doc/{an_ada}.pdf"


@pytest.fixture
def pdf_to_extract_text_from(pdf_for_testing_path) -> Path:
    return pdf_for_testing_path / Path("filmiki_epihorigisi.pdf")


@pytest.fixture
def page_count_of_pdf() -> int:
    return 2


@pytest.fixture
def expected_text_in_pdf() -> str:
    return "ΦΙΛΜΙΚΗ"


@pytest.fixture
def pymupdf_result(pdf_to_extract_text_from) -> Path:
    extractor = PyMuPDFExtractor()
    result = extractor.extract_text(pdf_to_extract_text_from)

    return result


@pytest.fixture
def mock_decision(an_ada, a_pdf_url):
    """Create a test decision"""
    from datetime import datetime, timedelta, timezone

    # Create a decision with all required fields
    return Decision.objects.create(
        ada=an_ada,
        document_url=a_pdf_url,
        version_id="v1",
        subject="Test Decision for Document Extraction",
        issue_date=datetime.now(timezone.utc) - timedelta(days=3),  # 3 days ago
        submission_timestamp=datetime.now(timezone.utc)
        - timedelta(days=2),  # 2 days ago
        publish_timestamp=datetime.now(timezone.utc) - timedelta(days=1),  # 1 day ago
        status="PUBLISHED",
        url=a_pdf_url,
    )


@pytest.fixture
def data_for_testing_path():
    return Path(__file__).parent / "data"


@pytest.fixture
def pdf_for_testing_path(data_for_testing_path):
    return data_for_testing_path / Path("pdfs")


@pytest.fixture
def mock_units_json():
    return load_json_fixture("units_lite.json")


@pytest.fixture
def mock_positions_json():
    return load_json_fixture("positions_lite.json")


@pytest.fixture
def mock_signers_json():
    return load_json_fixture("signers_lite.json")


@pytest.fixture(autouse=True)
def _silence_logs(caplog):
    caplog.set_level("CRITICAL")


@pytest.fixture
def mock_organizations_json():
    return load_json_fixture("organizations_active_lite.json")


@pytest.fixture
def label_to_query() -> str:
    return "Δήμος Λήμνου"


@pytest.fixture
def geo_data_full_response() -> NominatimResult:
    return load_pickle_fixture("dimos_limnou_geo_data_whole.pkl")


@pytest.fixture
def nominatim_fetcher():
    return NominatimFetcher()


@responses.activate
@pytest.fixture
def fetched_geo_data_success_full(
    nominatim_fetcher, geo_data_full_response, label_to_query
):

    encoded_query = quote(label_to_query)
    url = f"{NominatimFetcher.BASE_URL}?q={encoded_query}&polygon_geojson=1&format=jsonv2&limit=5"

    with responses.RequestsMock() as rsps:  # Corrected pass_through
        rsps.add(responses.GET, url, json=geo_data_full_response, status=200)

        result = nominatim_fetcher.fetch_geo_data(label_to_query)

    return result


@pytest.fixture
def mock_diavgeia_api(mock_organizations_json):
    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://diavgeia.gov.gr/opendata/organizations",
            json=mock_organizations_json,
            status=200,
            content_type="application/json",
        )
        yield rsps
