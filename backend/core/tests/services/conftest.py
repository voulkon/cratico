from pathlib import Path

import pytest
import vcr
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_ingestion_service import DecisionIngestionService


@pytest.fixture
def corrupted_file_name() -> str:
    """Fixture to provide the name of a corrupted file."""
    return "Corrupted_text - 9ΑΦΞ6-ΧΚΗ.pdf"


@pytest.fixture
def another_not_corrupted_file_name() -> str:
    """Fixture to provide the name of another not corrupted file."""
    return "yet_another_with_non_corrupted_text - 9ΧΒΕ46ΜΑΠΣ-ΑΗΗ.pdf"


@pytest.fixture
def not_corrupted_file_name() -> str:
    """Fixture to provide the name of a not corrupted file."""
    return "Not_Corrupted - ΨΑ8Α469Β7Ι-ΤΔΒ.pdf"


@pytest.fixture
def file_path_factory(pdf_for_testing_path):
    """Factory fixture to create file paths with existence checking."""

    def _get_file_path(file_name: str) -> Path:
        the_path = pdf_for_testing_path / Path(file_name)
        if not the_path.exists():
            raise FileNotFoundError(
                f"Test file {the_path} does not exist. "
                "Please ensure it is present in the test directory."
            )
        return the_path

    return _get_file_path


@pytest.fixture
def corrupted_file_path(file_path_factory, corrupted_file_name) -> Path:
    """Fixture to provide the path of a corrupted file."""
    return file_path_factory(corrupted_file_name)


@pytest.fixture
def not_corrupted_file_path(file_path_factory, not_corrupted_file_name) -> Path:
    """Fixture to provide the path of a not corrupted file."""
    return file_path_factory(not_corrupted_file_name)


@pytest.fixture
def another_not_corrupted_file_path(
    file_path_factory, another_not_corrupted_file_name
) -> Path:
    """Fixture to provide the path of a not corrupted file."""
    return file_path_factory(another_not_corrupted_file_name)


# --- VCR Integration Tests ---


@pytest.fixture
def vcr_config():
    """Provide VCR configuration for tests."""
    return vcr.VCR(
        serializer="yaml",
        cassette_library_dir="fixtures/vcr_cassettes",
        record_mode="once",
        match_on=["uri", "method"],
        decode_compressed_response=True,
    )


@pytest.fixture
def daily_decisions_vcr_cassette(vcr_config):
    """Factory fixture to create VCR cassettes."""

    def _create_cassette(cassette_name):
        return vcr_config.use_cassette(cassette_name)

    return _create_cassette


# --- Helper Fixtures ---


@pytest.fixture
def a_test_diavgeia_fetcher() -> DiavgeiaFetcher:
    """Provides a MagicMock for the DiavgeiaFetcher."""
    return DiavgeiaFetcher()


@pytest.fixture
def a_test_decision_service(
    mock_diavgeia_fetcher: DiavgeiaFetcher,
) -> DecisionIngestionService:
    """Provides an instance of the service with a mocked fetcher and zero delay."""
    # Use delay=0 for tests to avoid actual sleeping
    return DecisionIngestionService(mock_diavgeia_fetcher, delay_seconds=20)
