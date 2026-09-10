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

    payload = {
        "authentication": {
            "required": stealth_mode,
            "allowlist_enabled": stealth_allowlist,
        },
        "password_requirements": {
            "min_length": getattr(settings, "MIN_PASSWORD_LENGTH", 8),
        },
        "auth_methods": get_auth_methods(),
        "clerk_publishable_key": get_clerk_publishable_key(),
        "search": {
            "debounce_ms": feature_flags.get_value("SEARCH_DEBOUNCE_MS", 300),
        },
    }

    # Read-only "throttle" block for the throttling/auto-ban E2E stacks only.
    # Absent unless EXPOSE_E2E_OPERATIONAL_CONFIG is set — nothing new is
    # exposed in production by default.
    if getattr(settings, "EXPOSE_E2E_OPERATIONAL_CONFIG", False):
        from api.constants import DEFAULT_ANON_API_DAILY_LIMIT
        
        payload["throttle"] = {
            "anon_daily_limit": getattr(settings, "ANON_API_DAILY_LIMIT", DEFAULT_ANON_API_DAILY_LIMIT),
            "security_monitoring_enabled": feature_flags.is_enabled(
                "SECURITY_MONITORING_ENABLED"
            ),
            "security_auto_ban_enabled": feature_flags.is_enabled(
                "SECURITY_AUTO_BAN_ENABLED"
            ),
            "security_velocity_threshold": feature_flags.get_value(
                "SECURITY_VELOCITY_THRESHOLD", 300
            ),
        }

    return Response(payload)
