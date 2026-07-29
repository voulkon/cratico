"""
AI Settings API endpoints.

A user may have multiple settings rows (keys), with at most one default.

- GET    /api/ai/settings/              — the default row (legacy shape) + all rows
- PUT    /api/ai/settings/              — update the default row / set key
- POST   /api/ai/settings/rows/         — create an additional settings row
- PUT    /api/ai/settings/rows/<id>/    — update a specific row
- DELETE /api/ai/settings/rows/<id>/    — delete a row
- POST   /api/ai/settings/test-key/     — validate key via OpenRouter /key/info
- GET    /api/ai/models/                — list available models (cached 1h)
- POST   /api/ai/models/sync/           — admin: sync OpenRouter prices
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
        "label": settings_obj.label,
        "is_default": settings_obj.is_default,
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


def _apply_payload(obj: UserAISettings, data: dict) -> None:
    """Apply mutable fields from a request payload onto a settings row."""
    if "provider" in data:
        obj.provider = data["provider"]
    if "label" in data:
        obj.label = data["label"] or ""
    if "default_model" in data:
        obj.default_model = data["default_model"]
    if "monthly_budget_usd" in data:
        budget = data["monthly_budget_usd"]
        obj.monthly_budget_usd = budget if budget not in (None, "") else None
    if "is_active" in data:
        obj.is_active = bool(data["is_active"])
    if "is_default" in data:
        obj.is_default = bool(data["is_default"])
    if "api_key" in data:
        # Empty string clears the key
        obj.set_api_key(data["api_key"] or None)


@api_view(["GET", "PUT"])
@permission_classes([IsAuthenticated])
def ai_settings(request):
    """Get or update the current user's *default* AI settings row."""
    obj = UserAISettings.get_default_for_user(request.user)

    if request.method == "GET":
        payload = (
            _serialize_settings(obj)
            if obj
            else {
                "id": None,
                "provider": UserAISettings.Provider.OPENROUTER,
                "label": "",
                "is_default": True,
                "api_key_masked": "",
                "has_own_key": False,
                "default_model": None,
                "monthly_budget_usd": None,
                "is_active": True,
                "billed_to": "SYSTEM",
                "created_at": None,
                "updated_at": None,
            }
        )
        payload["rows"] = [
            _serialize_settings(r)
            for r in UserAISettings.objects.filter(user=request.user)
        ]
        # Include user-level AI feature flags
        payload["ai_enabled"] = request.user.ai_enabled
        payload["ai_system_key_accepted"] = request.user.ai_system_key_accepted
        # Determine effective mode: BYOK if any active row has a key, else SYSTEM
        has_active_byok = any(
            r.has_own_key for r in UserAISettings.objects.filter(user=request.user)
        )
        payload["key_mode"] = "BYOK" if has_active_byok else "SYSTEM"
        return Response(payload)

    # PUT — update (or lazily create) the default row
    if obj is None:
        obj = UserAISettings(user=request.user, is_default=True)
    _apply_payload(obj, request.data)
    obj.save()

    # Handle user-level flags if present in payload
    if "ai_enabled" in request.data:
        request.user.ai_enabled = bool(request.data["ai_enabled"])
        request.user.save(update_fields=["ai_enabled"])
    if "ai_system_key_accepted" in request.data:
        request.user.ai_system_key_accepted = bool(request.data["ai_system_key_accepted"])
        request.user.save(update_fields=["ai_system_key_accepted"])

    return Response(_serialize_settings(obj))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ai_settings_create(request):
    """Create an additional settings row for the current user."""
    obj = UserAISettings(user=request.user)
    _apply_payload(obj, request.data)
    obj.save()
    return Response(_serialize_settings(obj), status=status.HTTP_201_CREATED)


@api_view(["PUT", "DELETE"])
@permission_classes([IsAuthenticated])
def ai_settings_row(request, pk: int):
    """Update or delete a specific settings row owned by the current user."""
    try:
        obj = UserAISettings.objects.get(pk=pk, user=request.user)
    except UserAISettings.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)

    if request.method == "DELETE":
        was_default = obj.is_default
        obj.delete()
        if was_default:
            # Promote the oldest remaining row to default, if any.
            nxt = (
                UserAISettings.objects.filter(user=request.user)
                .order_by("created_at")
                .first()
            )
            if nxt:
                nxt.is_default = True
                nxt.save(update_fields=["is_default"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    _apply_payload(obj, request.data)
    obj.save()
    return Response(_serialize_settings(obj))


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def test_key(request):
    """Validate an OpenRouter API key via /key/info.

    Accepts:
      - ``api_key`` (str): a plaintext key to test (e.g. from a form field)
      - ``row_id`` (int):  pk of a UserAISettings row whose stored key to test

    If neither is provided the default row's key is tested.
    """
    # 1) Explicit row by id
    row_id = request.data.get("row_id")
    if row_id is not None:
        try:
            row = UserAISettings.objects.get(pk=row_id, user=request.user)
        except UserAISettings.DoesNotExist:
            return Response(
                {"is_valid": False, "error": "Settings row not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        key = row.get_api_key()
        if not key:
            return Response(
                {"is_valid": False, "error": "No API key stored on that row."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        result = OpenRouterProvider.check_key(key)
        return Response(result)

    # 2) Explicit plaintext key
    key = request.data.get("api_key")
    if not key:
        # 3) Fall back to the default row's stored key
        obj = UserAISettings.get_default_for_user(request.user)
        key = obj.get_api_key() if obj else None
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
        obj = UserAISettings.get_default_for_user(request.user)
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
