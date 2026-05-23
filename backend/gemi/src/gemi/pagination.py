"""Pagination utilities for the GEMI API client."""

from typing import Any, Dict, Generic, Iterator, List, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: List[T] = Field(default_factory=list)
    total_count: Optional[int] = Field(None, alias="totalCount")
    page: int = Field(1, alias="page")
    page_size: int = Field(20, alias="pageSize")
    has_next: bool = Field(False, alias="hasNext")
    has_previous: bool = Field(False, alias="hasPrevious")

    @property
    def total_pages(self) -> Optional[int]:
        """Calculate total number of pages."""
        if self.total_count is None or self.page_size <= 0:
            return None
        return (self.total_count + self.page_size - 1) // self.page_size


class PaginationParams(BaseModel):
    """Parameters for pagination."""

    page: int = Field(1, ge=1, description="Page number (1-based)")
    page_size: int = Field(20, ge=1, le=100, description="Number of items per page")

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API parameters."""
        return {"page": self.page, "pageSize": self.page_size}


class Paginator(Generic[T]):
    """Iterator for paginated API responses."""

    def __init__(self, fetch_func, initial_params: Dict[str, Any], page_size: int = 20):
        """
        Initialize paginator.

        Args:
            fetch_func: Function to fetch data that accepts parameters and returns paginated response
            initial_params: Initial parameters for the API call
            page_size: Number of items per page
        """
        self.fetch_func = fetch_func
        self.initial_params = initial_params
        self.page_size = page_size
        self.current_page = 1
        self._current_response: Optional[PaginatedResponse[T]] = None
        self._exhausted = False

    def __iter__(self) -> Iterator[T]:
        """Iterate through all items across all pages."""
        self.current_page = 1
        self._exhausted = False

        while not self._exhausted:
            response = self._fetch_page(self.current_page)

            for item in response.items:
                yield item

            if not response.has_next:
                self._exhausted = True
            else:
                self.current_page += 1

    def _fetch_page(self, page: int) -> PaginatedResponse[T]:
        """Fetch a specific page."""
        params = self.initial_params.copy()
        params.update({"page": page, "pageSize": self.page_size})
        return self.fetch_func(params)

    def get_page(self, page: int) -> PaginatedResponse[T]:
        """Get a specific page of results."""
        return self._fetch_page(page)

    def all(self) -> List[T]:
        """Get all items from all pages as a list."""
        return list(self)
