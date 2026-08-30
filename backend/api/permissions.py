"""
Centralized API permission classes.

All views should import permission classes from here instead of repeating
inline patterns.  This makes it easy to audit and change permission policies
across the entire codebase from a single location.

Usage::

    from api.permissions import AuthenticatedOrDebug

    @api_view(["GET"])
    @permission_classes([AuthenticatedOrDebug])
    def my_view(request):
        ...

Classes
-------
AuthenticatedOrDebug
    Allow any access when ``settings.DEBUG=True``, require authentication
    otherwise.  This is a **transitional** permission — most endpoints should
    eventually move to either ``IsAuthenticated`` or ``PublicReadOnly``.

PublicReadOnly
    Allow read-only access (GET/HEAD/OPTIONS) publicly.  Mutations
    (POST/PUT/PATCH/DELETE) require authentication.  Suitable for search,
    browse, and detail endpoints that serve public government data.

Endpoint categorisation (recommended)
-------------------------------------
**PublicReadOnly** (public browsing, authenticated mutations):
  - ``/api/search/*``          — all search endpoints
  - ``/api/entity/*``          — entity analytics & decisions
  - ``/api/explore/*``         — temporal exploration
  - ``/api/decisions/*``       — decision detail, unified, top-N lists
  - ``/api/companies/*``       — company details & stats
  - ``/api/organizations/*``   — organisation views
  - ``/api/browse/*``          — alphabetical entity browsing
  - ``/api/direct-assignments/*`` — direct assignment analytics
  - ``/api/entity/afm/*``      — legacy AFM entity endpoints
  - ``/api/org-chart-api/*``   — organisation chart
  - ``/api/summary/*``         — summary amounts

**AllowAny** (truly public, no auth ever):
  - ``/api/version/``          — health check
  - ``/api/system/config/``    — auth configuration
  - ``/api/system/legal/``     — legal documents
  - ``/api/auth/*``            — login/register

**IsAuthenticated** (always requires auth):
  - ``/api/ai/*``              — AI operations (costly, user-specific)
  - ``/api/user-data/*``        — user profile & preferences
  - ``/api/notifications/*``   — notification subscriptions
  - ``/api/search/history/*``  — user search history
  - ``/api/performance/*``     — performance monitoring
  - ``/api/tasks/*``           — background task management
  - ``/api/processes/*``       — text process triggering (POST is costly)
"""

from __future__ import annotations

from django.conf import settings
from rest_framework import permissions


class AuthenticatedOrDebug(permissions.BasePermission):
    """
    Allow any access when ``settings.DEBUG=True``, require authentication otherwise.

    Evaluated per-request so toggling ``settings.DEBUG`` takes effect without
    a process reload.

    This replaces the inline pattern::

        AuthenticatedOrDebug

    which appeared 66 times across the codebase.
    """

    def has_permission(self, request, view):
        if settings.DEBUG:
            return True
        return request.user and request.user.is_authenticated


class PublicReadOnly(permissions.BasePermission):
    """
    Allow read-only access (GET, HEAD, OPTIONS) publicly.

    Mutations (POST, PUT, PATCH, DELETE) require authentication.
    Suitable for search, browse, and detail endpoints that serve public
    government transparency data.
    """

    SAFE_METHODS = ("GET", "HEAD", "OPTIONS")

    def has_permission(self, request, view):
        if request.method in self.SAFE_METHODS:
            return True
        return request.user and request.user.is_authenticated


__all__ = [
    "AuthenticatedOrDebug",
    "PublicReadOnly",
]
