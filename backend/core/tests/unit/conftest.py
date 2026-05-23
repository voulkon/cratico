from pathlib import Path

import pytest
from core.models.decisions import Decision
from core.services.extractors.pymupdf import PyMuPDFExtractor
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
