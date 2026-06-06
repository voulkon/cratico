from django.utils.dateparse import parse_datetime
from loguru import logger
from rest_framework.response import Response

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
