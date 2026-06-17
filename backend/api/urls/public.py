"""
Public Sharing URL Configuration

Endpoints for publicly shared bookmarks and folders.
These endpoints are intentionally unauthenticated (AllowAny permission).
"""

from django.urls import path
from users.views import public_shared_bookmark, public_shared_folder

# This PREFIX is used by the stealth middleware to discover and exempt this module.
# Public sharing endpoints must be accessible without authentication.
PREFIX = "public/"

urlpatterns = [
    path(
        "bookmark/<slug:slug>/",
        public_shared_bookmark,
        name="public-shared-bookmark",
    ),
    path(
        "folder/<slug:slug>/",
        public_shared_folder,
        name="public-shared-folder",
    ),
]
