import pytest
import vcr


@pytest.fixture
def vcr_config():
    """Provide VCR configuration for tests."""
    return vcr.VCR(
        serializer="yaml",
        cassette_library_dir="fixtures/vcr_cassettes/db",
        record_mode="once",
        match_on=["uri", "method"],
        decode_compressed_response=True,
    )


@pytest.fixture
def vcr_cassette(vcr_config):
    """Factory fixture to create VCR cassettes."""

    def _create_cassette(cassette_name):
        return vcr_config.use_cassette(cassette_name)

    return _create_cassette
