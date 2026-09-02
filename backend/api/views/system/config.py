from api.utils.auth_methods import get_auth_methods, get_clerk_publishable_key
from core.services.feature_flag_service import feature_flags
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def auth_config(request):
    """
    Get authentication and authorization configuration.

    This public endpoint tells the frontend:
    - Whether authentication is required (stealth mode)
    - Whether allowlist is enabled
    - Password requirements
    - Which auth providers are active ("clerk" and/or "django")
    - The Clerk publishable key, when Clerk is active (null otherwise)

    This allows the frontend to adapt its UI without hardcoding env vars.
    """
    stealth_mode = feature_flags.is_enabled("STEALTH_MODE")
    stealth_allowlist = feature_flags.is_enabled("STEALTH_ALLOWLIST")

    return Response(
        {
            "authentication": {
                "required": stealth_mode,
                "allowlist_enabled": stealth_allowlist,
            },
            "password_requirements": {
                "min_length": getattr(settings, "MIN_PASSWORD_LENGTH", 8),
            },
            "auth_methods": get_auth_methods(),
            "clerk_publishable_key": get_clerk_publishable_key(),
        }
    )
