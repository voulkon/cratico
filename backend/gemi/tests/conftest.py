import os

import pytest
import vcr
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


@pytest.fixture
def api_credentials():
    """Get API credentials from environment variables."""
    api_key = os.getenv("GEMI_API_KEY")
    if not api_key:
        pytest.skip("GEMI_API_KEY environment variable not set")
    return {"api_key": api_key}


@pytest.fixture
def dummy_ar_gemi():
    return 786301000


@pytest.fixture
def dummy_afm():
    return "090000045"


@pytest.fixture
def dummy_company_name():
    return "DEI"


@pytest.fixture
def vcr_config():
    """Provide VCR configuration for tests."""
    return vcr.VCR(
        serializer="yaml",
        cassette_library_dir="tests/cassettes",
        record_mode="once",
        match_on=["uri", "method"],
        filter_headers=["api_key"],
        filter_query_parameters=["api_key"],
        decode_compressed_response=True,
    )


@pytest.fixture
def vcr_cassette(vcr_config):
    """Factory fixture to create VCR cassettes."""

    def _create_cassette(cassette_name):
        return vcr_config.use_cassette(cassette_name)

    return _create_cassette
