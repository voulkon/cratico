"""
Centralized frontend URL helpers.

Single source of truth for building frontend URLs (decision pages,
verification/reset links, notification batch links, etc.).

Consolidates the previously scattered lookups of
``FRONTEND_DOMAINS_clean`` / ``FRONTEND_HOSTNAMES`` so callers no longer
need to know which settings attribute holds the origin or fall back
differently in different places.

Precedence for the base URL:
    1. ``settings.FRONTEND_DOMAINS_clean[0]`` — full origin with scheme
       (e.g. ``https://crati.co``). This is the canonical setting.
    2. ``settings.FRONTEND_HOSTNAMES[0]`` — hostname only (no scheme), so
       we prepend ``https://``. Kept for backwards compatibility with
       deployments that only set ``ALLOWED_HOSTS``-style hostnames.
    3. ``settings.FRONTEND_DEV_BASE`` (default ``http://localhost:3000``)
       when ``DEBUG`` is on.
    4. ``settings.FRONTEND_PROD_BASE`` (default ``https://crati.co``) as a
       last-resort production default.
"""

from __future__ import annotations

from django.conf import settings

_DEFAULT_PROD_BASE = "https://crati.co"
_DEFAULT_DEV_BASE = "http://localhost:3000"


def frontend_base_url() -> str:
    """Return the canonical frontend origin (scheme + host, no trailing slash)."""
    domains = getattr(settings, "FRONTEND_DOMAINS_clean", None)
    if domains:
        return domains[0].rstrip("/")

    hostnames = getattr(settings, "FRONTEND_HOSTNAMES", None)
    if hostnames:
        return f"https://{hostnames[0]}"

    if getattr(settings, "DEBUG", False):
        return getattr(settings, "FRONTEND_DEV_BASE", _DEFAULT_DEV_BASE)

    return getattr(settings, "FRONTEND_PROD_BASE", _DEFAULT_PROD_BASE)


def decision_frontend_url(decision) -> str:
    """Return the frontend page URL for a decision."""
    return f"{frontend_base_url()}/decision/{decision.id}"
