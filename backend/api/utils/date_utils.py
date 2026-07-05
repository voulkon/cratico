from datetime import datetime

from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from loguru import logger
from rest_framework.response import Response


def _parse_optional_date_range(request):
    """
    Parse optional start_date and end_date from request query parameters.

    Unlike _parse_and_validate_date_range, this accepts YYYY-MM-DD format
    (parse_date) and makes both dates optional.  Returns timezone-aware
    datetime objects ready for queryset filtering.

    Args:
        request: Django request object

    Returns:
        Tuple of (start_dt, end_dt, error_response)
        - start_dt: timezone-aware datetime (start of day) or None
        - end_dt: timezone-aware datetime (end of day) or None
        - error_response: Response on parse error, or None on success
    """
    start_date_str = request.GET.get("start_date", "")
    end_date_str = request.GET.get("end_date", "")

    start_dt = None
    end_dt = None

    if start_date_str:
        parsed = parse_date(start_date_str)
        if not parsed:
            return (
                None,
                None,
                Response(
                    {"error": "Invalid start_date format. Use YYYY-MM-DD."},
                    status=400,
                ),
            )
        start_dt = timezone.make_aware(datetime.combine(parsed, datetime.min.time()))

    if end_date_str:
        parsed = parse_date(end_date_str)
        if not parsed:
            return (
                None,
                None,
                Response(
                    {"error": "Invalid end_date format. Use YYYY-MM-DD."},
                    status=400,
                ),
            )
        end_dt = timezone.make_aware(datetime.combine(parsed, datetime.max.time()))

    return start_dt, end_dt, None


def _parse_and_validate_date_range(request, context_label: str = None):
    """
    Parse and validate start_date and end_date from request query parameters.

    Args:
        request: Django request object
        context_label: Optional label for logging context (e.g., organization UID, entity AFM)

    Returns:
        Tuple of (start_date, end_date, error_response)
        - If successful: (date, date, None)
        - If error: (None, None, Response)
    """
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")

    # Validate required parameters
    if not start_date_str or not end_date_str:
        return (
            None,
            None,
            Response({"error": "start_date and end_date are required"}, status=400),
        )

    try:
        # Parse datetime strings (ISO 8601 format) and extract date component
        start_datetime = parse_datetime(start_date_str)
        end_datetime = parse_datetime(end_date_str)

        if start_datetime is None or end_datetime is None:
            return (
                None,
                None,
                Response(
                    {
                        "error": "Invalid date format. Expected ISO 8601 format (e.g., '2025-12-22T16:27:17.386689Z')"
                    },
                    status=400,
                ),
            )

        start_date = start_datetime.date()
        end_date = end_datetime.date()
    except (ValueError, AttributeError) as e:
        return (
            None,
            None,
            Response({"error": f"Invalid date format: {str(e)}"}, status=400),
        )

    # Validate date range
    if start_date > end_date:
        return (
            None,
            None,
            Response(
                {"error": "start_date must be before or equal to end_date"}, status=400
            ),
        )

    # Warn on large date ranges
    if (end_date - start_date).days > 365:
        context_info = f" for {context_label}" if context_label else ""
        logger.warning(
            f"Large date range requested{context_info}: "
            f"{start_date} to {end_date} ({(end_date - start_date).days} days)"
        )

    return start_date, end_date, None


# ── Temporal exploration date-range limit ─────────────────────────────
# We restrict temporal exploration to single day, week, or month
# to ensure all queries hit the issue_date_day / issue_date_month
# indexes and stay fast even on large datasets.
TEMPORAL_MAX_SPAN_DAYS = 32  # allows a full month (31 days) + 1 for inclusive


def _validate_temporal_span(start_dt, end_dt, bucket=None):
    """
    Validate that the requested date span is within allowed bounds for
    temporal exploration.

    Returns ``None`` on success or a ``Response`` (status 400) on failure.

    Bucket limits (optional — used only when the caller knows the URL
    bucket type and wants stricter enforcement):
      - day:   exactly 1 day
      - week:  ≤ 7 days
      - month: ≤ 31 days
      - None:  ≤ TEMPORAL_MAX_SPAN_DAYS (32) — the default fallback used
               by endpoints that don't receive an explicit bucket
               parameter.  This permits day/week/month URLs while still
               rejecting arbitrary multi-month ranges.
    """
    if start_dt is None or end_dt is None:
        return None  # no validation needed when dates are missing

    span = (end_dt.date() - start_dt.date()).days

    limits = {"day": 1, "week": 7, "month": 31}
    max_span = limits.get(bucket) if bucket else TEMPORAL_MAX_SPAN_DAYS

    if span > max_span:
        bucket_label = f"bucket={bucket}" if bucket else "temporal exploration"
        return Response(
            {
                "error": (
                    f"Date span too large for {bucket_label}. "
                    f"Max {max_span} day(s) allowed, got {span} days. "
                    f"Use /explore/temporal/<date>, /explore/week/<year>/<week>, "
                    f"or /explore/month/<year>/<month> for larger windows."
                )
            },
            status=400,
        )
    return None
