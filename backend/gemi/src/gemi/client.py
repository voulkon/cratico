from typing import List, Optional, Union

from loguru import logger

from .base_client import BaseAPIClient
from .config import GemiConfig
from .exceptions import GemiAPIError, GemiValidationError
from .pagination import PaginatedResponse
from .schemas.company import CompanyResponse, CompanySummary
from .services import CompaniesService, ReferenceDataService


class GemiDataClient:
    """High-level client for the BusinessPortal OpenData API, aggregating all services."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        config: Optional[GemiConfig] = None,
    ):
        """
        Initialize the OpenData API client.

        Args:
            api_key: API key for authentication. If not provided, will try to get from config or environment.
            base_url: Base URL for the API. If not provided, will use default or config value.
            config: Configuration object. If not provided, will create from environment variables.
        """
        if config is None:
            config = GemiConfig.from_env()

        # Override config with explicit parameters
        if api_key is not None:
            config.api_key = api_key
        if base_url is not None:
            config.base_url = base_url

        config.validate()

        # Initialize the base client and service components
        self._base_client = BaseAPIClient(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )
        self.companies = CompaniesService(self._base_client)
        self.reference = ReferenceDataService(self._base_client)

    @classmethod
    def from_config(cls, config: GemiConfig) -> "GemiDataClient":
        """Create a client instance from a configuration object."""
        return cls(config=config)

    def get_company(self, arithmos_gemi: Union[str, int]) -> CompanyResponse:
        """
        Get company information by GEMI registration number.

        Args:
            arithmos_gemi: The GEMI registration number (AR GEMI) as string or integer.
                        Must contain only digits if string.

        Returns:
            CompanyResponse: Validated company information

        Raises:
            GemiValidationError: If the arithmos_gemi parameter is invalid
            GemiNotFoundError: If the company is not found (404)
            GemiAPIError: For other API errors

        Example:
            >>> client = GemiDataClient(api_key="your-key")
            >>> company = client.get_company("786301000")
            >>> print(f"Company: {company.coNameEl}")
            >>> print(f"AFM: {company.afm}")
        """
        # Validate and normalize the GEMI number
        normalized_gemi = self._validate_and_normalize_gemi(arithmos_gemi)

        try:
            # Use CompaniesService with caching and proper error handling
            logger.debug(f"Fetching company data for GEMI number: {normalized_gemi}")
            company = self.companies.get_company(normalized_gemi)
            logger.info(
                f"Successfully retrieved company data for GEMI number: {normalized_gemi}"
            )
            return company

        except GemiAPIError:
            # Re-raise our custom exceptions as-is
            raise
        except Exception as e:
            logger.error(f"Unexpected error fetching company {normalized_gemi}: {e}")
            raise GemiAPIError(f"Unexpected error: {e}", None) from e

    def _validate_and_normalize_gemi(self, arithmos_gemi: Union[str, int]) -> str:
        """
        Validate and normalize the GEMI registration number.

        Args:
            arithmos_gemi: GEMI number as string or integer

        Returns:
            str: Normalized GEMI number as string

        Raises:
            GemiValidationError: If the GEMI number is invalid
        """
        if arithmos_gemi is None:
            raise GemiValidationError(
                "GEMI registration number cannot be None",
                None,
                {"parameter": "arithmos_gemi", "value": None},
            )

        # Convert to string and validate
        gemi_str = str(arithmos_gemi).strip()

        if not gemi_str:
            raise GemiValidationError(
                "GEMI registration number cannot be empty",
                None,
                {"parameter": "arithmos_gemi", "value": arithmos_gemi},
            )

        # Check if it contains only digits
        if not gemi_str.isdigit():
            raise GemiValidationError(
                "GEMI registration number must contain only digits",
                None,
                {"parameter": "arithmos_gemi", "value": arithmos_gemi},
            )

        # Convert to int and back to string to remove leading zeros
        try:
            gemi_int = int(gemi_str)
            if gemi_int <= 0:
                raise GemiValidationError(
                    "GEMI registration number must be a positive integer",
                    None,
                    {"parameter": "arithmos_gemi", "value": arithmos_gemi},
                )
            return str(gemi_int)
        except ValueError as e:
            raise GemiValidationError(
                f"Invalid GEMI registration number format: {e}",
                None,
                {"parameter": "arithmos_gemi", "value": arithmos_gemi},
            ) from e

    def get_rate_limit_status(self) -> dict:
        """Get current rate limiting status."""
        return self._base_client.get_rate_limit_status()

    def search_companies(
        self,
        gemh_number: Optional[str] = None,
        vat_number: Optional[str] = None,
        name: Optional[str] = None,
        local_office_id: Optional[int] = None,
        kad: Optional[str] = None,
        status: Optional[str] = None,
        prefecture_id: Optional[int] = None,
        municipality_id: Optional[int] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> Union[
        List[CompanySummary], PaginatedResponse[CompanySummary]
    ]:  # Add return type
        """
        Search for companies using various criteria. All parameters are optional filters.
        Returns paginated results if page parameters are provided.

        Args:
            gemh_number: GEMI registration number.
            vat_number: VAT number (AFM).
            name: Company name.
            local_office_id: Local GEMI office ID.
            kad: Activity code.
            status: Company status.
            prefecture_id: Prefecture ID.
            municipality_id: Municipality ID.
            page: Page number for pagination.
            page_size: Number of results per page.

        Returns:
            List[CompanySummary] or PaginatedResponse[CompanySummary]
        """
        return self.companies.search_companies(
            gemh_number=gemh_number,
            vat_number=vat_number,
            name=name,
            local_office_id=local_office_id,
            kad=kad,
            status=status,
            prefecture_id=prefecture_id,
            municipality_id=municipality_id,
            page=page,
            page_size=page_size,
        )
