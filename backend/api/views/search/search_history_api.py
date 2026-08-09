"""
Search History API Endpoints

This module contains all API endpoints related to user search behavior tracking:
- Personal search history
- Recent search queries
- Recently visited items
- Search selection tracking
- History clearing
"""

from api.utils.common import get_client_ip
from core.services.search_history_service import SearchHistoryService
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from api.permissions import AuthenticatedOrDebug
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of history items",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "offset",
            openapi.IN_QUERY,
            description="Offset for pagination",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def personal_search_history_api(request):
    """
    Get personal search history for the current user or IP.

    Returns recent searches in chronological order (newest first).
    For authenticated users, returns their personal history.
    For anonymous users, returns history associated with their IP.
    """
    limit = int(request.GET.get("limit", 20))
    offset = int(request.GET.get("offset", 0))

    service = SearchHistoryService()

    # Get user and IP
    user_id = request.user.id if request.user.is_authenticated else None
    ip_address = get_client_ip(request)

    # Retrieve history
    history = []

    if user_id:
        # Authenticated user: get their history
        history = service.get_user_history(user_id, limit=limit, offset=offset)
    elif ip_address:
        # Anonymous user: get IP history
        history = service.get_ip_history(ip_address, limit=limit, offset=offset)

    # Get statistics
    stats = service.get_history_stats(user_id=user_id, ip_address=ip_address)

    return Response(
        {
            "history": history,
            "count": len(history),
            "limit": limit,
            "offset": offset,
            "stats": stats,
            "user_authenticated": request.user.is_authenticated,
        }
    )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of queries",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def recent_search_queries_api(request):
    """
    Get recent search query strings (for autocomplete/suggestions).

    Returns only the query strings (deduplicated) from the user's history.
    Useful for "continue where you left off" autocomplete functionality.
    """
    limit = int(request.GET.get("limit", 10))

    service = SearchHistoryService()

    user_id = request.user.id if request.user.is_authenticated else None
    ip_address = get_client_ip(request)

    queries = service.get_recent_queries(
        user_id=user_id, ip_address=ip_address, limit=limit, unique=True
    )

    return Response(
        {
            "queries": queries,
            "count": len(queries),
        }
    )


@swagger_auto_schema(
    method="delete",
    operation_description="Delete a single item from search history by timestamp",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["timestamp"],
        properties={
            "timestamp": openapi.Schema(
                type=openapi.TYPE_NUMBER,
                description="Unix timestamp of the item to delete",
            ),
        },
    ),
    responses={
        200: openapi.Response(
            description="Item deleted successfully",
            examples={
                "application/json": {
                    "success": True,
                    "message": "History item deleted successfully",
                }
            },
        ),
        400: "Timestamp is required",
        404: "Item not found",
    },
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_single_history_item_api(request):
    """
    Delete a single item from the user's search history.

    Requires the timestamp of the item to delete (from the history list).
    This allows users to remove specific items without clearing their entire history.
    """
    timestamp = request.data.get("timestamp")

    if not timestamp:
        return Response(
            {"success": False, "message": "Timestamp is required"}, status=400
        )

    try:
        timestamp = float(timestamp)
    except (ValueError, TypeError):
        return Response(
            {"success": False, "message": "Invalid timestamp format"}, status=400
        )

    service = SearchHistoryService()

    user_id = request.user.id if request.user.is_authenticated else None
    ip_address = get_client_ip(request)

    success = service.delete_single_item(
        item_timestamp=timestamp, user_id=user_id, ip_address=ip_address
    )

    if success:
        return Response(
            {"success": True, "message": "History item deleted successfully"}
        )
    else:
        return Response(
            {"success": False, "message": "Failed to delete history item"}, status=500
        )


@swagger_auto_schema(method="post")
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def clear_search_history_api(request):
    """
    Clear the current user's search history.
    Privacy feature - allows users to delete their search history.
    """
    service = SearchHistoryService()

    user_id = request.user.id
    success = service.clear_user_history(user_id)

    if success:
        return Response(
            {"success": True, "message": "Search history cleared successfully"}
        )
    else:
        return Response(
            {"success": False, "message": "Failed to clear search history"}, status=500
        )


@swagger_auto_schema(
    method="get",
    operation_description="Get recently visited items (entities/documents user clicked on from search results). "
    "Returns enriched entity details including name and URL for easy navigation.",
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Maximum number of items",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "unique",
            openapi.IN_QUERY,
            description="Deduplicate by item ID",
            type=openapi.TYPE_BOOLEAN,
        ),
    ],
    responses={
        200: openapi.Response(
            description="List of recently visited items with enriched details",
            examples={
                "application/json": {
                    "visited": [
                        {
                            "query": "ΔΗΜΟΣΙΑ ΕΠ",
                            "normalized_query": "δημοσια επ",
                            "timestamp": 1778594856.1195428,
                            "is_selection": True,
                            "entity_type": "unit",
                            "selected_item_id": "100092757",
                            "selected_item_name": "ΔΗΜΟΣΙΑ ΕΠΙΧΕΙΡΗΣΗ",
                            "selected_item_url": "/entity/unit/100092757",
                        }
                    ],
                    "count": 1,
                }
            },
        )
    },
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def recently_visited_api(request):
    """
    Get recently visited items from search selections.

    Returns only items that were actually clicked (is_selection=True),
    with full details (name, URL, type) for easy revisiting.

    Entity details are automatically enriched from the database if missing,
    so this works even for items tracked before the name/URL fields were added.

    Perfect for "Recently Visited" or "Continue Where You Left Off" features.
    """
    limit = int(request.GET.get("limit", 10))
    unique = request.GET.get("unique", "true").lower() in ("true", "1", "t", "yes")

    service = SearchHistoryService()

    user_id = request.user.id if request.user.is_authenticated else None
    ip_address = get_client_ip(request)

    visited = service.get_recently_visited(
        user_id=user_id, ip_address=ip_address, limit=limit, unique=unique
    )

    return Response(
        {
            "visited": visited,
            "count": len(visited),
        }
    )


@swagger_auto_schema(
    method="post",
    operation_description="Track a search result selection (when user clicks on a search result)",
    request_body=openapi.Schema(
        type=openapi.TYPE_OBJECT,
        required=["query"],
        properties={
            "query": openapi.Schema(
                type=openapi.TYPE_STRING, description="The search query that was used"
            ),
            "result_type": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Type of result selected (e.g., organization, signer, document)",
            ),
            "result_id": openapi.Schema(
                type=openapi.TYPE_STRING, description="ID of the selected result"
            ),
            "result_name": openapi.Schema(
                type=openapi.TYPE_STRING,
                description="Name/title of the selected result",
            ),
            "result_url": openapi.Schema(
                type=openapi.TYPE_STRING, description="URL path to the selected result"
            ),
        },
    ),
    responses={200: "Selection tracked successfully"},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def track_search_selection_api(request):
    """
    Track when a user clicks on a search result.

    This is used to record search selections separately from typed queries,
    allowing the feature flag SEARCH_HISTORY_RECORDING_MODE to control
    whether we track all keystrokes or just final selections.

    Stores the selected item details (ID, name, URL) so users can easily
    revisit items from their search history.
    """
    query = request.data.get("query", "").strip()
    result_type = request.data.get("result_type")
    result_id = request.data.get("result_id")
    result_name = request.data.get("result_name")
    result_url = request.data.get("result_url")

    if not query:
        return Response({"success": False, "message": "Query is required"}, status=400)

    try:
        service = SearchHistoryService()

        user_id = request.user.id if request.user.is_authenticated else None
        ip_address = get_client_ip(request)

        # Track the search with is_selection=True and item details
        service.track_search(
            query=query,
            user_id=user_id,
            ip_address=ip_address,
            entity_type=result_type,
            is_selection=True,
            selected_item_id=result_id,
            selected_item_name=result_name,
            selected_item_url=result_url,
        )

        return Response({"success": True, "message": "Selection tracked successfully"})
    except Exception as e:
        from loguru import logger

        logger.error(f"Failed to track search selection: {e}")
        return Response(
            {"success": False, "message": "Failed to track selection"}, status=500
        )
