"""Base scraper client with HTTP capabilities and rate limiting."""

import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import requests

from .constants import (
    DEFAULT_MAX_RETRIES,
    DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE,
    DEFAULT_TIMEOUT,
)
from .exceptions import PothenNetworkError, PothenRateLimitError, PothenScrapingError

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter to control request frequency."""

    def __init__(
        self, requests_per_minute: int = DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE
    ):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0.0

    def wait_if_needed(self) -> None:
        """Wait if necessary to respect rate limits."""
        current_time = time.time()
        elapsed = current_time - self.last_request_time

        if elapsed < self.min_interval:
            sleep_time = self.min_interval - elapsed
            logger.debug(f"Rate limiting: sleeping for {sleep_time:.2f} seconds")
            time.sleep(sleep_time)

        self.last_request_time = time.time()


class BaseScraperClient:
    """Base HTTP client for scraping operations with rate limiting and error handling."""

    def __init__(
        self,
        timeout: int = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        requests_per_minute: int = DEFAULT_RATE_LIMIT_REQUESTS_PER_MINUTE,
        user_agent: Optional[str] = None,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.rate_limiter = RateLimiter(requests_per_minute)

        # Initialize session with headers
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent or "pothen-scraper/1.0.0",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    def _handle_response_errors(self, response: requests.Response) -> None:
        """Handle HTTP response errors."""
        if response.status_code == 429:
            raise PothenRateLimitError(
                f"Rate limited by server: {response.status_code}"
            )
        elif response.status_code >= 500:
            raise PothenNetworkError(f"Server error: {response.status_code}")
        elif response.status_code >= 400:
            raise PothenScrapingError(
                f"Client error: {response.status_code} - {response.url}"
            )

        response.raise_for_status()

    def get(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> requests.Response:
        """Make a GET request with rate limiting and retry logic."""

        for attempt in range(self.max_retries + 1):
            try:
                self.rate_limiter.wait_if_needed()

                logger.debug(f"GET request to {url} (attempt {attempt + 1})")

                response = self.session.get(
                    url, params=params, headers=headers, timeout=self.timeout, **kwargs
                )

                self._handle_response_errors(response)
                return response

            except requests.exceptions.Timeout as e:
                if attempt == self.max_retries:
                    raise PothenNetworkError(
                        f"Request timeout after {self.max_retries + 1} attempts: {url}"
                    ) from e
                logger.warning(
                    f"Timeout on attempt {attempt + 1} for {url}, retrying..."
                )

            except requests.exceptions.ConnectionError as e:
                if attempt == self.max_retries:
                    raise PothenNetworkError(
                        f"Connection error after {self.max_retries + 1} attempts: {url}"
                    ) from e
                logger.warning(
                    f"Connection error on attempt {attempt + 1} for {url}, retrying..."
                )

            except (PothenRateLimitError, PothenScrapingError):
                # Don't retry on these errors
                raise

            # Exponential backoff for retries
            if attempt < self.max_retries:
                sleep_time = 2**attempt
                logger.debug(f"Retrying in {sleep_time} seconds...")
                time.sleep(sleep_time)

        raise PothenNetworkError(f"Max retries exceeded for {url}")

    def download_file(
        self,
        url: str,
        filepath: Union[str, Path],
        chunk_size: int = 8192,
        max_size_mb: Optional[int] = None,
    ) -> Path:
        """Download a file from URL with streaming and size validation."""
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)

        logger.info(f"Downloading {url} to {filepath}")

        try:
            self.rate_limiter.wait_if_needed()

            response = self.session.get(url, stream=True, timeout=self.timeout)
            self._handle_response_errors(response)

            # Check content length if available
            content_length = response.headers.get("content-length")
            if content_length and max_size_mb:
                size_mb = int(content_length) / (1024 * 1024)
                if size_mb > max_size_mb:
                    raise PothenScrapingError(
                        f"File too large: {size_mb:.1f}MB > {max_size_mb}MB"
                    )

            # Download in chunks
            total_size = 0
            with open(filepath, "wb") as f:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
                        total_size += len(chunk)

                        # Check size during download
                        if max_size_mb and total_size > max_size_mb * 1024 * 1024:
                            filepath.unlink(missing_ok=True)  # Clean up partial file
                            raise PothenScrapingError(
                                f"File too large during download: >{max_size_mb}MB"
                            )

            logger.info(f"Downloaded {total_size} bytes to {filepath}")
            return filepath

        except Exception as e:
            # Clean up partial file on error
            if filepath.exists():
                filepath.unlink(missing_ok=True)
            raise PothenNetworkError(f"Download failed for {url}: {str(e)}") from e

    def close(self) -> None:
        """Close the session."""
        self.session.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
