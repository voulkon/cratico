"""Utility functions for the API."""

# Import commonly used functions to maintain backward compatibility
from .common import get_client_ip
from .date_utils import _parse_optional_date_range, _validate_temporal_span

__all__ = [
    "get_client_ip",
    "_parse_optional_date_range",
    "_validate_temporal_span",
]
