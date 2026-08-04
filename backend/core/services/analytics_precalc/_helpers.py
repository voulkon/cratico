"""
Shared helpers for analytics pre-calculation.

Used by all domain modules to convert dates into timezone-aware
datetimes and access the shared response cache.
"""

from datetime import date, datetime

from django.utils import timezone
from django.utils.dateparse import parse_date

from core.services.response_cache_service import response_cache

__all__ = [
    "_make_aware_start",
    "_make_aware_end",
    "_validate_dates",
    "parse_date",
    "response_cache",
]


def _make_aware_start(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _make_aware_end(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.max.time()))


def _validate_dates(start_date_str: str, end_date_str: str, caller: str) -> None:
    """Raise ValueError if either date string fails to parse."""
    if not parse_date(start_date_str) or not parse_date(end_date_str):
        raise ValueError(
            f"{caller}: invalid date strings "
            f"({start_date_str!r}, {end_date_str!r})"
        )
