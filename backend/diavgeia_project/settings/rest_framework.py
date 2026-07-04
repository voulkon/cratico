"""
REST Framework settings.

Contains REST_FRAMEWORK configuration including authentication and permission classes.
"""

import os

# Respect the explicit USE_CLERK_AUTH flag, not just key presence.
# Keys may be set in env even when Clerk is intentionally disabled.
USE_CLERK_AUTH = os.getenv("USE_CLERK_AUTH", "False").lower() == "true"

# Build authentication classes list.
# TokenAuthentication is first so an explicit Bearer token always wins
# over a residual session cookie (avoids stale-session cross-user issues).
AUTH_CLASSES = [
    "rest_framework.authentication.TokenAuthentication",
    # CSRF-exempt session auth: fallback for browsable API / same-origin requests
    "api.authentication.CsrfExemptSessionAuthentication",
    "rest_framework.authentication.BasicAuthentication",
]

# Add Clerk authentication only when the feature flag is explicitly on
if USE_CLERK_AUTH:
    AUTH_CLASSES.append("api.authentication.ClerkAuthentication")

# Always include API key authentication
AUTH_CLASSES.append("api.authentication.ApiKeyAuthentication")

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": AUTH_CLASSES,
    "DEFAULT_PERMISSION_CLASSES": [
        # Require authentication by default
        # Individual views can override with AllowAny if needed
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "api.parsers.SanitizedJSONParser",
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
}
