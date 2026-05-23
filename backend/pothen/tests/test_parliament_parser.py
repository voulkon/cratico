"""Test parliament parser functionality."""

from unittest.mock import Mock

import pytest
from bs4 import BeautifulSoup
from pothen.exceptions import PothenParsingError
from pothen.parliament_parser import ParliamentParser
from pothen.schemas import DeclarationType


class TestParliamentParser:
    """Test cases for ParliamentParser."""

    def test_init(self, mock_scraper):
        """Test parser initialization."""
        parser = ParliamentParser(mock_scraper)
        assert parser.scraper is mock_scraper

    def test_parse_pdf_filename_annual(self):
        """Test parsing annual declaration filename."""
        parser = ParliamentParser(Mock())

        pdf_url = "http://example.com/KUNEVA_KOSTADINKA_2586048_2022e.pdf"
        afm, file_id, declaration_type = parser._parse_pdf_filename(pdf_url)

        assert afm == "2586048"
        assert file_id == "KUNEVA_KOSTADINKA_2586048_2022e"
        assert declaration_type == DeclarationType.ANNUAL

    def test_parse_pdf_filename_initial(self):
        """Test parsing initial declaration filename."""
        parser = ParliamentParser(Mock())

        pdf_url = "http://example.com/BASTIAN_JENS_3865851_2023a.pdf"
        afm, file_id, declaration_type = parser._parse_pdf_filename(pdf_url)

        assert afm == "3865851"
        assert file_id == "BASTIAN_JENS_3865851_2023a"
        assert declaration_type == DeclarationType.INITIAL

    def test_parse_declaration_row_valid(self):
        """Test parsing valid declaration row."""
        parser = ParliamentParser(Mock())

        html = """
        <tr>
            <td><a name="K">KUNEVA</a></td>
            <td>KOSTADINKA</td>
            <td><a href="/userfiles/pothen/test.pdf" target="_blank">Δήλωση</a></td>
        </tr>
        """

        soup = BeautifulSoup(html, "html.parser")
        row = soup.find("tr")

        entry = parser._parse_declaration_row(row, 2022)

        assert entry is not None
        assert entry.last_name == "KUNEVA"
        assert entry.first_name == "KOSTADINKA"
        assert entry.year == 2022
        assert str(entry.pdf_url).endswith("test.pdf")

    def test_parse_declaration_row_invalid(self):
        """Test parsing invalid declaration row."""
        parser = ParliamentParser(Mock())

        # Row with insufficient cells
        html = "<tr><td>ONLY ONE CELL</td></tr>"
        soup = BeautifulSoup(html, "html.parser")
        row = soup.find("tr")

        entry = parser._parse_declaration_row(row, 2022)
        assert entry is None

    def test_parse_declaration_row_no_pdf_link(self):
        """Test parsing row without PDF link."""
        parser = ParliamentParser(Mock())

        html = """
        <tr>
            <td>LASTNAME</td>
            <td>FIRSTNAME</td>
            <td>No link here</td>
        </tr>
        """

        soup = BeautifulSoup(html, "html.parser")
        row = soup.find("tr")

        entry = parser._parse_declaration_row(row, 2022)
        assert entry is None


class TestParliamentParserIntegration:
    """Integration tests for ParliamentParser (require mocking HTTP calls)."""

    def test_get_available_years_success(self, mock_scraper):
        """Test successful year extraction."""
        # Mock response with year links
        mock_response = Mock()
        mock_response.text = """
        <html>
            <p><a href="/Diloseis-Periousiakis-Katastasis2024">DECLARATIONS 2024</a></p>
            <p><a href="/Diloseis-Periousiakis-Katastasis2023">DECLARATIONS 2023</a></p>
            <p><a href="/Diloseis-Periousiakis-Katastasis2022">DECLARATIONS 2022</a></p>
        </html>
        """
        mock_scraper.get.return_value = mock_response

        parser = ParliamentParser(mock_scraper)
        years = parser.get_available_years("http://test.com")

        assert years == [2024, 2023, 2022]  # Should be sorted descending
        mock_scraper.get.assert_called_once_with("http://test.com")

    def test_get_available_years_no_years(self, mock_scraper):
        """Test when no years are found."""
        mock_response = Mock()
        mock_response.text = "<html><p>No declaration links here</p></html>"
        mock_scraper.get.return_value = mock_response

        parser = ParliamentParser(mock_scraper)

        with pytest.raises(PothenParsingError, match="No declaration years found"):
            parser.get_available_years("http://test.com")

    def test_parse_year_page_success(self, mock_scraper):
        """Test successful year page parsing."""
        mock_response = Mock()
        mock_response.text = """
        <html>
            <table>
                <tr>
                    <td><a name="K">KUNEVA</a></td>
                    <td>KOSTADINKA</td>
                    <td><a href="/test1.pdf" target="_blank">Δήλωση</a></td>
                </tr>
                <tr>
                    <td>BASTIAN</td>
                    <td>JENS</td>
                    <td><a href="/test2.pdf" target="_blank">Δήλωση</a></td>
                </tr>
            </table>
        </html>
        """
        mock_scraper.get.return_value = mock_response

        parser = ParliamentParser(mock_scraper)
        declarations = parser.parse_year_page(2022)

        assert declarations.year == 2022
        assert len(declarations.entries) == 2
        assert declarations.entries[0].last_name == "KUNEVA"
        assert declarations.entries[1].last_name == "BASTIAN"
