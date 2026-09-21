"""
DRF-credential authentication for Django middleware.

Django's ``AuthenticationMiddleware`` only understands session cookies, but the
SPA authenticates with ``Authorization: Token <key>`` (or a Clerk ``Bearer``
JWT when that flag is on) — see ``frontend/src/api/client.js`` and
``DEFAULT_AUTHENTICATION_CLASSES`` in ``diavgeia_project/settings/rest_framework.py``.

Any middleware that asks ``request.user`` therefore sees ``AnonymousUser`` for
every logged-in SPA request, which made token-authenticated traffic look
anonymous to the rate limiter (billed to the per-IP anonymous bucket instead of
the per-user daily limit).

``authenticate_request()`` runs the configured authenticators against a Django
request and returns the user the API view will see (or ``None``).

Cost: for requests without credentials every authenticator short-circuits
before touching the database, so plain anonymous traffic pays almost nothing.
Token requests cost one ``authtoken_token`` lookup here plus DRF's own lookup
in the view — a token→user cache can be layered on later if measurements show
it matters.
"""

from typing import Any, Dict, Optional, Tuple

# Instantiated authenticators per configured class-path tuple.  Keyed by the
# tuple (not a single global) so ``override_settings(REST_FRAMEWORK=...)`` in
# tests is picked up instead of a stale instance list.
_authenticator_cache: Dict[Tuple[str, ...], list] = {}


def _get_authenticators(auth_class_paths: Tuple[str, ...]) -> list:
    """Build (and memoize) the authenticator instances for the given paths."""
    cached = _authenticator_cache.get(auth_class_paths)
    if cached is not None:
        return cached

    built = []
    for auth_class_path in auth_class_paths:
        try:
            module_path, class_name = auth_class_path.rsplit(".", 1)
            module = __import__(module_path, fromlist=[class_name])
            built.append(getattr(module, class_name)())
        except (ImportError, AttributeError):
            # An unimportable class must not disable the whole chain
            # (mirrors StealthModeMiddleware's previous behavior).
            continue

    _authenticator_cache[auth_class_paths] = built
    return built


def authenticate_request(request) -> Optional[Any]:
    """
    Return the user authenticated by the request's DRF credentials, or None.

    Session-authenticated requests should be handled by the caller via
    ``request.user`` first; this helper exists for the token/Bearer/API-key
    paths that Django's own authentication layer cannot see.
    """
    # APIClient.force_authenticate() tags the request before middleware runs;
    # the configured authenticators look for real credentials, not this marker.
    force_user = getattr(request, "_force_auth_user", None)
    if force_user is not None:
        return force_user

    from django.conf import settings
    from rest_framework.request import Request as DRFRequest

    rest_config = getattr(settings, "REST_FRAMEWORK", None) or {}
    auth_class_paths = tuple(rest_config.get("DEFAULT_AUTHENTICATION_CLASSES", []) or [])
    if not auth_class_paths:
        return None

    drf_request = DRFRequest(request)
    for authenticator in _get_authenticators(auth_class_paths):
        try:
            result = authenticator.authenticate(drf_request)
        except Exception:
            # A malformed or invalid credential must not raise from a
            # middleware: treat it as anonymous and let DRF reject it in the
            # view with the proper 401/403.
            continue
        if result is not None:
            user, _auth = result
            return user

    return None
