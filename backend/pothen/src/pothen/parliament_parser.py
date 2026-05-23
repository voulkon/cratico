"""Parliament HTML parser for extracting declaration links."""

import logging
import re
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .base_scraper import BaseScraperClient
from .constants import DECLARATIONS_YEAR_URL_TEMPLATE, PARLIAMENT_BASE_URL
from .exceptions import PothenParsingError, PothenScrapingError
from .schemas import DeclarationEntry, DeclarationType, YearlyDeclarations

logger = logging.getLogger(__name__)


class ParliamentParser:
    """Parser for Hellenic Parliament declaration pages."""

    def __init__(self, scraper_client: BaseScraperClient):
        self.scraper = scraper_client

    def get_available_years(self, landing_url: str) -> List[int]:
        """
        Extract available declaration years from the landing page.

        Looks for links like:
        <a href="...Diloseis-Periousiakis-Katastasis2024">ΔΗΛΩΣΕΙΣ...2024...</a>
        """
        logger.info(f"Fetching available years from {landing_url}")

        try:
            response = self.scraper.get(landing_url)
            soup = BeautifulSoup(response.text, "html.parser")

            years = set()

            # Look for links containing "Diloseis-Periousiakis-Katastasis" followed by year
            year_pattern = re.compile(r"Diloseis-Periousiakis-Katastasis(\d{4})")

            for link in soup.find_all("a", href=True):
                href = link["href"]
                match = year_pattern.search(href)
                if match:
                    year = int(match.group(1))
                    years.add(year)
                    logger.debug(f"Found year {year} in link: {href}")

            if not years:
                raise PothenParsingError("No declaration years found on landing page")

            sorted_years = sorted(years, reverse=True)
            logger.info(f"Found {len(sorted_years)} available years: {sorted_years}")
            return sorted_years

        except Exception as e:
            raise PothenScrapingError(
                f"Failed to parse available years: {str(e)}"
            ) from e

    def parse_year_page(self, year: int) -> YearlyDeclarations:
        """
        Parse a year-specific declarations page to extract all PDF links.

        Expected HTML structure:
        <tr>
            <td><a name="K">KUNEVA</a></td>
            <td>KOSTADINKA</td>
            <td><a href="...pdf" target="_blank">Δήλωση</a></td>
        </tr>
        """
        url = DECLARATIONS_YEAR_URL_TEMPLATE.format(year=year)
        logger.info(f"Parsing declarations for year {year} from {url}")

        try:
            response = self.scraper.get(url)
            soup = BeautifulSoup(response.text, "html.parser")
            declarations = YearlyDeclarations(year=year, page_url=url)

            # Find all table rows with declaration data
            rows = soup.find_all("tr")

            for row in rows:
                entry = self._parse_declaration_row(row, year)
                if entry:
                    declarations.entries.append(entry)

            logger.info(f"Found {len(declarations.entries)} declarations for {year}")

            if not declarations.entries:
                raise PothenParsingError(f"No declarations found for year {year}")

            return declarations

        except Exception as e:
            raise PothenScrapingError(
                f"Failed to parse year {year} page: {str(e)}"
            ) from e

    def _parse_declaration_row(self, row: Tag, year: int) -> Optional[DeclarationEntry]:
        """Parse a single table row to extract declaration information."""
        try:
            cells = row.find_all("td")

            # Need at least 3 cells: last_name, first_name, pdf_link
            if len(cells) < 3:
                return None

            # Extract names
            last_name_cell = cells[0]
            first_name_cell = cells[1]
            pdf_link_cell = cells[2]

            # Get last name (might be in <a> tag or direct text)
            last_name_elem = last_name_cell.find("a")
            if last_name_elem:
                last_name = last_name_elem.get_text(strip=True)
            else:
                last_name = last_name_cell.get_text(strip=True)

            # Get first name
            first_name = first_name_cell.get_text(strip=True)

            # Get PDF link
            pdf_link = pdf_link_cell.find("a", href=True)
            if not pdf_link:
                return None

            pdf_url = pdf_link["href"]

            # Convert relative URLs to absolute
            if not pdf_url.startswith("http"):
                pdf_url = urljoin(PARLIAMENT_BASE_URL, pdf_url)

            # Skip if not a PDF
            if not pdf_url.lower().endswith(".pdf"):
                return None

            # Extract metadata from filename
            afm, file_id, declaration_type = self._parse_pdf_filename(pdf_url)

            return DeclarationEntry(
                last_name=last_name,
                first_name=first_name,
                pdf_url=pdf_url,
                year=year,
                declaration_type=declaration_type,
                afm=afm,
                file_id=file_id,
            )

        except Exception as e:
            logger.debug(f"Failed to parse row: {str(e)}")
            return None

    def _parse_pdf_filename(
        self, pdf_url: str
    ) -> tuple[Optional[str], Optional[str], DeclarationType]:
        """Extract AFM, file ID, and declaration type from PDF filename."""
        filename = urlparse(pdf_url).path.split("/")[-1]

        # Remove .pdf extension
        name_without_ext = filename.replace(".pdf", "")

        # Split by underscores: LASTNAME_FIRSTNAME_AFM_YEARx.pdf
        # where x might be 'a' (arxiki) or 'e' (ethsia)
        parts = name_without_ext.split("_")

        afm = None
        file_id = None
        declaration_type = DeclarationType.ANNUAL  # Default

        if len(parts) >= 3:
            # Try to find AFM (should be numeric)
            for part in parts:
                if part.isdigit() and len(part) >= 6:  # AFM is typically 9 digits
                    afm = part
                    break

        # Check last part for declaration type indicator
        if parts:
            last_part = parts[-1].lower()
            if last_part.endswith("a"):
                declaration_type = DeclarationType.INITIAL
            elif last_part.endswith("e"):
                declaration_type = DeclarationType.ANNUAL

        # Use full filename as file_id for uniqueness
        file_id = name_without_ext

        return afm, file_id, declaration_type

    def get_declarations_for_years(
        self, years: List[int]
    ) -> Dict[int, YearlyDeclarations]:
        """Parse declarations for multiple years."""
        results = {}

        for year in years:
            try:
                declarations = self.parse_year_page(year)
                results[year] = declarations
                logger.info(
                    f"Successfully parsed {len(declarations.entries)} declarations for {year}"
                )

            except Exception as e:
                logger.error(f"Failed to parse declarations for year {year}: {str(e)}")
                continue

        return results
