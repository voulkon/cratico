# New file for security monitoring

import json
import re

from diavgeia_project.security_tracing import get_client_ip, security_tracer


class SecurityMonitoringMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

        # Common attack patterns
        self.suspicious_patterns = [
            r"(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER)\s+.*\s+(FROM|TABLE)",  # SQL injection
            r"<script.*>",  # XSS
            r"(\.\.|\\\\|\/)\.(\/|\\\\)",  # Path traversal
            r"(\$|`).+(\$|`)",  # Command injection
        ]
        self.compiled_patterns = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.suspicious_patterns
        ]

    def __call__(self, request):
        # Skip admin/static paths (for performance)
        if request.path.startswith("/admin/") or request.path.startswith("/static/"):
            return self.get_response(request)

        # Check for security issues
        self._check_request(request)

        # Process request normally
        response = self.get_response(request)

        # Check for security issues in response
        if response.status_code in [403, 401]:
            # Log unauthorized access attempts
            security_tracer.log_security_event(
                f"access.denied.{response.status_code}",
                {"path": request.path, "method": request.method},
                user=request.user if request.user.is_authenticated else None,
                ip=get_client_ip(request),
                severity="WARNING",
            )

        return response

    def _check_request(self, request):
        # Check query parameters
        for key, values in request.GET.items():
            if isinstance(values, list):
                for value in values:
                    self._check_for_attacks(key, value, request)
            else:
                self._check_for_attacks(key, values, request)

        # Check POST data
        if request.method == "POST":
            # Handle different content types
            if request.content_type == "application/json":
                try:
                    if request.body:
                        data = json.loads(request.body)
                        self._scan_data_recursively(data, request)
                except Exception:
                    # If we can't parse the JSON, just continue
                    pass
            else:
                # Form data
                for key, values in request.POST.items():
                    if isinstance(values, list):
                        for value in values:
                            self._check_for_attacks(key, value, request)
                    else:
                        self._check_for_attacks(key, values, request)

    def _scan_data_recursively(self, data, request, path=""):
        """Recursively scan data structure for suspicious patterns"""
        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path}.{key}" if path else key
                if isinstance(value, (dict, list)):
                    self._scan_data_recursively(value, request, new_path)
                elif isinstance(value, str):
                    self._check_for_attacks(new_path, value, request)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{path}[{i}]"
                if isinstance(item, (dict, list)):
                    self._scan_data_recursively(item, request, new_path)
                elif isinstance(item, str):
                    self._check_for_attacks(new_path, item, request)

    def _check_for_attacks(self, key, value, request):
        if not isinstance(value, str):
            return

        for i, pattern in enumerate(self.compiled_patterns):
            if pattern.search(value):
                security_tracer.log_security_event(
                    "security.potential_attack",
                    {
                        "parameter": key,
                        "pattern_index": i,
                        "path": request.path,
                        # Don't log the full value as it may contain attack payloads
                        "value_preview": value[:20]
                        + ("..." if len(value) > 20 else ""),
                    },
                    user=request.user if request.user.is_authenticated else None,
                    ip=get_client_ip(request),
                    severity="WARNING",
                )

                # ── Feed the strike counter for auto-ban evaluation ──
                # Only active when SECURITY_MONITORING_ENABLED is on.
                from core.services.feature_flag_service import feature_flags

                if feature_flags.is_enabled("SECURITY_MONITORING_ENABLED"):
                    from api.services.security_service import security_service

                    ip = get_client_ip(request)
                    if ip:
                        strike_count = security_service.record_strike(
                            ip, event_type=f"pattern_{i}:{key}"
                        )
                        # Evaluate immediately — a single SQLi attempt might
                        # not cross the threshold, but we check so a burst does.
                        if (
                            strike_count >= feature_flags.get_value("SECURITY_STRIKE_THRESHOLD", 5)
                            and feature_flags.is_enabled("SECURITY_AUTO_BAN_ENABLED")
                        ):
                            security_service.ban_ip(
                                ip, "strikes", strike_count=strike_count
                            )
                            # Signal to the response middleware that this IP
                            # was already banned — prevents a duplicate ban_ip
                            # call in the same request cycle.
                            request._security_already_banned = True
                break
