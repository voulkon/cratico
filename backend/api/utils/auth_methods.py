"""
Auth method resolution.

Single source of truth for which authentication providers this deployment
currently supports. Consumed by the public /api/system/config/auth/ endpoint
so the frontend can decide at runtime which login UI to render, instead of
relying on build-time environment variables.
"""

from django.conf import settings


def clerk_is_fully_configured() -> bool:
    """
    True only when Clerk auth is enabled AND fully configured.

    Mirrors the guard in api.authentication.ClerkAuthentication (feature flag
    + JWT public key) and additionally requires the secret and publishable
    keys, so the advertised auth methods can never disagree with the
    credentials the backend actually accepts.
    """
    return bool(
        getattr(settings, "USE_CLERK_AUTH", False)
        and getattr(settings, "CLERK_JWT_PUBLIC_KEY", None)
        and getattr(settings, "CLERK_SECRET_KEY", None)
        and getattr(settings, "CLERK_PUBLISHABLE_KEY", None)
    )


def get_auth_methods() -> list[str]:
    """
    Ordered list of active auth providers, e.g. ["clerk", "django"].

    "django" is always present and always last: token/session authentication
    is unconditionally registered in DRF's DEFAULT_AUTHENTICATION_CLASSES
    (diavgeia_project/settings/rest_framework.py).
    """
    methods: list[str] = []
    if clerk_is_fully_configured():
        methods.append("clerk")
    methods.append("django")
    return methods


def get_clerk_publishable_key() -> str | None:
    """
    Publishable key to hand to the frontend, or None when Clerk is not
    active. Never expose a key that isn't usable.
    """
    if not clerk_is_fully_configured():
        return None
    return getattr(settings, "CLERK_PUBLISHABLE_KEY", None) or None
