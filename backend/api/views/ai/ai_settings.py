"""
AI Settings API endpoints.

- GET    /api/ai/settings/        — current user's settings (key masked)
- PUT    /api/ai/settings/        — update settings / set key
- POST   /api/ai/settings/test-key/ — validate key via OpenRouter /key/info
- GET    /api/ai/models/         — list available models (cached 1h)
- POST   /api/ai/models/sync/    — admin: sync OpenRouter prices
"""

from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from core.ai_services.providers.openrouter import OpenRouterProvider
from core.models.user_ai_settings import UserAISettings
from core.services.openrouter_sync_service import OpenRouterModelSyncService

_MODELS_CACHE_KEY = "openrouter_models_v1"
_MODELS_CACHE_TTL = 3600  # 1 hour


def _serialize_settings(settings_obj: UserAISettings) -> dict:
    return {
        "id": settings_obj.id,
        "provider": settings_obj.provider,
        "api_key_masked": settings_obj.masked_key,
        "has_own_key": settings_obj.has_own_key,
        "default_model": settings_obj.default_model,
        "monthly_budget_usd": (
            str(settings_obj.monthly_budget_usd)
            if settings_obj.monthly_budget_usd is not None
            else None
        ),
        "is_active": settings_obj.is_active,
        "billed_to": settings_obj.billed_to,
        "created_at": settings_obj.created_at,
        "updated_at": settings_obj.updated_at,
    }


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def ai_settings(request):
    """Get or update the current user's AI settings."""
    obj, _ = UserAISettings.objects.get_or_create(user=request.user)

    if request.method == "GET":
        return Response(_serialize_settings(obj))

    # PUT
    data = request.data
    if "provider" in data:
        obj.provider = data["provider"]
    if "default_model" in data:
        obj.default_model = data["default_model"]
    if "monthly_budget_usd" in data:
        budget = data["monthly_budget_usd"]
        obj.monthly_budget_usd = budget if budget not in (None, "") else None
    if "is_active" in data:
        obj.is_active = bool(data["is_active"])
    if "api_key" in data:
        # Empty string clears the key
        obj.set_api_key(data["api_key"] or None)

    obj.save()
    return Response(_serialize_settings(obj))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_key(request):
    """Validate an OpenRouter API key via /key/info."""
    key = request.data.get("api_key")
    if not key:
        # If no key provided, test the user's stored key
        obj, _ = UserAISettings.objects.get_or_create(user=request.user)
        key = obj.get_api_key()
        if not key:
            return Response(
                {"is_valid": False, "error": "No API key to test."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    result = OpenRouterProvider.check_key(key)
    return Response(result)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def list_models(request):
    """List available OpenRouter models with price + context window (cached 1h)."""
    cached = cache.get(_MODELS_CACHE_KEY)
    if cached is not None:
        return Response({"models": cached, "cached": True})

    try:
        # Use the user's key if available, else system key
        obj = getattr(request.user, "ai_settings", None)
        api_key = obj.get_api_key() if obj and obj.has_own_key else None
        models = OpenRouterProvider.list_models(api_key=api_key)
        cache.set(_MODELS_CACHE_KEY, models, _MODELS_CACHE_TTL)
        return Response({"models": models, "cached": False})
    except Exception as exc:
        return Response(
            {"error": f"Failed to fetch models: {exc}"},
            status=status.HTTP_502_BAD_GATEWAY,
        )


@api_view(["POST"])
@permission_classes([IsAdminUser])
def sync_models(request):
    """Admin/operator: sync OpenRouter prices into AIModelPricing."""
    result = OpenRouterModelSyncService.sync_models()
    # Invalidate the models cache so the next list reflects new prices
    cache.delete(_MODELS_CACHE_KEY)
    return Response(result)
