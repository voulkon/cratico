"""
Rate limiting middleware.

Two independent counters share this code path:

* authenticated callers  -> ``ratelimit:user:<id>``  (``user.daily_request_limit``)
* everyone else          -> ``ratelimit:ip:<ip>``    (``ANON_API_DAILY_LIMIT``)

Two subtleties this middleware has to get right:

1. **Identity.** ``request.user`` is populated by Django's
   ``AuthenticationMiddleware``, which only understands session cookies. The
   SPA authenticates with ``Authorization: Token <key>`` (DRF
   ``TokenAuthentication``), so ``request.user`` is ``AnonymousUser`` for every
   logged-in SPA call. Counting those against the anonymous per-IP bucket meant
   the per-user limit and the staff exemption were unreachable for token
   traffic. ``_resolve_user()`` falls back to the DRF authenticators.

2. **Boot chatter.** A single page load fires 8-15 ``/api/`` calls (auth/me,
   system config, per-widget dashboards...). Charging all of them against the
   daily quota made ``ANON_API_DAILY_LIMIT=300`` mean ~25 page loads. Safe
   reads of the endpoints the SPA always calls (the same set the threat layer
   already ignores via ``security_service.is_noisy_endpoint``) are therefore
   not counted. Writes and everything else still are.
"""

import time

from loguru import logger

from api.redis_keys import (
    DAILY_STATS,
    HOURLY_STATS,
    STATS_EXPIRE,
    TOTAL_REQUESTS,
    UNIQUE_IPS,
    USER_AGENTS,
    get_endpoint_ips_key,
    get_endpoint_key,
    get_ip_endpoints_key,
    get_ip_ratelimit_key,
    get_method_key,
    get_user_ratelimit_key,
)
from api.utils.ip import get_client_ip, is_infrastructure_ip
from diavgeia_project.security_tracing import security_tracer
from django.conf import settings
from django.core.cache import cache
from django.http import JsonResponse
from django_redis import get_redis_connection

from ..redis_utils import safe_incr


class RateLimitMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # Initialize Redis connection once
        self.redis = get_redis_connection("default")

    def add_cors_headers(self, response):
        """Add CORS headers to response"""
        response["Access-Control-Allow-Origin"] = "http://localhost:3000"
        response["Access-Control-Allow-Credentials"] = "true"
        response["Access-Control-Expose-Headers"] = (
            "X-RateLimit-Limit, X-RateLimit-Remaining, X-RateLimit-Reset"
        )
        return response

    def __call__(self, request):
        # Record analytics for all requests
        if request.path.startswith("/api/"):
            self.record_api_request(request)

        # ── Always allow rate-limit management & auth endpoints ──────────
        # Users who have hit their limit still need to log in and request resets.
        if (
            "/system/rate-limit/" in request.path
            or request.path.startswith("/api/auth/")
        ):
            response = self.get_response(request)
            return self.add_cors_headers(response)

        # ── Boot/widget chatter is not billed ────────────────────────────
        # Safe reads of the endpoints the SPA fires on every navigation are
        # free (see the module docstring). Analytics above still records them.
        if self._is_noisy_read(request):
            return self.get_response(request)

        # ── Resolve the caller (session cookie OR DRF token) ─────────────
        user = self._resolve_user(request)

        # Skip rate limiting in development, for staff users, or when the
        # RESOLVED client IP is missing/local/private. We decide exclusively
        # from get_client_ip(): nginx's REMOTE_ADDR is a private compose/CF
        # gateway in every real stack, so it must not drive the exemption.
        client_ip = get_client_ip(request)
        if (
            settings.DEBUG
            or (user is not None and user.is_staff)
            or not client_ip
            or is_infrastructure_ip(client_ip)
        ):
            return self.get_response(request)

        # ── Diagnostic log (remove once confirmed working) ────────────────
        # nginx's REMOTE_ADDR is only logged for diagnostics — it no longer
        # drives the exemption (see the gate above). "anonymous" here means no
        # session AND no usable DRF credential.
        logger.warning(
            "RateLimitMiddleware applying limit: path={} user={} is_staff={} "
            "client_ip={} remote_addr={}",
            request.path,
            getattr(user, "username", "anonymous") if user else "anonymous",
            bool(user and user.is_staff),
            client_ip,
            request.META.get("REMOTE_ADDR", ""),
        )

        if user is not None:
            key = get_user_ratelimit_key(user.id)

            # Read usage from Django cache (NOT raw redis — cache adds a
            # ":1:" version prefix, so raw redis reads always miss).
            usage = cache.get(key, {"count": 0, "reset_time": time.time() + 86400})

            # Get user's limit from their subscription
            limit = user.daily_request_limit

            # Check if limit reached
            if usage["count"] >= limit:
                remaining = int(usage["reset_time"] - time.time())
                if remaining <= 0:
                    # Reset if time expired
                    usage = {"count": 1, "reset_time": time.time() + 86400}
                    cache.set(key, usage, 86400)
                else:
                    # Return rate limit exceeded response
                    response = JsonResponse(
                        {
                            "error": "Rate limit exceeded. Please upgrade your subscription for more requests."
                        },
                        status=429,
                    )
                    response["X-RateLimit-Limit"] = limit
                    response["X-RateLimit-Remaining"] = 0
                    response["X-RateLimit-Reset"] = int(usage["reset_time"])
                    return self.add_cors_headers(response)

            # Increment usage counter
            usage["count"] += 1
            cache.set(key, usage, 86400)

            response = self.get_response(request)

            # Add rate limit headers
            response["X-RateLimit-Limit"] = limit
            response["X-RateLimit-Remaining"] = max(0, limit - usage["count"])
            response["X-RateLimit-Reset"] = int(usage["reset_time"])

            return self.add_cors_headers(response)

        # Get client IP address
        ip = get_client_ip(request)

        # Check if this is an API request
        if request.path.startswith("/api/"):
            # Get current usage stats
            key = get_ip_ratelimit_key(ip)
            usage = cache.get(key, {"count": 0, "reset_time": time.time() + 86400})

            # Check if limit reached.
            # Anonymous daily cap is a FeatureFlag (admin-tunable, env-backed)
            # whose effective default is the ANON_API_DAILY_LIMIT setting. Local
            # import keeps this middleware decoupled from app-load ordering.
            from core.services.feature_flag_service import feature_flags
            from api.constants import DEFAULT_ANON_API_DAILY_LIMIT

            limit = feature_flags.get_value(
                "ANON_API_DAILY_LIMIT",
                default=getattr(settings, "ANON_API_DAILY_LIMIT", DEFAULT_ANON_API_DAILY_LIMIT),
            )
            if usage["count"] >= limit:
                remaining = int(usage["reset_time"] - time.time())
                if remaining <= 0:
                    # Reset if time expired
                    usage = {"count": 1, "reset_time": time.time() + 86400}
                    cache.set(key, usage, 86400)
                else:
                    # Return rate limit exceeded response
                    response = JsonResponse(
                        {"error": "Rate limit exceeded. Please try again later."},
                        status=429,
                    )
                    response["X-RateLimit-Limit"] = limit
                    response["X-RateLimit-Remaining"] = 0
                    response["X-RateLimit-Reset"] = int(usage["reset_time"])
                    return self.add_cors_headers(response)

            # Increment usage counter
            usage["count"] += 1
            cache.set(key, usage, 86400)  # Store for 24 hours

            # Process the request
            response = self.get_response(request)

            # Add rate limit headers
            response["X-RateLimit-Limit"] = limit
            response["X-RateLimit-Remaining"] = max(0, limit - usage["count"])
            response["X-RateLimit-Reset"] = int(usage["reset_time"])

            return self.add_cors_headers(response)

        return self.get_response(request)

    @staticmethod
    def _resolve_user(request):
        """
        Return the authenticated caller, or None if truly anonymous.

        Session-authenticated requests come straight from ``request.user``
        (Django ``AuthenticationMiddleware``). Token/Bearer/API-key requests are
        resolved through the DRF authenticators, so the limiter keys them by
        user id exactly like the API view will.
        """
        django_user = getattr(request, "user", None)
        if django_user is not None and django_user.is_authenticated:
            return django_user

        from api.utils.drf_auth import authenticate_request

        resolved = authenticate_request(request)
        if resolved is not None:
            # Keep downstream middleware, logging and (defensive) views that read
            # request.user consistent with the identity the API view will see.
            request.user = resolved
        return resolved

    @staticmethod
    def _is_noisy_read(request):
        """
        True for safe reads of endpoints the SPA calls on every page.

        Single source of truth: ``security_service.is_noisy_endpoint``, which the
        threat layer already uses so that normal browsing cannot self-ban. Only
        safe methods qualify — writes on the same paths (e.g. bookmark
        mutations) keep consuming quota, so the carve-out cannot be used to
        hammer a mutating endpoint for free.
        """
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return False

        from api.services.security_service import is_noisy_endpoint

        return is_noisy_endpoint(request.path)

    def record_api_request(self, request):
        """Record API request analytics in Redis"""
        ip = get_client_ip(request)
        endpoint = request.path

        # Increment total request counter
        safe_incr(TOTAL_REQUESTS, 1)

        # Increment requests per endpoint
        endpoint_key = get_endpoint_key(endpoint)
        safe_incr(endpoint_key, 1)

        # Track unique IPs (using Redis Sets)
        self.redis.sadd(UNIQUE_IPS, ip)

        # Store hourly stats (using Redis Sorted Sets)
        hour_key = int(time.time() / 3600)  # Current hour timestamp
        self.redis.zincrby(HOURLY_STATS, 1, str(hour_key))

        # Store daily stats
        day_key = int(time.time() / 86400)  # Current day timestamp
        self.redis.zincrby(DAILY_STATS, 1, str(day_key))

        # Store method stats
        method_key = get_method_key(request.method)
        safe_incr(method_key, 1)

        # Track which endpoints each IP visits (for user journey analysis)
        ip_endpoints_key = get_ip_endpoints_key(ip)
        self.redis.sadd(ip_endpoints_key, endpoint)
        self.redis.expire(ip_endpoints_key, STATS_EXPIRE)

        # Track which IPs visit each endpoint (reverse lookup)
        endpoint_ips_key = get_endpoint_ips_key(endpoint)
        self.redis.sadd(endpoint_ips_key, ip)
        self.redis.expire(endpoint_ips_key, STATS_EXPIRE)

        # Optionally track user agent
        if "HTTP_USER_AGENT" in request.META:
            self.redis.zincrby(USER_AGENTS, 1, request.META["HTTP_USER_AGENT"])

        # Track query parameters for important endpoints (search, filters, etc.)
        # Store in Redis as hash for easy retrieval
        if request.GET or request.POST:
            # Only track for specific endpoints to avoid noise
            trackable_patterns = [
                "/api/search",
                "/api/decisions",
                "/api/organizations",
                "/api/filters",
            ]
            should_track = any(pattern in endpoint for pattern in trackable_patterns)

            if should_track:
                import json
                from datetime import datetime as dt

                query_data = {
                    "ip": ip,
                    "endpoint": endpoint,
                    "method": request.method,
                    "get_params": dict(request.GET),
                    "post_params": (
                        dict(request.POST) if request.method == "POST" else {}
                    ),
                    "timestamp": dt.now().isoformat(),
                }

                # Store in Redis sorted set with timestamp as score
                query_log_key = f"stats:query_logs:{endpoint}"
                self.redis.zadd(query_log_key, {json.dumps(query_data): time.time()})

                # Keep only last 1000 entries per endpoint
                self.redis.zremrangebyrank(query_log_key, 0, -1001)
                self.redis.expire(query_log_key, STATS_EXPIRE)
