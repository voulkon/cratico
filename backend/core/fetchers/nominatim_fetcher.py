from urllib.parse import quote

import requests
from core.pydantic_models.geo_data import NominatimResult
from loguru import logger
from pydantic import ValidationError

IS_NOMINATIM_FETCHER_READY = False


class NominatimFetcher:
    """Fetches geographical data from OpenStreetMap Nominatim."""

    BASE_URL = "https://nominatim.openstreetmap.org/search.php"
    HEADERS = {
        "User-Agent": "DiavgeiaApp/1.0 (https://github.com/voulkon/diavgeia-api/)"
    }

    def fetch_geo_data(self, query: str) -> NominatimResult | None:
        """
        Fetches geodata for a given query string.

        Args:
            query: The search term (e.g., organization label).

        Returns:
            A validated NominatimResult object or None on error/no results.
        """
        if not query:
            logger.warning("Nominatim query is empty, skipping fetch.")
            return None

        encoded_query = quote(query)
        url = (
            f"{self.BASE_URL}?q={encoded_query}&polygon_geojson=1&format=jsonv2&limit=2"
        )
        logger.debug(f"Fetching Nominatim data for query: '{query}' from URL: {url}")

        try:
            response = requests.get(url, headers=self.HEADERS, timeout=30)
            response.raise_for_status()
            data = response.json()
            logger.debug(f"Nominatim response data: {str(data)[:3000]}")

            # Check if we got any results
            if not data or not isinstance(data, list) or len(data) == 0:
                logger.warning(f"No results found for query: '{query}'")
                return None

            # Try to validate the first result
            try:
                validated_data = NominatimResult(**data[0])
                logger.info(f"Successfully validated geodata for '{query}'")
                return validated_data
            except ValidationError as e:
                logger.warning(f"Validation failed for result of query '{query}': {e}")
                return None

        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching Nominatim data for query '{query}': {e}")
            return None
        except Exception as e:
            logger.error(
                f"An unexpected error occurred during Nominatim fetch for query '{query}': {e}"
            )
            return None
