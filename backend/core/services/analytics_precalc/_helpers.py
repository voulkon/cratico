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
    "parse_date",
    "response_cache",
]


def _make_aware_start(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.min.time()))


def _make_aware_end(d: date) -> datetime:
    return timezone.make_aware(datetime.combine(d, datetime.max.time()))
