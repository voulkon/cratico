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
        }
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def system_config(request):
    """
    Get general system configuration.

    DEPRECATED: This endpoint exposes internal feature flags.
    Consider using specific endpoints like /api/system/config/auth/ instead.

    This endpoint can be called by the frontend to determine which features are enabled.
    Uses the feature flag service to check DB first, then environment variables.
    """
    return Response(
        {
            "features": {
                "opensearch_indexing": feature_flags.is_enabled("INDEX_THE_OPENSEARCH"),
                "company_enrichment": feature_flags.is_enabled("HAVE_AFM_FETCH_JOB"),
                "document_extraction": feature_flags.is_enabled(
                    "EXTRACT_THE_DOCS_FROM_PDFS"
                ),
                "jaeger_tracing": feature_flags.is_enabled("TRANSMIT_TO_JAEGER"),
            },
            "settings": {
                "retry_afm_fetches_after_days": settings.RETRY_AFM_FETCHES_AFTER_NUMBER_OF_DAYS,
                "min_password_length": getattr(settings, "MIN_PASSWORD_LENGTH", 8),
            },
            "messages": {
                "opensearch": (
                    "OpenSearch indexing is disabled. Document search uses PostgreSQL fallback only."
                    if not feature_flags.is_enabled("INDEX_THE_OPENSEARCH")
                    else None
                ),
                "company_enrichment": (
                    "Company data enrichment is disabled. Only AFM entity information is maintained."
                    if not feature_flags.is_enabled("HAVE_AFM_FETCH_JOB")
                    else None
                ),
                "document_extraction": (
                    "Document text extraction is disabled. PDF content analysis is not available."
                    if not feature_flags.is_enabled("EXTRACT_THE_DOCS_FROM_PDFS")
                    else None
                ),
                "jaeger_tracing": (
                    "Distributed tracing is disabled. No telemetry data is sent to Jaeger."
                    if not feature_flags.is_enabled("TRANSMIT_TO_JAEGER")
                    else None
                ),
            },
        }
    )
