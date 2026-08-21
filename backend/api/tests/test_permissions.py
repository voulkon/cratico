"""
Tests for the centralized API permission classes in ``api.permissions``.

These verify the core contract of each class both directly (unit tests on
``has_permission``) and through the full DRF request lifecycle (view tests):

- ``AuthenticatedOrDebug``: allow everyone when ``DEBUG=True``; require
  authentication when ``DEBUG=False``.
- ``PublicReadOnly``: allow safe methods (GET/HEAD/OPTIONS) publicly; require
  authentication for mutations.
"""

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory, override_settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from api.permissions import AuthenticatedOrDebug, PublicReadOnly


# ---------------------------------------------------------------------------
# Minimal views that exercise each permission through the real DRF stack.
# ---------------------------------------------------------------------------

@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def _authenticated_or_debug_view(request):
    return Response({"ok": True})


@api_view(["GET", "POST"])
@permission_classes([PublicReadOnly])
def _public_read_only_view(request):
    return Response({"ok": True})


# ---------------------------------------------------------------------------
# AuthenticatedOrDebug — unit tests
# ---------------------------------------------------------------------------


class TestAuthenticatedOrDebugUnit:
    @override_settings(DEBUG=True)
    def test_allows_anonymous_when_debug_true(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        assert AuthenticatedOrDebug().has_permission(request, None) is True

    @override_settings(DEBUG=False)
    def test_denies_anonymous_when_debug_false(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        assert AuthenticatedOrDebug().has_permission(request, None) is False

    @override_settings(DEBUG=False)
    def test_allows_authenticated_user_when_debug_false(self, user):
        request = RequestFactory().get("/")
        request.user = user
        assert AuthenticatedOrDebug().has_permission(request, None) is True


class TestAuthenticatedOrDebugView:
    @override_settings(DEBUG=True)
    def test_returns_200_when_debug_true_and_anonymous(self):
        request = RequestFactory().get("/")
        assert _authenticated_or_debug_view(request).status_code == 200

    @override_settings(DEBUG=False)
    def test_returns_401_when_debug_false_and_anonymous(self):
        request = RequestFactory().get("/")
        assert _authenticated_or_debug_view(request).status_code == 401

    @override_settings(DEBUG=False)
    def test_returns_200_when_debug_false_but_authenticated(self, user):
        request = APIRequestFactory().get("/")
        force_authenticate(request, user=user)
        assert _authenticated_or_debug_view(request).status_code == 200


# ---------------------------------------------------------------------------
# PublicReadOnly
# ---------------------------------------------------------------------------


class TestPublicReadOnly:
    def test_allows_safe_methods_anonymously(self):
        request = RequestFactory().get("/")
        request.user = AnonymousUser()
        assert PublicReadOnly().has_permission(request, None) is True

    def test_denies_mutation_anonymously(self):
        request = RequestFactory().post("/")
        request.user = AnonymousUser()
        assert PublicReadOnly().has_permission(request, None) is False

    def test_allows_mutation_when_authenticated(self, user):
        request = RequestFactory().post("/")
        request.user = user
        assert PublicReadOnly().has_permission(request, None) is True
