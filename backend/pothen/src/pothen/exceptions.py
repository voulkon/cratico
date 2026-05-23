"""Custom exceptions for the POTHEN scraper package."""


class PothenError(Exception):
    """Base exception for all POTHEN-related errors."""


class PothenScrapingError(PothenError):
    """Exception raised when web scraping operations fail."""


class PothenParsingError(PothenError):
    """Exception raised when parsing HTML or PDF content fails."""


class PothenNetworkError(PothenError):
    """Exception raised when network operations fail."""


class PothenValidationError(PothenError):
    """Exception raised when data validation fails."""


class PothenDownloadError(PothenError):
    """Exception raised when PDF download operations fail."""


class PothenRateLimitError(PothenError):
    """Exception raised when rate limits are exceeded."""
