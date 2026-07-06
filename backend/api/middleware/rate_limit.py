import time

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
from api.utils.ip import get_client_ip
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

        # Skip rate limiting in development or for staff users
        if settings.DEBUG or (request.user.is_authenticated and request.user.is_staff):
            return self.get_response(request)

        if request.user.is_authenticated:
            key = get_user_ratelimit_key(request.user.id)
            daily_count = int(self.redis.get(key) or 0)

            # Check if user has exceeded their subscription limit
            if daily_count >= request.user.daily_request_limit:
                security_tracer.log_security_event(
                    "rate_limit.exceeded",
                    {
                        "limit_type": "daily",
                        "count": daily_count,
                        "limit": request.user.daily_request_limit,
                        "path": request.path,
                    },
                    user=request.user,
                    ip=get_client_ip(request),
                    severity="WARNING",
                )
                response = JsonResponse(
                    {"error": "Daily API request limit exceeded for your subscription"},
                    status=429,
                )
                response["X-RateLimit-Limit"] = request.user.daily_request_limit
                response["X-RateLimit-Remaining"] = 0
                response["X-RateLimit-Reset"] = int(time.time() + 86400)
                return self.add_cors_headers(response)

            usage = cache.get(key, {"count": 0, "reset_time": time.time() + 86400})

            # Get user's limit from their subscription
            limit = request.user.daily_request_limit

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

            # Check if limit reached
            limit = 100  # Set your daily limit for anonymous users
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
