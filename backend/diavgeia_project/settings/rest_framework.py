"""
REST Framework settings.

Contains REST_FRAMEWORK configuration including authentication and permission classes.
"""

import os

# Check if Clerk authentication is available
CLERK_JWT_PUBLIC_KEY = os.getenv("CLERK_JWT_PUBLIC_KEY")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY")
USE_CLERK_AUTH = bool(CLERK_JWT_PUBLIC_KEY and CLERK_SECRET_KEY)

# Build authentication classes list
AUTH_CLASSES = [
    "rest_framework.authentication.BasicAuthentication",
    # Use CSRF-exempt session auth for API endpoints that primarily use token auth
    "api.authentication.CsrfExemptSessionAuthentication",
    "rest_framework.authentication.TokenAuthentication",
]

# Add Clerk authentication if credentials are available
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
