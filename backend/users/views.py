from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from users.models import Bookmark, BookmarkFolder, SearchHistory, _generate_public_slug


class UserDataViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    # ============ BOOKMARK FOLDERS ============

    @action(detail=False, methods=["get", "post"])
    def folders(self, request):
        """List all folders or create a new one"""
        if request.method == "GET":
            folders = BookmarkFolder.objects.filter(user=request.user).prefetch_related(
                "bookmarks"
            )
            return Response(
                [
                    {
                        "id": f.id,
                        "name": f.name,
                        "description": f.description,
                        "color": f.color,
                        "icon": f.icon,
                        "parent_id": f.parent_id,
                        "bookmark_count": f.bookmarks.count(),
                        "is_public": f.is_public,
                        "public_slug": f.public_slug,
                        "created_at": f.created_at,
                        "updated_at": f.updated_at,
                    }
                    for f in folders
                ]
            )

        elif request.method == "POST":
            data = request.data
            folder = BookmarkFolder.objects.create(
                user=request.user,
                name=data["name"],
                description=data.get("description", ""),
                color=data.get("color", "#3b82f6"),
                icon=data.get("icon", ""),
                parent_id=data.get("parent_id"),
            )
            return Response(
                {
                    "id": folder.id,
                    "name": folder.name,
                    "description": folder.description,
                    "color": folder.color,
                    "icon": folder.icon,
                    "parent_id": folder.parent_id,
                    "is_public": folder.is_public,
                    "public_slug": folder.public_slug,
                },
                status=status.HTTP_201_CREATED,
            )

    @action(detail=True, methods=["patch", "delete"], url_path="folders")
    def folder_detail(self, request, pk=None):
        """Update or delete a specific folder"""
        folder = get_object_or_404(BookmarkFolder, pk=pk, user=request.user)

        if request.method == "PATCH":
            data = request.data
            if "name" in data:
                folder.name = data["name"]
            if "description" in data:
                folder.description = data["description"]
            if "color" in data:
                folder.color = data["color"]
            if "icon" in data:
                folder.icon = data["icon"]
            if "parent_id" in data:
                folder.parent_id = data["parent_id"]
            if "is_public" in data:
                was_public = folder.is_public
                folder.is_public = data["is_public"]
                if folder.is_public and not was_public:
                    folder.public_created_at = timezone.now()
                    if not folder.public_slug:
                        folder.public_slug = _generate_public_slug()
                elif not folder.is_public:
                    folder.public_created_at = None
                    folder.public_slug = None  # Invalidate old share link

            folder.save()
            return Response({"updated": True})

        elif request.method == "DELETE":
            # Move bookmarks to root (no folder) before deleting
            folder.bookmarks.update(folder=None)
            folder.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

    # ============ BOOKMARKS ============

    @action(detail=False, methods=["get", "post"])
    def bookmarks(self, request):
        """List all bookmarks or create a new one"""
        if request.method == "GET":
            folder_id = request.query_params.get("folder")
            favorites_only = request.query_params.get("favorites") == "true"

            bookmarks = Bookmark.objects.filter(user=request.user)

            if folder_id:
                bookmarks = bookmarks.filter(folder_id=folder_id)
            elif folder_id == "null":
                bookmarks = bookmarks.filter(folder__isnull=True)

            if favorites_only:
                bookmarks = bookmarks.filter(is_favorite=True)

            bookmarks = bookmarks.select_related("folder")[:100]

            return Response(
                [
                    {
                        "id": b.id,
                        "title": b.title,
                        "url": b.url,
                        "notes": b.notes,
                        "folder_id": b.folder_id,
                        "folder_name": b.folder.name if b.folder else None,
                        "view_type": b.view_type,
                        "preview_data": b.preview_data,
                        "is_favorite": b.is_favorite,
                        "visit_count": b.visit_count,
                        "last_visited": b.last_visited,
                        "is_public": b.is_public,
                        "public_slug": b.public_slug,
                        "created_at": b.created_at,
                        "updated_at": b.updated_at,
                    }
                    for b in bookmarks
                ]
            )

        elif request.method == "POST":
            # Check user's limit
            if request.user.bookmarks.count() >= request.user.max_saved_items:
                return Response(
                    {"error": "Maximum bookmarks limit reached"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            data = request.data
            bookmark = Bookmark.objects.create(
                user=request.user,
                title=data["title"],
                url=data["url"],
                notes=data.get("notes", ""),
                folder_id=data.get("folder_id"),
                view_type=data.get("view_type", ""),
                preview_data=data.get("preview_data"),
                is_favorite=data.get("is_favorite", False),
            )

            return Response(
                {"id": bookmark.id, "title": bookmark.title, "url": bookmark.url},
                status=status.HTTP_201_CREATED,
            )

    @action(detail=True, methods=["get", "patch", "delete"], url_path="bookmarks")
    def bookmark_detail(self, request, pk=None):
        """Get, update, or delete a specific bookmark"""
        bookmark = get_object_or_404(Bookmark, pk=pk, user=request.user)

        if request.method == "GET":
            # Track visit
            bookmark.visit_count += 1
            bookmark.last_visited = timezone.now()
            bookmark.save(update_fields=["visit_count", "last_visited"])

            return Response(
                {
                    "id": bookmark.id,
                    "title": bookmark.title,
                    "url": bookmark.url,
                    "notes": bookmark.notes,
                    "folder_id": bookmark.folder_id,
                    "view_type": bookmark.view_type,
                    "preview_data": bookmark.preview_data,
                    "is_favorite": bookmark.is_favorite,
                    "visit_count": bookmark.visit_count,
                    "last_visited": bookmark.last_visited,
                    "is_public": bookmark.is_public,
                    "public_slug": bookmark.public_slug,
                    "created_at": bookmark.created_at,
                    "updated_at": bookmark.updated_at,
                }
            )

        elif request.method == "PATCH":
            data = request.data
            if "title" in data:
                bookmark.title = data["title"]
            if "url" in data:
                bookmark.url = data["url"]
            if "notes" in data:
                bookmark.notes = data["notes"]
            if "folder_id" in data:
                bookmark.folder_id = data["folder_id"]
            if "view_type" in data:
                bookmark.view_type = data["view_type"]
            if "preview_data" in data:
                bookmark.preview_data = data["preview_data"]
            if "is_favorite" in data:
                bookmark.is_favorite = data["is_favorite"]
            if "is_public" in data:
                was_public = bookmark.is_public
                bookmark.is_public = data["is_public"]
                if bookmark.is_public and not was_public:
                    bookmark.public_created_at = timezone.now()
                    if not bookmark.public_slug:
                        bookmark.public_slug = _generate_public_slug()
                elif not bookmark.is_public:
                    bookmark.public_created_at = None
                    bookmark.public_slug = None  # Invalidate old share link

            bookmark.save()
            return Response({"updated": True})

        elif request.method == "DELETE":
            bookmark.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="bookmarks/bulk-move")
    def bulk_move_bookmarks(self, request):
        """Move multiple bookmarks to a folder"""
        bookmark_ids = request.data.get("bookmark_ids", [])
        folder_id = request.data.get("folder_id")

        Bookmark.objects.filter(id__in=bookmark_ids, user=request.user).update(
            folder_id=folder_id
        )

        return Response({"moved": len(bookmark_ids)})

    # ============ SEARCH HISTORY ============

    @action(detail=False, methods=["get"])
    def search_history(self, request):
        history = SearchHistory.objects.filter(user=request.user)[:20]
        return Response(
            [
                {
                    "id": h.id,
                    "query": h.query,
                    "search_type": h.search_type,
                    "results_count": h.results_count,
                    "created_at": h.created_at,
                }
                for h in history
            ]
        )

    # ============ USER PREFERENCES ============

    @action(detail=False, methods=["get"])
    def user_preferences(self, request):
        return Response(
            {
                "theme": request.user.preferred_theme,
                "palette": request.user.preferred_palette,
                "layout": request.user.preferred_layout,
            }
        )

    @action(detail=False, methods=["patch"])
    def update_preferences(self, request):
        user = request.user
        data = request.data

        if "theme" in data:
            user.preferred_theme = data["theme"]
        if "palette" in data:
            user.preferred_palette = data["palette"]
        if "layout" in data:
            user.preferred_layout = data["layout"]

        user.save()
        return Response({"updated": True})


# ============ PUBLIC SHARING ENDPOINTS ============


@api_view(["GET"])
@permission_classes([AllowAny])
def public_shared_bookmark(request, slug):
    """Public endpoint: retrieve a shared bookmark by its slug. No auth required."""
    bookmark = get_object_or_404(Bookmark, public_slug=slug, is_public=True)
    return Response(
        {
            "id": bookmark.id,
            "title": bookmark.title,
            "url": bookmark.url,
            "notes": bookmark.notes,
            "view_type": bookmark.view_type,
            "preview_data": bookmark.preview_data,
            "folder_name": bookmark.folder.name if bookmark.folder else None,
            "created_at": bookmark.created_at,
            "updated_at": bookmark.updated_at,
            "shared_by": bookmark.user.username if hasattr(bookmark.user, "username") else None,
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def public_shared_folder(request, slug):
    """Public endpoint: retrieve a shared folder and its bookmarks by slug. No auth required."""
    folder = get_object_or_404(BookmarkFolder, public_slug=slug, is_public=True)

    bookmarks = folder.bookmarks.all().order_by("-is_favorite", "title")

    return Response(
        {
            "folder": {
                "id": folder.id,
                "name": folder.name,
                "description": folder.description,
                "color": folder.color,
                "icon": folder.icon,
                "bookmark_count": bookmarks.count(),
                "created_at": folder.created_at,
                "updated_at": folder.updated_at,
                "shared_by": folder.user.username if hasattr(folder.user, "username") else None,
            },
            "bookmarks": [
                {
                    "id": b.id,
                    "title": b.title,
                    "url": b.url,
                    "notes": b.notes,
                    "view_type": b.view_type,
                    "preview_data": b.preview_data,
                    "is_favorite": b.is_favorite,
                    "folder_name": b.folder.name if b.folder else None,
                    "created_at": b.created_at,
                    "updated_at": b.updated_at,
                }
                for b in bookmarks
            ],
        }
    )
