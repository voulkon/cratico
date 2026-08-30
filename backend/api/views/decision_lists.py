"""
Top-N Decision List Views

Dedicated, cacheable endpoints for DashboardGrid sections that show filtered,
amount-sorted lists of decisions within a date range.

Unlike the general-purpose ``/decisions/unified/?view=decisions`` (which is NOT
cached because params vary too widely), these endpoints have **deterministic
params** (fixed filter, fixed sort, fixed page_size) — so they can be cached
and pre-warmed by the post-import orchestrator.

Endpoints
─────────
  GET /api/decisions/top-payments/
    Decisions of type "Β.2.2" (expenditure/payment), sorted by amount desc.

  GET /api/decisions/top-direct-assignments/
    Decisions classified as direct assignments, sorted by amount desc.

  GET /api/decisions/top-by-amount/
    All decisions sorted by amount desc — replaces the uncached
    ``unified?view=decisions`` that DecisionsSection used previously.

Pattern
───────
  Each endpoint follows the same structure as ``da_top_pairs``:
    ┌─ @swagger_auto_schema
    ├─ @cached_view(cache_prefix=…, defer_on_miss=False)
    ├─ @api_view(["GET"])
    ├─ Parse + validate date range
    ├─ Delegate to compute_* function in analytics_precalc_service
    └─ Return Response(…)

  The compute_* functions are the single source of truth — shared by both
  the view (on cache miss) and the warmup task (to pre-populate).

  Note: these views do NOT use ``defer_on_miss``.  They are paginated with
  ``limit``/``offset`` and the DashboardGrid sections infinite-scroll, so a
  cache miss for any page must compute synchronously and cache the result
  (the queries are bounded by limit/offset and cheap).  ``defer_on_miss``
  would return 202 for every page beyond the pre-warmed ``offset=0`` and
  stall the scroll for ~30s per page.
"""

from core.decorators.cache_decorator import cached_view
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response

from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_date_range(request):
    """
    Parse required start_date / end_date as YYYY-MM-DD.

    Returns (start_dt, end_dt, start_str, end_str, error_response).
    """
    start_str = (request.GET.get("start_date") or "").strip()
    end_str = (request.GET.get("end_date") or "").strip()

    if not start_str or not end_str:
        return None, None, None, None, Response(
            {"error": "start_date and end_date are required"}, status=400
        )

    start_parsed = parse_date(start_str)
    end_parsed = parse_date(end_str)

    if not start_parsed or not end_parsed:
        return None, None, None, None, Response(
            {"error": "Invalid date format. Use YYYY-MM-DD."}, status=400
        )

    if start_parsed > end_parsed:
        return None, None, None, None, Response(
            {"error": "start_date must be before or equal to end_date"}, status=400
        )

    start_dt = timezone.make_aware(datetime.combine(start_parsed, datetime.min.time()))
    end_dt = timezone.make_aware(datetime.combine(end_parsed, datetime.max.time()))

    return start_dt, end_dt, start_str, end_str, None


# ---------------------------------------------------------------------------
# Shared swagger params
# ---------------------------------------------------------------------------

_DATE_PARAMS = [
    openapi.Parameter(
        "start_date",
        openapi.IN_QUERY,
        description="Start date (YYYY-MM-DD)",
        type=openapi.TYPE_STRING,
        required=True,
    ),
    openapi.Parameter(
        "end_date",
        openapi.IN_QUERY,
        description="End date (YYYY-MM-DD)",
        type=openapi.TYPE_STRING,
        required=True,
    ),
    openapi.Parameter(
        "limit",
        openapi.IN_QUERY,
        description="Max results to return",
        type=openapi.TYPE_INTEGER,
        default=5,
    ),
    openapi.Parameter(
        "offset",
        openapi.IN_QUERY,
        description="Pagination offset",
        type=openapi.TYPE_INTEGER,
        default=0,
    ),
]


# ---------------------------------------------------------------------------
# top-payments
# ---------------------------------------------------------------------------

@swagger_auto_schema(
    method="get",
    operation_description="Top payment (Β.2.2) decisions sorted by amount desc",
    manual_parameters=_DATE_PARAMS,
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="top_payments",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
def top_payments_api(request):
    """
    Return the highest-amount payment (Β.2.2) decisions in a date range.

    Used by the DashboardGrid's "Highest Payments" section.
    """
    start_dt, end_dt, start_str, end_str, err = _parse_date_range(request)
    if err is not None:
        return err

    limit = int(request.GET.get("limit", 5))
    offset = int(request.GET.get("offset", 0))

    from core.services.analytics_precalc_service import compute_top_payments

    return Response(
        compute_top_payments(
            start_dt=start_dt,
            end_dt=end_dt,
            start_date_str=start_str,
            end_date_str=end_str,
            limit=limit,
            offset=offset,
        )
    )


# ---------------------------------------------------------------------------
# top-direct-assignments
# ---------------------------------------------------------------------------

@swagger_auto_schema(
    method="get",
    operation_description="Top direct-assignment decisions sorted by amount desc",
    manual_parameters=_DATE_PARAMS,
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="top_direct_assignments",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
def top_direct_assignments_api(request):
    """
    Return the highest-amount direct-assignment decisions in a date range.

    Used by the DashboardGrid's "Highest Direct Assignments" section.
    """
    start_dt, end_dt, start_str, end_str, err = _parse_date_range(request)
    if err is not None:
        return err

    limit = int(request.GET.get("limit", 5))
    offset = int(request.GET.get("offset", 0))

    from core.services.analytics_precalc_service import compute_top_direct_assignments

    return Response(
        compute_top_direct_assignments(
            start_dt=start_dt,
            end_dt=end_dt,
            start_date_str=start_str,
            end_date_str=end_str,
            limit=limit,
            offset=offset,
        )
    )


# ---------------------------------------------------------------------------
# top-by-amount
# ---------------------------------------------------------------------------

@swagger_auto_schema(
    method="get",
    operation_description="Highest-amount decisions (all types) sorted by amount desc",
    manual_parameters=_DATE_PARAMS,
)
@api_view(["GET"])
@permission_classes([PublicReadOnly])
@cached_view(
    cache_prefix="top_by_amount",
    cache_params=["start_date", "end_date", "limit", "offset"],
    end_date_param="end_date",
)
def top_by_amount_api(request):
    """
    Return the highest-amount decisions (all types) in a date range.

    Used by the DashboardGrid's "Largest Decisions" section (formerly
    "Notable Recent Decisions", which hit the uncached unified endpoint).
    """
    start_dt, end_dt, start_str, end_str, err = _parse_date_range(request)
    if err is not None:
        return err

    limit = int(request.GET.get("limit", 5))
    offset = int(request.GET.get("offset", 0))

    from core.services.analytics_precalc_service import compute_top_by_amount

    return Response(
        compute_top_by_amount(
            start_dt=start_dt,
            end_dt=end_dt,
            start_date_str=start_str,
            end_date_str=end_str,
            limit=limit,
            offset=offset,
        )
    )
