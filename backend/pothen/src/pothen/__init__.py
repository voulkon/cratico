"""POTHEN Scraper - Greek Parliament Asset Declarations Parser."""

from .client import PothenClient
from .exceptions import (
    PothenError,
    PothenNetworkError,
    PothenParsingError,
    PothenScrapingError,
    PothenValidationError,
)

__version__ = "1.0.0"
__author__ = "Konstantinos Voulgaropoulos"

__all__ = [
    "PothenClient",
    # Exceptions
    "PothenError",
    "PothenScrapingError",
    "PothenParsingError",
    "PothenNetworkError",
    "PothenValidationError",
]
