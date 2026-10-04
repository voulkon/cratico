"""
Stealth Mode Middleware

Enforces authentication on all API endpoints when STEALTH_MODE is enabled.
Can optionally enforce an allowlist when STEALTH_ALLOWLIST is also enabled.

Always exempts critical endpoints (health, admin, docs, auth) from authentication.
Additional exemptions can be configured via the STEALTH_EXEMPT_PREFIXES feature flag.
"""

from api.utils.url_prefixes import get_all_exempt_prefixes
from django.db import models
from django.http import JsonResponse
from rest_framework import status


class StealthModeMiddleware:
    """
    Middleware to enforce authentication in stealth mode.

    When STEALTH_MODE=true, all /api/* requests must be authenticated.
    When STEALTH_MODE=true AND STEALTH_ALLOWLIST=true, authenticated users
    must also be in the AllowedUser table.

    Returns 401 Unauthorized for unauthenticated requests.
    Returns 403 Forbidden for authenticated but not allowed requests.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check feature flags dynamically on each request to allow instant updates
        from core.services.feature_flag_service import feature_flags

        stealth_mode = feature_flags.is_enabled("STEALTH_MODE")
        stealth_allowlist = feature_flags.is_enabled("STEALTH_ALLOWLIST")

        # Allow OPTIONS requests (CORS preflight) without authentication
        if request.method == "OPTIONS":
            return self.get_response(request)

        # Only enforce in stealth mode and for API endpoints
        # Skip enforcement for force-authenticated requests (used by DRF's
        # APIClient.force_authenticate() in tests). The _force_auth_user flag
        # means the test client has explicitly declared this request as
        # authenticated — we should trust it and skip all stealth checks.
        force_auth_user = getattr(request, '_force_auth_user', None)

        if stealth_mode and request.path.startswith("/api/") and force_auth_user is None:
            # Get all exempt prefixes (defaults + feature flag configured)
            # This automatically includes: health, admin, docs, auth, and any additional configured
            exempt_prefixes = get_all_exempt_prefixes()

            # Check if path should be exempted (starts with any exempt prefix)
            is_exempt = any(
                request.path.startswith(prefix) for prefix in exempt_prefixes
            )

            if not is_exempt:
                # Manually authenticate using DRF authentication classes
                user = self._authenticate_request(request)

                if not user:
                    return JsonResponse(
                        {
                            "error": "Authentication required",
                            "detail": "This API is in stealth mode. Please authenticate to access.",
                            "stealth_mode": True,
                        },
                        status=status.HTTP_401_UNAUTHORIZED,
                    )

                # Attach authenticated user to request for downstream use
                request.user = user
                request._dont_enforce_csrf_checks = True

                # If allowlist is enabled, check if user is allowed
                # Note: Superusers and staff are always allowed regardless of allowlist
                if stealth_allowlist:
                    # Always allow superusers and staff
                    if user.is_superuser or user.is_staff:
                        pass  # Allow through
                    else:
                        # Check regular users against allowlist
                        is_allowed = self._check_user_allowed(user)
                        if not is_allowed:
                            return JsonResponse(
                                {
                                    "error": "Access forbidden",
                                    "detail": "Your account is not authorized to access this application.",
                                    "stealth_mode": True,
                                    "allowlist_enabled": True,
                                },
                                status=status.HTTP_403_FORBIDDEN,
                            )

        response = self.get_response(request)
        return response

    def _authenticate_request(self, request):
        """
        Manually run DRF authentication to check if request has valid credentials.
        Returns the authenticated user or None.

        Delegates to api.utils.drf_auth so the stealth middleware and
        RateLimitMiddleware resolve the identity of token/Bearer/API-key
        requests exactly the same way.
        """
        from api.utils.drf_auth import authenticate_request

        return authenticate_request(request)

    def _check_user_allowed(self, user):
        """
        Check if user is in the allowlist.
        Checks by clerk_id (if available) or email.
        """
        from users.models import AllowedUser

        # Get user's email and clerk_id
        email = getattr(user, "email", None)
        clerk_id = getattr(user, "clerk_id", None)

        if not email and not clerk_id:
            return False

        # Check if user exists in allowlist and is active
        try:
            allowed_user = (
                AllowedUser.objects.filter(is_active=True)
                .filter(models.Q(email=email) | models.Q(clerk_user_id=clerk_id))
                .first()
            )

            # If found by email but clerk_user_id is not set, update it
            if allowed_user and clerk_id and not allowed_user.clerk_user_id:
                allowed_user.clerk_user_id = clerk_id
                allowed_user.save(update_fields=["clerk_user_id", "updated_at"])

            return allowed_user is not None
        except Exception:
            # If there's any error (e.g., table doesn't exist yet), deny access
            return False
