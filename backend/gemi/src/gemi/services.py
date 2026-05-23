from typing import List, Optional, Union

from .base_client import BaseAPIClient
from .cache import CachedClient, MemoryCache
from .logging_utils import log_api_call
from .pagination import PaginatedResponse, Paginator
from .schemas.company import CompanyResponse, CompanySummary


class CompaniesService(CachedClient):
    """Service class for company search and detail endpoints."""

    def __init__(self, base_client: BaseAPIClient, cache=None):
        super().__init__(
            cache or MemoryCache(default_ttl=300)
        )  # 5 min cache for company data
        self.client = base_client

    @log_api_call
    def get_company(self, gemh_number: str) -> CompanyResponse:
        """
        Retrieve full public data for a company by its GEMI number.
        """
        endpoint = f"companies/{gemh_number}"

        def fetch_func():
            data = self.client.get(endpoint)
            return CompanyResponse(**data)

        # Cache company details for 5 minutes
        return self._get_cached_or_fetch(endpoint, None, fetch_func, ttl=300)

    @log_api_call
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
    ) -> Union[List[CompanySummary], PaginatedResponse[CompanySummary]]:
        """
        Search for companies using various criteria. All parameters are optional filters.
        Returns paginated results if page parameters are provided.
        """
        params = {
            "gemhNumber": gemh_number,
            "afm": vat_number,
            "name": name,
            "localOfficeId": local_office_id,
            "kad": kad,
            "status": status,
            "prefectureId": prefecture_id,
            "municipalityId": municipality_id,
            "page": page,
            "pageSize": page_size,
        }
        # Remove None values
        params = {k: v for k, v in params.items() if v is not None}

        data = self.client.get("companies", params=params)

        # Check if response has searchResults (paginated format)
        if isinstance(data, dict) and "searchResults" in data:
            # Paginated response with searchResults and searchMetadata
            items = [
                CompanySummary.model_validate(item) for item in data["searchResults"]
            ]
            metadata = data.get("searchMetadata", {})

            return PaginatedResponse[CompanySummary](
                items=items,
                total_count=metadata.get("totalCount"),
                page=page,
                page_size=page_size,
                has_next=(metadata.get("resultsOffset", 0) + len(items))
                < metadata.get("totalCount", 0),
                has_previous=metadata.get("resultsOffset", 0) > 0,
            )
        else:
            # Simple list response
            return [CompanySummary.model_validate(item) for item in data]

    def search_companies_iter(self, **kwargs) -> Paginator[CompanySummary]:
        """
        Get an iterator for paginated company search results.
        """

        def fetch_func(params):
            return self.search_companies(**params)

        return Paginator(fetch_func, kwargs, kwargs.get("page_size", 20))


class ReferenceDataService(CachedClient):
    """Service class for retrieving reference (parametric) data lists."""

    def __init__(self, base_client: BaseAPIClient):
        self.client = base_client


#     def get_local_offices(self) -> List[LocalOffice]:
#         """Get the list of local GEMI registry offices (Chambers)."""
#         data = self.client.get("localOffices")
#         return [LocalOffice.parse_obj(item) for item in data]

#     def get_prefectures(self) -> List[Prefecture]:
#         """Get the list of regional units (Nomoi)."""
#         data = self.client.get("prefectures")
#         return [Prefecture.parse_obj(item) for item in data]

#     def get_municipalities(self) -> List[Municipality]:
#         """Get the list of municipalities."""
#         data = self.client.get("municipalities")
#         return [Municipality.parse_obj(item) for item in data]

#     def get_business_statuses(self) -> List[BusinessStatus]:
#         """Get the list of possible business status values."""
#         data = self.client.get("businessStatuses")
#         return [BusinessStatus.parse_obj(item) for item in data]

#     def get_legal_forms(self) -> List[LegalForm]:
#         """Get the list of legal forms of companies."""
#         data = self.client.get("legalForms")
#         return [LegalForm.parse_obj(item) for item in data]

#     def get_organ_types(self) -> List[OrganType]:
#         """Get the list of company organ types."""
#         data = self.client.get("organTypes")
#         return [OrganType.parse_obj(item) for item in data]

#     def get_document_types(self) -> List[DocumentType]:
#         """Get the list of document types available."""
#         data = self.client.get("documentTypes")
#         return [DocumentType.parse_obj(item) for item in data]

#     def get_decision_types(self) -> List[DecisionType]:
#         """Get the list of decision types."""
#         data = self.client.get("decisionTypes")
#         return [DecisionType.parse_obj(item) for item in data]
