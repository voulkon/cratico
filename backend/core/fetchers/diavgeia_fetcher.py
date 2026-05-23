from typing import List

from diavgeia_api import DiavgeiaClient
from diavgeia_api.models.decisions import Decision
from diavgeia_api.models.dictionaries import (
    DictionariesListResponse,
    DictionaryListItem,
    DictionaryValuesResponse,
)
from diavgeia_api.models.organizations import (
    Organization,
    OrganizationsResponse,
    Position,
    PositionsResponse,
    Signer,
    SignersResponse,
    Unit,
    UnitsResponse,
)
from diavgeia_api.models.search import SearchResponse
from diavgeia_api.models.types import TypeDetails  # Add these imports
from diavgeia_api.models.types import TypeSummaries, TypeSummary
from loguru import logger


class DiavgeiaFetcher:
    """Integration layer: talk to the API and return DTOs. No DB code."""

    _client: DiavgeiaClient | None = None

    @classmethod
    def _get_client(cls) -> DiavgeiaClient:
        if cls._client is None:
            cls._client = DiavgeiaClient()
        return cls._client

    # ————————————————————————————————————————————
    # TODO: Check the type annotation of the return value
    def fetch_organizations(self) -> list[Organization]:
        """Return a list of *validated* Organization DTOs."""
        # The SDK already parses JSON into its Pydantic model
        raw: OrganizationsResponse = self._get_client().get_organizations()
        return raw.organizations

    def fetch_an_organization(self, org_uid) -> Organization:
        """Return a list of *validated* Organization DTOs."""
        # The SDK already parses JSON into its Pydantic model
        raw: OrganizationsResponse = self._get_client().get_organization(org_uid)
        return raw

    def fetch_dictionaries(self) -> DictionaryValuesResponse:
        """Return a list of *validated* Organization DTOs."""
        # The SDK already parses JSON into its Pydantic model
        raw: DictionariesListResponse = self._get_client().get_dictionaries()
        return raw.dictionaries

    def fetch_dictionary_items(self, uid) -> list[DictionaryListItem]:
        """Return a list of *validated* Organization DTOs."""
        # The SDK already parses JSON into its Pydantic model
        raw = self._get_client().get_dictionary(uid=uid)
        return raw.items

    def fetch_organization_units(self, organization_uid: str) -> list[Unit]:
        """Return a list of validated Unit DTOs for an organization."""
        raw: UnitsResponse = self._get_client().get_organization_units(
            organization_id=organization_uid
        )
        return raw.units

    def fetch_organization_positions(self, organization_uid: str) -> list[Position]:
        """Return a list of validated Position DTOs for an organization."""
        raw: PositionsResponse = self._get_client().get_organization_positions(
            organization_id=organization_uid
        )
        return raw.positions

    def fetch_organization_signers(self, organization_uid: str) -> list[Signer]:
        """Return a list of validated Signer DTOs for an organization."""
        raw: SignersResponse = self._get_client().get_organization_signers(
            organization_id=organization_uid
        )
        return raw.signers

    def fetch_a_decision(self, ada) -> Decision:
        raw: Decision = self._get_client().get_a_decision(ada)
        return raw

    def fetch_a_unit(self, unit_id) -> Unit:
        from diavgeia_api._config import UNITS

        raw: Unit = self._get_client()._get_and_parse(Unit, UNITS, unit_id)
        return raw

    def fetch_decisions(self, **kwargs) -> SearchResponse | None:
        """
        Fetches a page of decisions based on search criteria.

        Returns:
            The full SearchResponse object containing decisions and search info,
            or None if the request fails.
        """
        try:
            # Filter out internal parameters that aren't part of the API
            # These are used by our code but shouldn't be passed to DiavgeiaClient
            # TODO: Ideally, these values should be centralized in a constant or config to avoid hardcoding here
            internal_params = {"force", "chunk_size", "job_id"}
            api_kwargs = {k: v for k, v in kwargs.items() if k not in internal_params}

            # Assuming the client method handles potential errors or returns None/empty on failure
            raw: SearchResponse | None = self._get_client().search_decisions(**api_kwargs)  # type: ignore[no-untyped-call]
            if raw and raw.decisions:  # Check if response is valid and has decisions
                logger.debug(
                    f"Fetched {raw.info.actualSize} decisions (page {raw.info.page}/{raw.info.total // raw.info.size + 1}) for query: {kwargs}"
                )
                return raw
            elif raw:  # Response received but no decisions found for this page/query
                logger.warning(
                    f"No decisions found (page {raw.info.page}) for query: {kwargs}"
                )
                return raw  # Return the response with empty decisions list and info
            else:
                logger.error(
                    f"Failed to fetch decisions for query: {kwargs}. Received None response."
                )
                return None
        except Exception as e:
            logger.error(f"Exception during decision fetch for query {kwargs}: {e}")
            return None

    # ————————————————————————————————————————————
    # New methods for types

    def fetch_all_types(self) -> List[TypeSummary]:
        """Return a list of all available act types as TypeSummary DTOs."""
        try:
            raw: TypeSummaries = self._get_client().get_all_types()
            logger.info(f"Fetched {len(raw.decisionTypes)} act types")
            return raw.decisionTypes
        except Exception as e:
            logger.error(f"Error fetching all types: {e}")
            return []

    def fetch_type_summary(self, type_uid: str) -> TypeSummary | None:
        """Return a TypeSummary DTO for a specific act type."""
        try:
            return self._get_client().get_a_types_summary(types_uid=type_uid)
        except Exception as e:
            logger.error(f"Error fetching type summary for {type_uid}: {e}")
            return None

    def fetch_type_details(self, type_uid: str) -> TypeDetails | None:
        """Return a TypeDetails DTO for a specific act type with extra fields."""
        try:
            return self._get_client().get_a_types_details(types_uid=type_uid)
        except Exception as e:
            logger.error(f"Error fetching type details for {type_uid}: {e}")
            return None

    def fetch_a_signer(self, signer_id: str) -> Signer | None:
        """Return a TypeDetails DTO for a specific act type with extra fields."""
        try:
            return self._get_client().get_specific_signer(signer_id=signer_id)
        except Exception as e:
            logger.error(f"Error fetching signer's details for {signer_id}: {e}")
            return None
