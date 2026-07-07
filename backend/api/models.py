from django.db import models


class APIRequest(models.Model):
    ip_address = models.GenericIPAddressField()
    path = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    user = models.ForeignKey(
        "users.CustomUser", null=True, blank=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    user_agent = models.TextField(blank=True, null=True)
    query_params = models.JSONField(
        null=True, blank=True, help_text="GET/POST parameters for analysis"
    )

    class Meta:
        indexes = [
            models.Index(fields=["ip_address"]),
            models.Index(fields=["timestamp"]),
        ]

    def __str__(self):
        return f"{self.ip_address} - {self.method} {self.path}"


class APIAnalytics(models.Model):
    total_requests = models.PositiveIntegerField()
    unique_ips = models.PositiveIntegerField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "API Analytics"
        verbose_name_plural = "API Analytics"

    def __str__(self):
        return f"Analytics {self.timestamp.strftime('%Y-%m-%d %H:%M')}"

    @property
    def requests_per_ip_ratio(self):
        """Calculate the average requests per IP"""
        if self.unique_ips > 0:
            return round(self.total_requests / self.unique_ips, 2)
        return 0

    @property
    def pattern_signature(self):
        """Return a string signature for this pattern"""
        return f"{self.total_requests}:{self.unique_ips}"

    def get_top_endpoints(self, limit=5):
        """Get the top endpoints for this analytics record"""
        return self.endpoints.order_by("-count")[:limit]

    @classmethod
    def get_pattern_frequency(cls, days=30):
        """Get frequency of different patterns over the last N days"""
        from collections import Counter
        from datetime import datetime, timedelta

        recent_analytics = cls.objects.filter(
            timestamp__gte=datetime.now() - timedelta(days=days)
        )

        patterns = Counter()
        for analytics in recent_analytics:
            patterns[analytics.pattern_signature] += 1

        return patterns.most_common()


class EndpointStats(models.Model):
    analytics = models.ForeignKey(
        APIAnalytics, on_delete=models.CASCADE, related_name="endpoints"
    )
    endpoint = models.CharField(max_length=255)
    count = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Endpoint Stat"
        verbose_name_plural = "Endpoint Stats"

    def __str__(self):
        return f"{self.endpoint}: {self.count}"


class DailyTraffic(models.Model):
    analytics = models.ForeignKey(
        APIAnalytics, on_delete=models.CASCADE, related_name="daily_traffic"
    )
    date = models.DateField()
    count = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Daily Traffic"
        verbose_name_plural = "Daily Traffic"

    def __str__(self):
        return f"{self.date}: {self.count}"


class IPJourney(models.Model):
    """Tracks which endpoints each IP has visited (for user journey analysis)"""

    analytics = models.ForeignKey(
        APIAnalytics, on_delete=models.CASCADE, related_name="ip_journeys"
    )
    ip_address = models.GenericIPAddressField()
    endpoints_visited = models.JSONField(
        help_text="List of endpoints visited by this IP"
    )
    journey_length = models.PositiveIntegerField(
        help_text="Number of unique endpoints visited"
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "IP Journey"
        verbose_name_plural = "IP Journeys"
        indexes = [
            models.Index(fields=["ip_address"]),
            models.Index(fields=["last_seen"]),
        ]

    def __str__(self):
        return f"{self.ip_address}: {self.journey_length} endpoints"


class EndpointAccessLog(models.Model):
    """Detailed log of endpoint access with query parameters.

    Used for forensic capture of flagged/suspicious traffic. When
    SECURITY_FORENSIC_LOGGING_ENABLED is on, ALL requests are logged here;
    otherwise only requests from IPs flagged by the security layer are
    captured (so you can review what the attacker actually sent).
    """

    ip_address = models.GenericIPAddressField()
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    query_params = models.JSONField(
        null=True, blank=True, help_text="GET/POST parameters"
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    user_agent = models.TextField(blank=True, null=True)
    # ── Forensic enrichment fields ──────────────────────────────────
    status_code = models.PositiveIntegerField(
        null=True, blank=True, help_text="HTTP response status code"
    )
    response_time_ms = models.PositiveIntegerField(
        null=True, blank=True, help_text="Response time in milliseconds"
    )
    user = models.ForeignKey(
        "users.CustomUser",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        help_text="Authenticated user (if any)",
    )
    is_flagged = models.BooleanField(
        default=False,
        db_index=True,
        help_text="True if this request was captured because the IP was flagged",
    )
    flag_reason = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text="Why this request was captured (e.g. velocity, strike, scan)",
    )

    class Meta:
        verbose_name = "Endpoint Access Log"
        verbose_name_plural = "Endpoint Access Logs"
        indexes = [
            models.Index(fields=["ip_address", "timestamp"]),
            models.Index(fields=["endpoint", "timestamp"]),
            models.Index(fields=["is_flagged", "timestamp"]),
            models.Index(fields=["status_code", "timestamp"]),
        ]

    def __str__(self):
        return f"{self.ip_address} → {self.method} {self.endpoint} [{self.status_code}]"

    @property
    def search_term(self):
        """Extract search term if this is a search endpoint"""
        if self.query_params and isinstance(self.query_params, dict):
            # Common search parameter names
            for key in ["q", "query", "search", "term", "keyword"]:
                if key in self.query_params:
                    return self.query_params[key]
        return None


class FlaggedIP(models.Model):
    """An IP address flagged by the security layer for malicious behavior.

    Created when an IP is auto-banned (if SECURITY_AUTO_BAN_ENABLED) or
    manually flagged from the admin security dashboard. The middleware
    checks the Redis ban set on every request for performance; this DB
    table is the persistent record and the admin-facing source of truth.
    """

    class FlagReason(models.TextChoices):
        VELOCITY = "velocity", "High request velocity"
        SCAN = "scan", "Endpoint scanning"
        STRIKES = "strikes", "Security pattern strikes (SQLi/XSS/etc)"
        ERRORS = "errors", "High 4xx/5xx error rate"
        MANUAL = "manual", "Manually flagged"
        RECURRING = "recurring", "Recurring offender (repeat ban)"

    ip_address = models.GenericIPAddressField(unique=True)
    reason = models.CharField(
        max_length=20,
        choices=FlagReason.choices,
        default=FlagReason.MANUAL,
    )
    flagged_at = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)
    ban_expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the Redis ban expires. Null = permanent ban.",
    )
    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="If False, the IP is no longer banned (kept for history).",
    )
    strike_count = models.PositiveIntegerField(
        default=0,
        help_text="Number of security events that contributed to this flag.",
    )
    notes = models.TextField(
        blank=True,
        default="",
        help_text="Admin notes about this IP (e.g. ' scraper from AWS, banned 2026-07-07')",
    )

    class Meta:
        verbose_name = "Flagged IP"
        verbose_name_plural = "Flagged IPs"
        indexes = [
            models.Index(fields=["is_active", "last_seen"]),
            models.Index(fields=["reason"]),
        ]

    def __str__(self):
        status = "active" if self.is_active else "expired"
        return f"{self.ip_address} ({self.reason}, {status})"
