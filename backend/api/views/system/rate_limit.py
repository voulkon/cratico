"""
Admin & user rate-limit management views.

Provides:
- Staff-only endpoint to reset any user's rate limit (clear cache).
- User-facing endpoint to request a rate-limit reset (bypasses rate limiter).
"""

import time

from api.redis_keys import get_user_ratelimit_key
from django.contrib.auth import get_user_model
from django.core.cache import cache
from loguru import logger
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response

User = get_user_model()

# Cache key for pending reset requests so we don't spam admins
_RESET_REQUEST_KEY = "rate_limit_reset_requests"  # set of user_ids


@api_view(["POST"])
@permission_classes([IsAdminUser])
def admin_reset_rate_limit(request):
    """
    Staff-only: Reset the rate-limit counter for a user, and optionally
    set a permanent daily-limit override.

    Body:
        user_id: int                  — (required) user to act on
        daily_limit_override: int|null — set a new permanent daily limit,
                                         or null to remove the override and
                                         fall back to subscription default.
    """
    user_id = request.data.get("user_id") if request.data else None

    if not user_id:
        return Response(
            {
                "error": "user_id is required. "
                "To reset ALL users, pass confirm='yes-reset-all'."
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response(
            {"error": f"User {user_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Clear the rate-limit counter
    key = get_user_ratelimit_key(user.id)
    cache.delete(key)

    # Optionally set a permanent override
    override = request.data.get("daily_limit_override")
    if "daily_limit_override" in (request.data or {}):
        if override is None:
            user.daily_request_limit_override = None
            msg_extra = ", override removed (back to subscription default)"
        else:
            try:
                user.daily_request_limit_override = int(override)
                msg_extra = f", daily limit set to {override}"
            except (TypeError, ValueError):
                return Response(
                    {"error": "daily_limit_override must be an integer or null"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        user.save(update_fields=["daily_request_limit_override"])
    else:
        msg_extra = ""

    logger.info(
        f"Rate limit reset for {user.username} (id={user.id}){msg_extra}"
    )
    return Response(
        {
            "status": "ok",
            "message": f"Rate limit reset for {user.username}{msg_extra}",
            "user_id": user.id,
            "daily_limit": user.daily_request_limit,
        }
    )


@api_view(["POST"])
@permission_classes([AllowAny])
def request_rate_limit_reset(request):
    """
    Request a rate-limit reset from admins.

    This endpoint is exempt from rate limiting (see RateLimitMiddleware).
    Authenticated users get their request recorded; anonymous users are
    prompted to log in first so the request can be tied to their account.
    """
    if not request.user.is_authenticated:
        return Response(
            {
                "status": "error",
                "message": "Please log in to request a rate limit reset.",
                "require_auth": True,
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    user = request.user

    # Check if this user already has a pending request
    pending = cache.get(_RESET_REQUEST_KEY, set())
    if user.id in pending:
        return Response(
            {
                "status": "ok",
                "message": "Your rate-limit reset request is already pending. An admin will review it shortly.",
                "already_pending": True,
            }
        )

    # Record the request (expire after 24h)
    pending = set(pending)  # cache may return a set or list
    pending.add(user.id)
    cache.set(_RESET_REQUEST_KEY, pending, 86400)

    logger.info(
        f"Rate-limit reset requested by {user.username} (id={user.id})"
    )

    return Response(
        {
            "status": "ok",
            "message": "Your rate-limit reset request has been sent to the admins.",
        }
    )


@api_view(["GET"])
@permission_classes([IsAdminUser])
def get_rate_limit_status(request, user_id: int):
    """
    Staff-only: Get current rate-limit status for a specific user.
    """
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return Response(
            {"error": f"User {user_id} not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    key = get_user_ratelimit_key(user.id)
    usage = cache.get(key, {"count": 0, "reset_time": time.time() + 86400})

    return Response(
        {
            "user_id": user.id,
            "username": user.username,
            "daily_limit": user.daily_request_limit,
            "current_usage": usage.get("count", 0),
            "remaining": max(0, user.daily_request_limit - usage.get("count", 0)),
            "resets_at": usage.get("reset_time"),
            "has_active_subscription": user.has_active_subscription,
        }
    )


@api_view(["GET"])
@permission_classes([IsAdminUser])
def list_pending_reset_requests(request):
    """
    Staff-only: List all pending rate-limit reset requests.
    """
    pending = cache.get(_RESET_REQUEST_KEY, set())
    if not pending:
        return Response({"requests": [], "count": 0})

    users = User.objects.filter(id__in=pending).only(
        "id", "username", "email", "daily_request_limit_override"
    )

    result = []
    for user in users:
        key = get_user_ratelimit_key(user.id)
        usage = cache.get(key, {"count": 0, "reset_time": time.time() + 86400})
        daily_limit = user.daily_request_limit

        result.append(
            {
                "user_id": user.id,
                "username": user.username,
                "email": user.email,
                "daily_limit": daily_limit,
                "current_usage": usage.get("count", 0),
                "remaining": max(0, daily_limit - usage.get("count", 0)),
                "has_override": user.daily_request_limit_override is not None,
            }
        )

    return Response({"requests": result, "count": len(result)})
