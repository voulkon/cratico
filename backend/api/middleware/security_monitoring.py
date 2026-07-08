"""
Security Monitoring Response Middleware

Sits at the end of the middleware stack and:
    1. Checks if the IP is banned → 403 immediately (fast path).
    2. Records the request for velocity/scan detection.
    3. Records 4xx/5xx responses for error-rate detection.
    4. Evaluates threats and auto-bans if thresholds are crossed.
    5. Forensically logs flagged IPs (or all IPs if forensic logging is on)
       via an async Celery task to avoid DB write amplification on the hot path.

This middleware wraps the response, so it must be placed AFTER
RateLimitMiddleware in MIDDLEWARE (so it sees the final status code).
"""

import time
from api.services.security_service import security_service
from api.utils.ip import get_client_ip
from django.http import JsonResponse
from loguru import logger


class SecurityMonitoringResponseMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Skip non-API paths (admin, static, media) for performance
        if not request.path.startswith("/api/"):
            return self.get_response(request)

        ip = get_client_ip(request)
        start_time = time.monotonic()

        # ── Fast path: check ban list before processing ──────────────
        from core.services.feature_flag_service import feature_flags

        security_enabled = feature_flags.is_enabled("SECURITY_MONITORING_ENABLED")

        if security_enabled and ip and security_service.is_banned(ip):
            logger.info(f"Blocked banned IP {ip} on {request.path}")
            # Signal to _finalize that this IP was already banned — prevents
            # record_signals + evaluate_threats + ban_ip from running again,
            # which would cause a redundant DB write per request.
            request._security_already_banned = True
            response = JsonResponse(
                {"error": "Access denied", "detail": "IP has been blocked."},
                status=403,
            )
            return self._finalize(response, request, ip, start_time, security_enabled)

        # Process the request
        response = self.get_response(request)

        return self._finalize(response, request, ip, start_time, security_enabled)

    def _finalize(self, response, request, ip, start_time, security_enabled):
        """Record signals, evaluate threats, and optionally log forensically."""
        response_time_ms = int((time.monotonic() - start_time) * 1000)
        status_code = response.status_code

        if not security_enabled or not ip:
            # Still log forensically if the global forensic flag is on
            self._maybe_log_forensic(
                request, ip, status_code, response_time_ms, forced=False
            )
            return response

        # ── Skip signal recording + threat eval for already-banned IPs ──
        # The request-side middleware (security.py) and this middleware's own
        # fast-path both set _security_already_banned=True to prevent the
        # redundant DB write that update_or_create in ban_ip() would cause
        # on every subsequent request from the same banned IP.
        already_banned = getattr(request, "_security_already_banned", False)
        threat_reason = ""

        if not already_banned:
            # Record velocity/scan/error signals (not useful for banned IPs)
            security_service.record_signals(
                ip, request.path, is_error=(status_code >= 400)
            )

            # Evaluate threats against current thresholds
            from core.services.feature_flag_service import feature_flags

            auto_ban = feature_flags.is_enabled("SECURITY_AUTO_BAN_ENABLED")
            threat_reason = security_service.evaluate_threats(ip) or ""

            if threat_reason and auto_ban:
                from api.redis_keys import get_strikes_key

                strikes = int(security_service.redis.get(get_strikes_key(ip)) or 0)
                security_service.ban_ip(ip, threat_reason, strike_count=strikes)
                # Overwrite response with 403 if this is the request that
                # triggered the ban (only if the original response wasn't
                # already an error)
                if status_code < 400:
                    response = JsonResponse(
                        {
                            "error": "Access denied",
                            "detail": "IP flagged for suspicious activity.",
                        },
                        status=403,
                    )
                    status_code = 403

        # ── Forensic logging (runs for banned IPs too) ────────────────
        self._maybe_log_forensic(
            request,
            ip,
            status_code,
            response_time_ms,
            forced=False,
            flag_reason=threat_reason,
        )

        return response

    def _maybe_log_forensic(
        self,
        request,
        ip,
        status_code,
        response_time_ms,
        forced=False,
        flag_reason="",
    ):
        """
        Write to EndpointAccessLog (via async Celery task) if:
            - SECURITY_FORENSIC_LOGGING_ENABLED is on (logs everything), OR
            - the IP is flagged for forensics (logs only flagged traffic), OR
            - forced=True (caller explicitly wants this logged)

        The DB write is offloaded to a Celery task so that a burst of
        requests from a flagged IP does not amplify writes synchronously.
        """
        from core.services.feature_flag_service import feature_flags

        forensic_all = feature_flags.is_enabled("SECURITY_FORENSIC_LOGGING_ENABLED")

        # Skip logging for endpoints that produce noise without forensic value.
        # These are admin internals, auth checks, and static assets that every
        # pageload triggers — they inflate the log table without helping identify
        # attackers.
        _NOISY_ENDPOINT_PREFIXES = (
            "/api/admin/jsi18n/",
            "/api/auth/me/",
            "/api/system/legal/",
            "/api/system/config/",
        )
        if request.path.startswith(_NOISY_ENDPOINT_PREFIXES):
            return

        is_flagged = bool(flag_reason)  # truly suspicious, regardless of forensic mode

        if not (forced or forensic_all):
            # Only log if the IP is under forensic observation
            is_flagged = is_flagged or bool(
                ip and security_service.is_flagged_for_forensics(ip)
            )
            if not is_flagged:
                return

        # Avoid logging if IP is None (e.g. health checks from localhost)
        if not ip:
            return

        # Extract query params safely
        query_params = None
        if request.GET:
            query_params = {"GET": dict(request.GET)}
        if request.method == "POST" and request.content_type != "application/json":
            try:
                query_params = query_params or {}
                query_params["POST"] = dict(request.POST)
            except Exception:
                pass

        user_obj = getattr(request, "user", None)
        user_id = None
        if user_obj and getattr(user_obj, "is_authenticated", False):
            user_id = user_obj.pk

        # Offload the DB write to a Celery task — never block the response.
        from api.tasks.security import persist_endpoint_access_log

        persist_endpoint_access_log.delay(
            ip_address=ip,
            endpoint=request.path,
            method=request.method,
            query_params=query_params,
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:1000] or None,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user_id=user_id,
            is_flagged=is_flagged,
            flag_reason=flag_reason,
        )
