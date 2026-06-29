"""
Browse API Views

Alphabetical entity browsing with letter filtering and offset-based pagination.
Covers all 6 browsable entity types: organization, unit, signer, company,
companyperson, afmentity.
"""

from core.constants.search_service import BROWSABLE_ENTITY_TYPES
from core.services.browse_service import BrowseService
from core.decorators.cache_decorator import cached_view
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response


class _BrowsePermission(permissions.BasePermission):
    """Allow anonymous access in DEBUG mode, require auth otherwise.

    Evaluated per request so toggling settings.DEBUG takes effect without
    a process reload.
    """

    def has_permission(self, request, view):
        if settings.DEBUG:
            return True
        return request.user and request.user.is_authenticated


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "type",
            openapi.IN_QUERY,
            description=f"Entity type to browse. One of: {', '.join(BROWSABLE_ENTITY_TYPES)}",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "letter",
            openapi.IN_QUERY,
            description="First-letter filter (Greek or Latin, case-insensitive)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "q",
            openapi.IN_QUERY,
            description="Free-text substring filter (e.g. 'ΚΑΠΟΔΙΣΤΡΙΑΚΟ' matches 'ΕΘΝΙΚΟ & ΚΑΠΟΔΙΣΤΡΙΑΚΟ ΠΑΝΕΠΙΣΤΗΜΙΟ ΑΘΗΝΩΝ'). "
                        "Applied on top of letter filtering. Case-insensitive.",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "sort",
            openapi.IN_QUERY,
            description="Sort direction: 'asc' (default) or 'desc'",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Pagination offset (0-based)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Page size (max 200, default 50)",
            type=openapi.TYPE_INTEGER,
            required=False,
        ),
    ],
)
@cached_view(
    cache_prefix="browse",
    cache_params=None,  # include all present query params in cache key
    ttl=60 * 60 * 24,  # 24h — data only changes on daily import
    should_cache_fn=lambda req: not req.GET.get("q"),  # skip free-text searches
)
@api_view(["GET"])
@permission_classes([_BrowsePermission])
def browse_entities_api(request):
    """
    Browse entities alphabetically with letter filtering and pagination.

    Returns a paginated list of entities sorted alphabetically by their display
    name. Supports filtering by first letter, sorting direction, and
    offset-based pagination.

    Entity types:
        - all: All entity types merged together (default)
        - organization: Organizations only
        - unit: Units only
        - signer: Signers only
        - company: Companies only
        - companyperson: Company persons only
        - afmentity: AFM entities only

    Response format:
        {
            "results": [
                {"id": "...", "text": "Display Name", "type": "organization",
                 "sort_key": "display name"}
            ],
            "has_more": bool,
            "total_count": int,
            "available_letters": ["Α", "Β", "Γ", ...]
        }
    """
    entity_type = request.GET.get("type", "all")
    letter = request.GET.get("letter", None)
    query = request.GET.get("q", None)
    sort = request.GET.get("sort", "asc")

    # Validate sort
    if sort not in ("asc", "desc"):
        return Response(
            {"error": "sort must be 'asc' or 'desc'"},
            status=400,
        )

    # Validate entity_type
    if entity_type not in BROWSABLE_ENTITY_TYPES:
        return Response(
            {
                "error": f"Invalid entity type '{entity_type}'. "
                f"Valid types: {', '.join(BROWSABLE_ENTITY_TYPES)}"
            },
            status=400,
        )

    # Parse pagination params — return 400 (not 500) on bad input
    try:
        offset = int(request.GET.get("offset", 0))
        limit = int(request.GET.get("limit", 50))
    except (TypeError, ValueError):
        return Response(
            {"error": "offset and limit must be integers"},
            status=400,
        )
    if offset < 0 or limit < 0:
        return Response(
            {"error": "offset and limit must be non-negative"},
            status=400,
        )
    limit = min(limit, 200)

    try:
        service = BrowseService()
        results = service.browse_entities(
            entity_type=entity_type,
            letter=letter,
            query=query,
            sort=sort,
            offset=offset,
            limit=limit,
        )
        return Response(results)
    except ValueError as e:
        return Response({"error": str(e)}, status=400)
