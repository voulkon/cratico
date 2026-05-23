import logging
import time
from typing import Any, Dict, Optional

import requests

from .constants import DEFAULT_BASE_URL
from .exceptions import (
    GemiAPIError,
    GemiAuthenticationError,
    GemiConnectionError,
    GemiNotFoundError,
    GemiRateLimitError,
    GemiServerError,
    GemiTimeoutError,
    GemiValidationError,
)
from .rate_limiter import SharedRateLimiter

logger = logging.getLogger(__name__)


class BaseAPIClient:
    """Base client for the BusinessPortal OpenData API handling HTTP requests and auth."""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        timeout: int = 30,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")  # Ensure no trailing slash
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries

        # Initialize a session and set the API key in headers for all requests
        self.session = requests.Session()
        self.session.headers.update(
            {
                "api_key": api_key,  # Correct header name from swagger docs
                "User-Agent": "gemi-python-client/1.0.0",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def get_rate_limit_status(self) -> Dict[str, Any]:
        """Get current rate limiting status for this API key."""
        return {
            "requests_last_minute": SharedRateLimiter.get_request_count_last_minute(
                self.api_key
            ),
            "requests_remaining": max(
                0, 8 - SharedRateLimiter.get_request_count_last_minute(self.api_key)
            ),
            "backoff_time": SharedRateLimiter.should_back_off(self.api_key),
        }

    def _extract_api_error_message(self, response: requests.Response) -> str:
        """Extract error message from API response, falling back to status text."""
        try:
            error_data = response.json()
            # Try common error message fields
            for field in ["message", "error", "detail", "error_description"]:
                if field in error_data and error_data[field]:
                    return str(error_data[field])
            # If it's a string response, use it
            if isinstance(error_data, str):
                return error_data
        except (ValueError, TypeError):
            pass

        # Fallback to HTTP status reason
        return response.reason or f"HTTP {response.status_code}"

    def _handle_response_errors(self, response: requests.Response) -> None:
        """Handle HTTP errors and convert them to appropriate custom exceptions."""
        # Always try to extract the actual API error message
        api_message = self._extract_api_error_message(response)

        if response.status_code == 401:
            message = f"Authentication failed: {api_message}"
            raise GemiAuthenticationError(message, response)
        elif response.status_code == 403:
            message = f"Access forbidden: {api_message}"
            raise GemiAuthenticationError(message, response)
        elif response.status_code == 404:
            message = f"Resource not found: {api_message}"
            raise GemiNotFoundError(message, response)
        elif response.status_code == 422:
            # Try to extract validation errors from response
            try:
                error_data = response.json()
                validation_errors = error_data.get("errors", {})
                message = f"Validation failed: {api_message}"
            except:
                validation_errors = {}
                message = f"Validation failed: {api_message}"
            raise GemiValidationError(message, response, validation_errors)
        elif response.status_code == 429:
            # Rate limit exceeded
            retry_after = response.headers.get("Retry-After")
            retry_after = int(retry_after) if retry_after else None
            message = f"Rate limit exceeded: {api_message}"
            raise GemiRateLimitError(message, response, retry_after)
        elif 500 <= response.status_code < 600:
            message = f"Server error ({response.status_code}): {api_message}"
            raise GemiServerError(message, response)
        else:
            response.raise_for_status()  # Let requests handle other HTTP errors

    def _make_request_with_retries(
        self, method: str, url: str, **kwargs
    ) -> requests.Response:
        """Make a request with automatic retries for transient failures."""
        # Check if we should back off due to recent rate limiting
        backoff_time = SharedRateLimiter.should_back_off(self.api_key)
        if backoff_time:
            logger.warning(
                f"Backing off for {backoff_time:.1f}s due to recent rate limiting"
            )
            time.sleep(backoff_time)

        last_exception = None

        for attempt in range(self.max_retries + 1):
            try:
                logger.debug(
                    f"Making {method} request to {url} (attempt {attempt + 1})"
                )
                response = self.session.request(
                    method, url, timeout=self.timeout, **kwargs
                )
                self._handle_response_errors(response)

                # Record successful request for rate limiting tracking
                SharedRateLimiter.record_successful_request(self.api_key)
                return response

            except (
                requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
            ) as e:
                last_exception = e
                if attempt < self.max_retries:
                    wait_time = 2**attempt  # Exponential backoff
                    logger.warning(
                        f"Request failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    if isinstance(e, requests.exceptions.ConnectionError):
                        raise GemiConnectionError(
                            f"Failed to connect to API after {self.max_retries + 1} attempts",
                            None,
                        ) from e
                    else:
                        raise GemiTimeoutError(
                            f"Request timed out after {self.max_retries + 1} attempts",
                            None,
                        ) from e

            except GemiRateLimitError as e:
                # Record the rate limit hit for shared tracking
                SharedRateLimiter.record_429_response(self.api_key, e.retry_after)

                # Handle rate limiting with automatic retry if Retry-After header is present
                if e.retry_after and attempt < self.max_retries:
                    logger.warning(
                        f"Rate limited, waiting {e.retry_after}s before retry"
                    )
                    time.sleep(e.retry_after)
                    continue
                else:
                    raise

            except (
                GemiAuthenticationError,
                GemiNotFoundError,
                GemiValidationError,
            ):
                # Don't retry these errors
                raise

            except requests.exceptions.HTTPError as e:
                # Convert any remaining HTTP errors to our custom exception
                raise GemiAPIError(f"HTTP error: {e}", e.response) from e

        # This shouldn't be reached, but just in case
        if last_exception:
            raise GemiConnectionError(
                "Request failed after all retries", None
            ) from last_exception

    def get(
        self, endpoint: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Perform a GET request to the API and return the parsed JSON data."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"  # construct full URL
        response = self._make_request_with_retries("GET", url, params=params)

        try:
            return response.json()
        except ValueError as e:
            raise GemiAPIError(f"Invalid JSON response from API: {e}", response) from e

    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Perform a POST request to the API and return the parsed JSON data."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        response = self._make_request_with_retries("POST", url, data=data, json=json)

        try:
            return response.json()
        except ValueError as e:
            raise GemiAPIError(f"Invalid JSON response from API: {e}", response) from e
