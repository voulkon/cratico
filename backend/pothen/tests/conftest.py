"""Test configuration and fixtures."""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest
from pothen.base_scraper import BaseScraperClient
from pothen.schemas import DeclarationEntry, DeclarationType


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    temp_path = Path(tempfile.mkdtemp())
    yield temp_path
    shutil.rmtree(temp_path, ignore_errors=True)


@pytest.fixture
def mock_scraper():
    """Mock scraper client for tests."""
    return Mock(spec=BaseScraperClient)


@pytest.fixture
def sample_declaration():
    """Sample declaration entry for testing."""
    return DeclarationEntry(
        last_name="KUNEVA",
        first_name="KOSTADINKA",
        pdf_url="http://www.hellenicparliament.gr/userfiles/pothen/xrhsh2021_etos2022/KUNEVA_KOSTADINKA_2586048_2022.pdf",
        year=2022,
        declaration_type=DeclarationType.ANNUAL,
        afm="2586048",
        file_id="KUNEVA_KOSTADINKA_2586048_2022",
    )


@pytest.fixture
def sample_html_row():
    """Sample HTML row for parser testing."""
    return """
    <tr>
        <td><a name="K">KUNEVA</a></td>
        <td>KOSTADINKA</td>
        <td><a href="http://www.hellenicparliament.gr/userfiles/pothen/xrhsh2021_etos2022/KUNEVA_KOSTADINKA_2586048_2022.pdf" target="_blank">Δήλωση</a></td>
    </tr>
    """


@pytest.fixture
def sample_pdf_content():
    """Sample PDF content for testing."""
    return b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n/Pages 2 0 R\n>>\nendobj\n"
