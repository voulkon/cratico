"""Custom exceptions for the GEMI API client."""

from typing import Any, Dict, Optional

import requests


class GemiAPIError(Exception):
    """Base exception for all GEMI API related errors."""

    def __init__(self, message: str, response: Optional[requests.Response] = None):
        super().__init__(message)
        self.response = response
        self.status_code = response.status_code if response else None

        # Preserve original response content for debugging
        if response is not None:
            try:
                self.response_data = response.json()
            except (ValueError, TypeError):
                self.response_data = response.text
        else:
            self.response_data = None

    def get_api_error_details(self) -> Dict[str, Any]:
        """Get detailed error information from the API response."""
        return {
            "status_code": self.status_code,
            "message": str(self),
            "response_data": self.response_data,
            "headers": dict(self.response.headers) if self.response else None,
        }


class GemiAuthenticationError(GemiAPIError):
    """Raised when API key is invalid or authentication fails."""


class GemiRateLimitError(GemiAPIError):
    """Raised when API rate limit is exceeded."""

    def __init__(
        self,
        message: str,
        response: Optional[requests.Response] = None,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message, response)
        self.retry_after = retry_after


class GemiValidationError(GemiAPIError):
    """Raised when request parameters are invalid."""

    def __init__(
        self,
        message: str,
        response: Optional[requests.Response] = None,
        validation_errors: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message, response)
        self.validation_errors = validation_errors or {}


class GemiNotFoundError(GemiAPIError):
    """Raised when requested resource is not found."""


class GemiServerError(GemiAPIError):
    """Raised when server returns 5xx errors."""


class GemiConnectionError(GemiAPIError):
    """Raised when connection to API fails."""


class GemiTimeoutError(GemiAPIError):
    """Raised when request times out."""
