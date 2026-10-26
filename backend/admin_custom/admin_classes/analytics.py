import ipaddress
import json
from datetime import date, datetime, time, timedelta

from core.models.decision_health import HealthStatus
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from core.tasks import (
    backfill_health_checks_for_import_job,
    retry_failed_decisions_for_import_job,
)
from django.contrib import admin, messages
from django.core.paginator import Paginator
from django.db.models import (
    BooleanField,
    Case,
    Count,
    ExpressionWrapper,
    FloatField,
    Max,
    Min,
    Q,
    Value,
    When,
)
from django.db.models.functions import Cast, TruncDate
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.http import urlencode
from django.utils.safestring import mark_safe


class APIAnalyticsAdmin(admin.ModelAdmin):
    """Admin interface for API Analytics"""

    list_display = (
        "timestamp",
        "total_requests",
        "unique_ips",
        "endpoint_count",
        "avg_requests_per_ip",
    )
    date_hierarchy = "timestamp"
    list_filter = ("timestamp",)
    ordering = ("-timestamp",)

    def endpoint_count(self, obj):
        return obj.endpoints.count()

    endpoint_count.short_description = "Endpoints Hit"

    def avg_requests_per_ip(self, obj):
        if obj.unique_ips > 0:
            return round(obj.total_requests / obj.unique_ips, 2)
        return 0

    avg_requests_per_ip.short_description = "Avg Req/IP"

    def get_queryset(self, request):
        return super().get_queryset(request).prefetch_related("endpoints")


class EndpointStatsAdmin(admin.ModelAdmin):
    """Admin interface for Endpoint Statistics"""

    list_display = ("endpoint", "count")
    search_fields = ("endpoint",)


class EndpointAccessLogAdmin(admin.ModelAdmin):
    """Admin interface for forensic endpoint access logs."""

    # Admin API paths require authentication — the admin's own browsing is
    # never an attack probe, so exclude them from suspicious classification.
    _ADMIN_API_PREFIX = "/api/admin/"

    # ── Suspicious endpoint patterns for automatic classification ──────
    # NOTE: matching is substring-based (icontains), so keep patterns long
    # enough to avoid false positives.  e.g. "/api/endpoint/" (with the
    # trailing slash) so it does NOT match "/api/endpointaccesslog/".
    _SUSPICIOUS_ENDPOINT_PATTERNS = (
        "/.env",
        "/.git/",
        "/wp-admin",
        "/wp-login",
        "/phpmyadmin",
        "/adminer",
        "/actuator",
        "/api/test",
        "/api/[[...slug]]",
        "/api/endpoint/",
        "/cgi-bin/",
        "/.aws/",
        "/config",
        "/backup",
    )

    list_display = (
        "timestamp",
        "ip_address",
        "method",
        "full_request_display",
        "status_code",
        "response_time_ms",
        "is_flagged",
        "flag_reason",
        "user_link",
    )
    list_filter = (
        "ip_address",
        ("user", admin.RelatedOnlyFieldListFilter),
        "is_flagged",
        "flag_reason",
        "method",
        "status_code",
        "timestamp",
    )
    search_fields = ("ip_address", "endpoint", "user_agent")
    date_hierarchy = "timestamp"
    ordering = ("-timestamp",)
    list_per_page = 50
    readonly_fields = ("timestamp", "full_request_display")
    list_display_links = ("timestamp", "ip_address")
    change_list_template = "admin/endpoint_access_log_changelist.html"

    @admin.display(description="Full Request URL")
    def full_request_display(self, obj):
        """Clickable full request URL that filters by endpoint.

        Shows: GET /api/endpoint?param1=val1&param2=val2
        Clicking filters the changelist to show only requests to that endpoint.
        Truncates long URLs; full text shown on hover.
        """
        query_string = self._format_query_params(obj.query_params)
        endpoint_with_qs = obj.endpoint
        if query_string:
            endpoint_with_qs = f"{obj.endpoint}?{query_string}"

        full_display = f"{obj.method} {endpoint_with_qs}"

        # Build filter URL for this endpoint
        filter_url = reverse("admin:api_endpointaccesslog_changelist")
        filter_url += "?" + urlencode({"endpoint": obj.endpoint})

        # Truncate for display
        if len(full_display) > 120:
            display = full_display[:117] + "..."
        else:
            display = full_display

        return format_html(
            '<a href="{}" title="{}" style="font-family: monospace; font-size: 12px; '
            'word-break: break-all;">{}</a>',
            filter_url,
            full_display,
            display,
        )

    @admin.display(description="User")
    def user_link(self, obj):
        """Render the user as a link that filters the changelist to that user.

        Clicking a user drills into only that user's access logs. The sidebar
        "By user" filter (RelatedOnlyFieldListFilter) lists every unique user
        that has at least one entry in this table.
        """
        if obj.user_id is None:
            return "-"
        filter_url = reverse("admin:api_endpointaccesslog_changelist")
        filter_url += "?" + urlencode({"user__id__exact": obj.user_id})
        return format_html('<a href="{}">{}</a>', filter_url, obj.user)

    def get_queryset(self, request):
        # Default: show all entries. The is_flagged filter in the sidebar lets
        # the user drill down to only flagged entries when investigating.
        return super().get_queryset(request).select_related("user")

    def get_urls(self):
        """Add custom URLs for IP summary and endpoint summary views."""
        urls = super().get_urls()
        custom_urls = [
            path(
                "ip-summary/",
                self.admin_site.admin_view(self.ip_summary_view),
                name="endpointaccesslog_ip_summary",
            ),
            path(
                "ip-detail/",
                self.admin_site.admin_view(self.ip_detail_view),
                name="endpointaccesslog_ip_detail",
            ),
            path(
                "endpoint-summary/",
                self.admin_site.admin_view(self.endpoint_summary_view),
                name="endpointaccesslog_endpoint_summary",
            ),
        ]
        return custom_urls + urls

    # ── IP Summary View ───────────────────────────────────────────────

    SESSION_GAP = timedelta(minutes=30)
    VISITORS_PER_PAGE = 50
    DETAIL_ROW_CAP = 20000
    VISITOR_SORTS = {
        "ip": "ip_address",
        "requests": "request_count",
        "endpoints": "unique_endpoints",
        "errors": "error_ratio",
        "notfound": "notfound_ratio",
        "suspicious": "suspicious_hits",
        "first_seen": "first_seen",
        "last_seen": "last_seen",
    }
    VISITOR_COLUMNS = (
        ("ip", "IP Address"),
        ("requests", "Requests"),
        ("endpoints", "Endpoints"),
        ("errors", "Err %"),
        ("notfound", "404 %"),
        ("suspicious", "Suspicious"),
        ("first_seen", "First Seen"),
        ("last_seen", "Last Seen"),
    )

    @classmethod
    def _suspicious_q(cls):
        q = Q()
        for pat in cls._SUSPICIOUS_ENDPOINT_PATTERNS:
            q |= Q(endpoint__icontains=pat)
        return q & ~Q(endpoint__startswith=cls._ADMIN_API_PREFIX)

    @staticmethod
    def _parse_day(value):
        try:
            return date.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _range_query(start, end):
        return {
            "start": start.isoformat() if start else "",
            "end": end.isoformat() if end else "",
        }

    def _latest_day(self):
        today = timezone.localdate()
        latest = self.model.objects.aggregate(latest=Max("timestamp"))["latest"]
        if latest is None:
            return today
        return min(timezone.localtime(latest).date(), today)

    def _date_range(self, request, latest):
        """Inclusive (start, end) dates; a missing side means unbounded."""
        if "start" not in request.GET and "end" not in request.GET:
            return latest, latest
        return (
            self._parse_day(request.GET.get("start")),
            self._parse_day(request.GET.get("end")),
        )

    @staticmethod
    def _bounds(start, end):
        """Aware [lo, hi) datetimes covering an inclusive date range."""
        tz = timezone.get_current_timezone()
        lo = None
        hi = None
        if start:
            lo = timezone.make_aware(datetime.combine(start, time.min), tz)
        if end:
            hi = timezone.make_aware(
                datetime.combine(end + timedelta(days=1), time.min), tz
            )
        return lo, hi

    def _scope(self, qs, start, end):
        lo, hi = self._bounds(start, end)
        if lo:
            qs = qs.filter(timestamp__gte=lo)
        if hi:
            qs = qs.filter(timestamp__lt=hi)
        return qs

    def _range_presets(self, base_url, latest, extra=None):
        options = (
            ("Latest day", latest, latest),
            ("Last 7 days", latest - timedelta(days=6), latest),
            ("Last 30 days", latest - timedelta(days=29), latest),
            ("All time", None, None),
        )
        return [
            {
                "label": label,
                "url": f"{base_url}?"
                + urlencode({**(extra or {}), **self._range_query(start, end)}),
            }
            for label, start, end in options
        ]

    def _changelist_url(self, **lookups):
        query = {
            key: value.isoformat() if isinstance(value, datetime) else value
            for key, value in lookups.items()
            if value is not None
        }
        return (
            reverse("admin:api_endpointaccesslog_changelist") + "?" + urlencode(query)
        )

    @staticmethod
    def _ratio(count_field):
        return ExpressionWrapper(
            Cast(count_field, FloatField()) / Cast("request_count", FloatField()),
            output_field=FloatField(),
        )

    def _build_sessions(self, events):
        """Group time-ordered (timestamp, endpoint, status, suspicious) rows into sessions."""
        sessions = []
        for timestamp, endpoint, status_code, suspicious in events:
            if not sessions or timestamp - sessions[-1]["end"] > self.SESSION_GAP:
                sessions.append(
                    {
                        "start": timestamp,
                        "end": timestamp,
                        "requests": 0,
                        "errors": 0,
                        "suspicious": 0,
                        "endpoint_set": set(),
                    }
                )
            session = sessions[-1]
            session["end"] = timestamp
            session["requests"] += 1
            session["endpoint_set"].add(endpoint)
            if status_code is None or status_code >= 400:
                session["errors"] += 1
            if suspicious:
                session["suspicious"] += 1

        for session in sessions:
            session["endpoints"] = len(session.pop("endpoint_set"))
            session["duration_min"] = int(
                (session["end"] - session["start"]).total_seconds() // 60
            )
        return sessions

    def ip_summary_view(self, request):
        """Visitors list: one row per IP for a date range, aggregated in SQL."""
        from api.models import FlaggedIP
        from core.services.feature_flag_service import feature_flags

        latest = self._latest_day()
        start, end = self._date_range(request, latest)
        range_query = self._range_query(start, end)
        sort = request.GET.get("sort")
        if sort not in self.VISITOR_SORTS:
            sort = "last_seen"
        direction = "asc" if request.GET.get("dir") == "asc" else "desc"
        sort_prefix = "" if direction == "asc" else "-"

        logs = self._scope(self.model.objects.all(), start, end)
        suspicious_q = self._suspicious_q()

        visitors = (
            logs.values("ip_address")
            .annotate(
                request_count=Count("id"),
                first_seen=Min("timestamp"),
                last_seen=Max("timestamp"),
                unique_endpoints=Count("endpoint", distinct=True),
                error_count=Count(
                    "id",
                    filter=Q(status_code__gte=400) | Q(status_code__isnull=True),
                ),
                notfound_count=Count("id", filter=Q(status_code=404)),
                suspicious_hits=Count("id", filter=suspicious_q),
                suspicious_endpoints=Count(
                    "endpoint", distinct=True, filter=suspicious_q
                ),
            )
            .annotate(
                error_ratio=self._ratio("error_count"),
                notfound_ratio=self._ratio("notfound_count"),
            )
            .order_by(f"{sort_prefix}{self.VISITOR_SORTS[sort]}", "ip_address")
        )

        page = Paginator(visitors, self.VISITORS_PER_PAGE).get_page(
            request.GET.get("page")
        )
        rows = list(page.object_list)
        flagged = FlaggedIP.objects.in_bulk(
            [row["ip_address"] for row in rows], field_name="ip_address"
        )
        lo, hi = self._bounds(start, end)

        for row in rows:
            ip = row["ip_address"]
            row["error_rate"] = round(row["error_ratio"] * 100, 1)
            row["notfound_rate"] = round(row["notfound_ratio"] * 100, 1)
            row["classification"] = self._classify_ip(row)
            row["ip_display"] = self._format_ip(ip)
            row["is_ipv6"] = ":" in ip
            flag = flagged.get(ip)
            row["ban_status"] = (
                ("banned" if flag.is_active else "flagged") if flag else "none"
            )
            row["flag_reason"] = flag.reason if flag else ""
            row["detail_url"] = (
                reverse("admin:endpointaccesslog_ip_detail")
                + "?"
                + urlencode({"ip": ip, **range_query})
            )
            row["requests_url"] = self._changelist_url(
                ip_address=ip, timestamp__gte=lo, timestamp__lt=hi
            )

        totals = logs.aggregate(
            requests=Count("id"),
            unique_ips=Count("ip_address", distinct=True),
            logged_in_users=Count("user", distinct=True),
        )
        daily = list(
            logs.annotate(day=TruncDate("timestamp"))
            .values("day")
            .annotate(
                requests=Count("id"),
                unique_ips=Count("ip_address", distinct=True),
            )
            .order_by("-day")[:90]
        )

        sort_columns = []
        for key, label in self.VISITOR_COLUMNS:
            active = key == sort
            next_dir = "asc" if active and direction == "desc" else "desc"
            sort_columns.append(
                {
                    "label": label,
                    "arrow": ("▲" if direction == "asc" else "▼") if active else "",
                    "url": "?"
                    + urlencode({**range_query, "sort": key, "dir": next_dir}),
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "title": "Visitors by IP",
            "page": page,
            "visitors": rows,
            "totals": totals,
            "daily": daily,
            "presets": self._range_presets(
                reverse("admin:endpointaccesslog_ip_summary"), latest
            ),
            "range_query": range_query,
            "sort": sort,
            "direction": direction,
            "sort_columns": sort_columns,
            "page_query": urlencode({**range_query, "sort": sort, "dir": direction}),
            "forensic_logging": feature_flags.is_enabled(
                "SECURITY_FORENSIC_LOGGING_ENABLED"
            ),
            "opts": self.model._meta,
            "cl": {"model_admin": self},
        }

        return render(request, "admin/endpoint_access_log_ip_summary.html", context)

    def ip_detail_view(self, request):
        """Per-IP drill-down: daily totals and activity sessions for a date range."""
        from core.services.feature_flag_service import feature_flags

        try:
            ip = str(ipaddress.ip_address(request.GET.get("ip", "")))
        except ValueError:
            raise Http404("Invalid IP address")

        latest = self._latest_day()
        start, end = self._date_range(request, latest)
        range_query = self._range_query(start, end)
        logs = self._scope(self.model.objects.filter(ip_address=ip), start, end)
        suspicious = Case(
            When(self._suspicious_q(), then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        )

        totals = logs.aggregate(
            requests=Count("id"),
            endpoints=Count("endpoint", distinct=True),
            errors=Count(
                "id", filter=Q(status_code__gte=400) | Q(status_code__isnull=True)
            ),
            flagged=Count("id", filter=Q(is_flagged=True)),
        )

        daily = list(
            logs.annotate(day=TruncDate("timestamp"))
            .values("day")
            .annotate(
                requests=Count("id"),
                unique_endpoints=Count("endpoint", distinct=True),
                error_count=Count(
                    "id",
                    filter=Q(status_code__gte=400) | Q(status_code__isnull=True),
                ),
                suspicious_hits=Count("id", filter=self._suspicious_q()),
            )
            .order_by("day")
        )
        for row in daily:
            lo, hi = self._bounds(row["day"], row["day"])
            row["requests_url"] = self._changelist_url(
                ip_address=ip, timestamp__gte=lo, timestamp__lt=hi
            )

        events = list(
            logs.annotate(suspicious=suspicious)
            .order_by("timestamp")
            .values_list("timestamp", "endpoint", "status_code", "suspicious")[
                : self.DETAIL_ROW_CAP + 1
            ]
        )
        truncated = len(events) > self.DETAIL_ROW_CAP
        sessions = self._build_sessions(events[: self.DETAIL_ROW_CAP])
        for number, session in enumerate(sessions, start=1):
            session["number"] = number
            session["requests_url"] = self._changelist_url(
                ip_address=ip,
                timestamp__gte=session["start"],
                timestamp__lte=session["end"],
            )

        context = {
            **self.admin_site.each_context(request),
            "title": f"Visitor {ip}",
            "ip": ip,
            "totals": totals,
            "daily": daily,
            "sessions": sessions,
            "truncated": truncated,
            "row_cap": self.DETAIL_ROW_CAP,
            "range_query": range_query,
            "presets": self._range_presets(
                reverse("admin:endpointaccesslog_ip_detail"), latest, {"ip": ip}
            ),
            "back_url": reverse("admin:endpointaccesslog_ip_summary")
            + "?"
            + urlencode(range_query),
            "forensic_logging": feature_flags.is_enabled(
                "SECURITY_FORENSIC_LOGGING_ENABLED"
            ),
            "opts": self.model._meta,
            "cl": {"model_admin": self},
        }

        return render(request, "admin/endpoint_access_log_ip_detail.html", context)

    # ── Endpoint Summary View ─────────────────────────────────────────

    def endpoint_summary_view(self, request):
        """Show endpoint-level summary: which endpoints are hit most, by whom."""
        from django.db.models import Count, Max, Min

        endpoint_stats = (
            self.model.objects.values("endpoint", "method")
            .annotate(
                request_count=Count("id"),
                unique_ips=Count("ip_address", distinct=True),
                first_seen=Min("timestamp"),
                last_seen=Max("timestamp"),
                error_count=Count(
                    "id",
                    filter=Q(status_code__gte=400) | Q(status_code__isnull=True),
                ),
                flagged_count=Count("id", filter=Q(is_flagged=True)),
            )
            .order_by("-request_count")
        )

        for stat in endpoint_stats:
            endpoint = stat["endpoint"]
            total = stat["request_count"]
            stat["error_rate"] = (
                round(stat["error_count"] / total * 100, 1) if total else 0
            )

            # Is this a suspicious endpoint?  Admin API paths are excluded
            # because they require authentication and are the admin's own
            # browsing, not an attack probe.
            stat["is_suspicious"] = (
                not endpoint.startswith(self._ADMIN_API_PREFIX)
                and any(
                    pat in endpoint for pat in self._SUSPICIOUS_ENDPOINT_PATTERNS
                )
            )

            # Top IPs hitting this endpoint
            top_ips = (
                self.model.objects.filter(
                    endpoint=endpoint, method=stat["method"]
                )
                .values("ip_address")
                .annotate(cnt=Count("id"))
                .order_by("-cnt")[:5]
            )
            stat["top_ips"] = [
                {"ip": ip["ip_address"], "count": ip["cnt"]} for ip in top_ips
            ]

        context = {
            **self.admin_site.each_context(request),
            "title": "Endpoint Summary",
            "endpoint_stats": list(endpoint_stats),
            "opts": self.model._meta,
            "cl": {"model_admin": self},
        }

        return render(
            request, "admin/endpoint_access_log_endpoint_summary.html", context
        )

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _classify_ip(stat):
        """Classify an IP's behavior based on its stats.

        Returns one of: attacker, scanner, suspicious, normal

        Classification is deliberately conservative to avoid false-flagging
        legitimate users who browse many decision pages.  Endpoint
        normalization (collapsing numeric IDs) is NOT applied here because
        this view operates on raw DB data — the counts are already inflated
        by unique decision/notification IDs.  Thresholds are therefore
        higher than the Redis-based real-time detection.
        """
        suspicious = stat.get("suspicious_hits", 0)
        unique = stat.get("unique_endpoints", 0)
        total = stat.get("request_count", 0)
        error_rate = stat.get("error_rate", 0)
        notfound_rate = stat.get("notfound_rate", 0)

        # Hits known attack endpoints (.env, /wp-admin, etc.) → attacker
        if suspicious >= 5:
            return "attacker"
        if suspicious >= 2 and unique >= 30:
            return "attacker"

        # High-volume scanning (many unique endpoints, mostly 404s)
        if unique >= 50 and notfound_rate >= 80:
            return "scanner"
        if unique >= 30 and notfound_rate >= 90:
            return "scanner"

        # Suspicious: requires both high endpoint diversity AND high error rate.
        # A legitimate user browsing 50 decision pages with <30% errors is
        # not suspicious — that's normal SPA usage.
        if unique >= 40 and notfound_rate >= 60:
            return "suspicious"
        if error_rate >= 70 and total >= 20:
            return "suspicious"
        if suspicious >= 1 and unique >= 20:
            return "suspicious"

        return "normal"

    @staticmethod
    def _format_ip(ip):
        """Format an IP address for display: truncate IPv6, leave IPv4 as-is."""
        if ":" in ip:
            # IPv6: show first 4 groups + truncated remainder
            groups = ip.split(":")
            if len(groups) > 4:
                return ":".join(groups[:4]) + ":…"
        return ip

    @staticmethod
    def _format_query_params(query_params):
        """Format query_params dict into a clean query string.

        Handles the stored format: {"GET": {"param": ["val1", "val2"]}, "POST": {...}}
        Returns a clean query string like: param1=val1&param2=val2
        Long values (>80 chars) are truncated with '…'.
        """
        if not query_params or not isinstance(query_params, dict):
            return ""

        parts = []
        # Look for GET params first (the common case)
        get_params = query_params.get("GET", None)
        if isinstance(get_params, dict):
            for key, values in get_params.items():
                if isinstance(values, list):
                    for v in values:
                        v_str = str(v)
                        if len(v_str) > 80:
                            v_str = v_str[:77] + "…"
                        parts.append(f"{key}={v_str}")
                else:
                    v_str = str(values)
                    if len(v_str) > 80:
                        v_str = v_str[:77] + "…"
                    parts.append(f"{key}={v_str}")
        else:
            # Flat params (no GET/POST wrapper)
            for key, values in query_params.items():
                if key in ("GET", "POST"):
                    continue
                if isinstance(values, list):
                    for v in values:
                        v_str = str(v)
                        if len(v_str) > 80:
                            v_str = v_str[:77] + "…"
                        parts.append(f"{key}={v_str}")
                else:
                    v_str = str(values)
                    if len(v_str) > 80:
                        v_str = v_str[:77] + "…"
                    parts.append(f"{key}={v_str}")

        return "&".join(parts)


class FlaggedIPAdmin(admin.ModelAdmin):
    """Admin interface for flagged/banned IPs."""

    list_display = (
        "ip_address",
        "reason",
        "is_active",
        "strike_count",
        "flagged_at",
        "last_seen",
        "ban_expires_at",
    )
    list_filter = ("is_active", "reason")
    search_fields = ("ip_address", "notes")
    ordering = ("-last_seen",)
    readonly_fields = ("flagged_at", "last_seen")
    actions = ["unban_selected", "ban_selected_permanent"]

    def get_queryset(self, request):
        return super().get_queryset(request)

    @admin.action(description="Unban selected IPs (deactivate)")
    def unban_selected(self, request, queryset):
        from api.services.security_service import security_service

        updated = 0
        for flagged_ip in queryset.filter(is_active=True):
            security_service.unban_ip(flagged_ip.ip_address)
            updated += 1
        self.message_user(
            request,
            f"Unbanned {updated} IP(s).",
            messages.SUCCESS,
        )

    @admin.action(description="Ban selected IPs permanently")
    def ban_selected_permanent(self, request, queryset):
        from api.services.security_service import security_service

        count = 0
        for flagged_ip in queryset:
            # Preserve the original flag reason (e.g. "velocity", "strikes")
            # so the audit trail is not lost when upgrading to permanent.
            reason = flagged_ip.reason if flagged_ip.reason else "manual"
            # duration_hours=0 is falsy → ban_ip treats it as permanent
            # (expiry_ts=float("inf")).  None would use the feature-flag default.
            security_service.ban_ip(
                flagged_ip.ip_address,
                reason=reason,
                duration_hours=0,
            )
            count += 1
        self.message_user(
            request,
            f"Permanently banned {count} IP(s).",
            messages.WARNING,
        )


class DailyTrafficAdmin(admin.ModelAdmin):
    """Admin interface for Daily Traffic"""

    list_display = ("date", "count")
    date_hierarchy = "date"


class ImportJobAdmin(admin.ModelAdmin):
    """Admin interface for Import Jobs with Redis chunking progress tracking"""

    list_display = (
        "id",
        "start_date",
        "start_date_day",
        "status",
        "created_at",
        "completed_at",
        "chunk_progress_display",
        "pipeline_progress_display",
        "entity_name",
        "stuck_indicator",
        "created_by",
        "end_date",
        "end_date_day",
        "decisions_count",
        "no_health_check_count",
        "no_health_check_link",
        "healthy_count",
        "warning_count",
        "health_error_count",
        "unknown_count",
        "health_percentage",
        "warning_health_checks_link",
        "failed_health_checks_link",
    )
    list_per_page = 3
    list_filter = ("status", "created_by", "created_at")
    search_fields = (
        "organization__label",
        "signer__first_name",
        "signer__last_name",
        "celery_task_id",
    )
    date_hierarchy = "created_at"
    readonly_fields = [
        "id",
        "created_at",
        "chunk_diagnostics_display",
        "failed_chunks_display",
        "stuck_job_diagnostics",
    ]
    fieldsets = (
        (
            "Basic Info",
            {
                "fields": (
                    "id",
                    "start_date",
                    "end_date",
                    "status",
                    "created_by",
                    "created_at",
                    "completed_at",
                )
            },
        ),
        (
            "Pipeline Progress",
            {
                "fields": (
                    "total_decisions",
                    "decisions_restored_from_redis",
                    "decisions_assigned_to_pipeline",
                    "new_decisions",
                    "updated_decisions",
                    "error_count",
                ),
                "description": "Track decisions through the import pipeline: API → Redis → Restored → Pipeline",
            },
        ),
        (
            "Redis Chunks",
            {
                "fields": (
                    "total_chunks",
                    "chunks_completed",
                    "chunks_failed",
                    "chunk_diagnostics_display",
                    "failed_chunks_display",
                    "chunk_task_ids",
                    "search_params",
                ),
                "description": "Track chunk-level progress and diagnose stuck chunks",
            },
        ),
        (
            "Diagnostics",
            {"fields": ("stuck_job_diagnostics",), "classes": ("collapse",)},
        ),
        (
            "Entity Filters",
            {"fields": ("organization", "unit", "signer"), "classes": ("collapse",)},
        ),
        (
            "Error Details",
            {"fields": ("error_details", "celery_task_id"), "classes": ("collapse",)},
        ),
    )
    actions = (
        "download_batch_health_report",
        "enqueue_backfill_missing_health_checks",
        "enqueue_retry_failed_decisions",
        "retry_failed_chunks",
        "retry_missing_chunks",
        "diagnose_stuck_job",
        "cancel_selected_imports",
        "reimport_from_scratch",
        "delete_with_cleanup",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(
            decisions_count=Count("decisions", distinct=True),
            health_checks_count=Count("decisions__health_check", distinct=True),
            healthy_count=Count(
                "decisions__health_check",
                filter=Q(decisions__health_check__overall_status=HealthStatus.HEALTHY),
                distinct=True,
            ),
            warning_count=Count(
                "decisions__health_check",
                filter=Q(decisions__health_check__overall_status=HealthStatus.WARNING),
                distinct=True,
            ),
            health_error_count=Count(
                "decisions__health_check",
                filter=Q(decisions__health_check__overall_status=HealthStatus.ERROR),
                distinct=True,
            ),
            unknown_count=Count(
                "decisions__health_check",
                filter=Q(decisions__health_check__overall_status=HealthStatus.UNKNOWN),
                distinct=True,
            ),
        )

    def entity_name(self, obj):
        if obj.organization:
            return f"Org: {obj.organization.label}"
        elif obj.signer:
            return f"Signer: {obj.signer}"
        return "All"

    entity_name.short_description = "Entity"

    def start_date_day(self, obj):
        """Display the day of the week for start_date"""
        if obj.start_date:
            return obj.start_date.strftime("%A")
        return "-"

    start_date_day.short_description = "Start Day"
    start_date_day.admin_order_field = "start_date"

    def end_date_day(self, obj):
        """Display the day of the week for end_date"""
        if obj.end_date:
            return obj.end_date.strftime("%A")
        return "-"

    end_date_day.short_description = "End Day"
    end_date_day.admin_order_field = "end_date"

    def stuck_indicator(self, obj):
        """Visual indicator for stuck jobs"""
        from datetime import timedelta

        from django.utils import timezone

        # Consider a job stuck if:
        # 1. Status is PROCESSING/FETCHING/SPLITTING for >2 hours
        # 2. Has missing chunks (total != completed + failed) for >1 hour

        age = timezone.now() - obj.created_at

        # Check for long-running active jobs
        if obj.status in [
            ImportJobStatus.PROCESSING,
            ImportJobStatus.FETCHING,
            ImportJobStatus.SPLITTING,
        ]:
            if age > timedelta(hours=2):
                hours = age.total_seconds() / 3600
                return format_html(
                    '<span style="color: red; font-size: 18px;" title="Stuck for {} hours">\u26a0\ufe0f STUCK</span>',
                    f"{hours:.1f}",
                )

        # Check for missing chunks
        if obj.total_chunks > 0:
            missing = obj.total_chunks - obj.chunks_completed - obj.chunks_failed
            if missing > 0 and age > timedelta(hours=1):
                return format_html(
                    '<span style="color: orange; font-size: 16px;" title="{} chunks missing">\u23f3 {}</span>',
                    missing,
                    missing,
                )

        return "-"

    stuck_indicator.short_description = "\u26a0\ufe0f"
    stuck_indicator.admin_order_field = "created_at"

    def decisions_count(self, obj):
        return getattr(obj, "decisions_count", 0)

    decisions_count.short_description = "Decisions"
    decisions_count.admin_order_field = "decisions_count"

    def no_health_check_count(self, obj):
        total = getattr(obj, "decisions_count", 0) or 0
        checks = getattr(obj, "health_checks_count", 0) or 0
        missing = total - checks
        return missing if missing >= 0 else 0

    no_health_check_count.short_description = "No health check"

    def no_health_check_link(self, obj):
        missing = self.no_health_check_count(obj)
        if missing <= 0:
            return "-"

        base_url = reverse(f"{self.admin_site.name}:core_decision_changelist")
        query = urlencode(
            {
                "import_job__id__exact": obj.id,
                "health_check__isnull": "1",
            }
        )
        url = f"{base_url}?{query}"
        return format_html('<a href="{}">View {}</a>', url, missing)

    no_health_check_link.short_description = "Missing"

    def healthy_count(self, obj):
        return getattr(obj, "healthy_count", 0)

    healthy_count.short_description = "Healthy"
    healthy_count.admin_order_field = "healthy_count"

    def warning_count(self, obj):
        return getattr(obj, "warning_count", 0)

    warning_count.short_description = "Warnings"
    warning_count.admin_order_field = "warning_count"

    def health_error_count(self, obj):
        return getattr(obj, "health_error_count", 0)

    health_error_count.short_description = "Errors"
    health_error_count.admin_order_field = "health_error_count"

    def unknown_count(self, obj):
        return getattr(obj, "unknown_count", 0)

    unknown_count.short_description = "Unknown"
    unknown_count.admin_order_field = "unknown_count"

    def health_percentage(self, obj):
        total = getattr(obj, "decisions_count", 0) or 0
        healthy = getattr(obj, "healthy_count", 0) or 0
        if total <= 0:
            return "-"
        pct = (healthy / total) * 100
        return f"{pct:.1f}%"

    health_percentage.short_description = "Health %"

    def chunk_progress_display(self, obj):
        """Display chunk processing progress"""
        if obj.total_chunks == 0:
            return "-"
        completed = obj.chunks_completed + obj.chunks_failed
        return f"{completed}/{obj.total_chunks}"

    chunk_progress_display.short_description = "Chunks"

    def pipeline_progress_display(self, obj):
        """Display decision pipeline progress: Fetched → Redis → Restored → Assigned"""
        if obj.total_decisions == 0:
            return "-"

        parts = []
        # (a) Stored in Redis (this is total_decisions)
        parts.append(f"Redis: {obj.total_decisions}")

        # (b) Restored from Redis
        if obj.decisions_restored_from_redis > 0:
            pct_restored = (
                obj.decisions_restored_from_redis / obj.total_decisions
            ) * 100
            parts.append(
                f"Restored: {obj.decisions_restored_from_redis} ({pct_restored:.0f}%)"
            )
        else:
            parts.append(f"Restored: 0")

        # (c) Assigned to pipeline
        if obj.decisions_assigned_to_pipeline > 0:
            pct_assigned = (
                obj.decisions_assigned_to_pipeline / obj.total_decisions
            ) * 100
            parts.append(
                f"Pipeline: {obj.decisions_assigned_to_pipeline} ({pct_assigned:.0f}%)"
            )
        else:
            parts.append(f"Pipeline: 0")

        return mark_safe(
            "<br>".join(parts)
        )  # nosec: B703/B308 - Safe HTML for admin display (internal data only)

    pipeline_progress_display.short_description = "Pipeline Progress"

    def failed_health_checks_link(self, obj):
        errors = getattr(obj, "health_error_count", 0) or 0
        if errors <= 0:
            return "-"

        base_url = reverse(
            f"{self.admin_site.name}:core_decisionhealthcheck_changelist"
        )
        query = urlencode(
            {
                "decision__import_job__id__exact": obj.id,
                "overall_status__exact": HealthStatus.ERROR,
            }
        )
        url = f"{base_url}?{query}"
        return format_html('<a href="{}">View {} failed</a>', url, errors)

    failed_health_checks_link.short_description = "Failures"

    def warning_health_checks_link(self, obj):
        warnings = getattr(obj, "warning_count", 0) or 0
        if warnings <= 0:
            return "-"

        base_url = reverse(
            f"{self.admin_site.name}:core_decisionhealthcheck_changelist"
        )
        query = urlencode(
            {
                "decision__import_job__id__exact": obj.id,
                "overall_status__exact": HealthStatus.WARNING,
            }
        )
        url = f"{base_url}?{query}"
        return format_html('<a href="{}">View {} warnings</a>', url, warnings)

    warning_health_checks_link.short_description = "Warnings"

    def download_batch_health_report(self, request, queryset):
        """Download orchestrator-derived batch health report as JSON."""
        if queryset.count() != 1:
            messages.error(
                request, "Select exactly one ImportJob to download a report."
            )
            return

        job = queryset.first()
        orchestrator = DecisionPipelineOrchestrator()
        report = orchestrator.get_batch_health_report(
            import_job_id=job.id, include_failures=True
        )

        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        filename = f"import-job-{job.id}-health-report.json"
        response = HttpResponse(payload, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    download_batch_health_report.short_description = (
        "Download batch health report (JSON)"
    )

    def enqueue_backfill_missing_health_checks(self, request, queryset):
        """Enqueue a Celery job to create missing DecisionHealthCheck records for this batch."""
        if queryset.count() != 1:
            messages.error(
                request, "Select exactly one ImportJob to backfill health checks."
            )
            return

        job = queryset.first()
        async_result = backfill_health_checks_for_import_job.delay(import_job_id=job.id)
        messages.success(
            request,
            f"Queued backfill of missing health checks for ImportJob #{job.id}. "
            f"Task id: {async_result.id}",
        )

    enqueue_backfill_missing_health_checks.short_description = (
        "Backfill missing health checks (async)"
    )

    def enqueue_retry_failed_decisions(self, request, queryset):
        """Enqueue a Celery job to retry all ERROR health checks in this batch."""
        if queryset.count() != 1:
            messages.error(
                request, "Select exactly one ImportJob to retry failed decisions."
            )
            return

        job = queryset.first()
        async_result = retry_failed_decisions_for_import_job.delay(
            import_job_id=job.id, component=None, max_workers=5  # Retry all components
        )
        messages.success(
            request,
            f"Queued retry of failed decisions for ImportJob #{job.id}. "
            f"Task id: {async_result.id}",
        )

    enqueue_retry_failed_decisions.short_description = "Retry ERROR decisions (async)"

    def chunk_diagnostics_display(self, obj):
        """Display detailed chunk processing diagnostics"""
        if obj.total_chunks == 0:
            return "No chunks"

        completed = obj.chunks_completed
        failed = obj.chunks_failed
        total = obj.total_chunks
        in_progress = total - completed - failed

        html = [
            f"<strong>Chunk Status:</strong><br>",
            f"[OK] Completed: {completed}/{total} ({100*completed/total:.1f}%)<br>",
            f"[ERROR] Failed: {failed}<br>",
        ]

        if in_progress > 0:
            html.append(f"⏳ In Progress/Missing: {in_progress}<br>")

        # Check for stuck chunks (job in PROCESSING but hasn't updated in 1+ hour)
        from datetime import timedelta

        from django.utils import timezone

        if obj.status == ImportJobStatus.PROCESSING:
            time_since_update = timezone.now() - obj.created_at
            if time_since_update > timedelta(hours=1) and in_progress > 0:
                html.append(
                    f"<br><span style='color: red; font-weight: bold;'>[WARN]️ WARNING: {in_progress} chunks stuck for {time_since_update.seconds//3600}h</span>"
                )

        return mark_safe(
            "".join(html)
        )  # nosec: B703/B308 - Safe HTML for admin display (internal data only)

    chunk_diagnostics_display.short_description = "Chunk Diagnostics"

    def failed_chunks_display(self, obj):
        """Display failed chunk task IDs for investigation"""
        if obj.chunks_failed == 0:
            return "No failures"

        # Get failed chunk task IDs from ImportFailure records
        from core.models.import_jobs import ImportFailure

        failures = ImportFailure.objects.filter(
            import_job=obj, task_id__in=obj.chunk_task_ids
        ).values("task_id", "error_message")[
            :10
        ]  # Limit to 10

        if not failures:
            return f"{obj.chunks_failed} failures (no details available)"

        html = ["<strong>Failed Chunks:</strong><br><ul>"]
        for failure in failures:
            task_id = failure["task_id"][:8]  # Short ID
            error = failure["error_message"][:50]  # Truncate
            html.append(f"<li>{task_id}: {error}...</li>")
        html.append("</ul>")

        if obj.chunks_failed > len(failures):
            html.append(f"<em>...and {obj.chunks_failed - len(failures)} more</em>")

        return mark_safe(
            "".join(html)
        )  # nosec: B703/B308 - Safe HTML for admin display (internal data only)

    failed_chunks_display.short_description = "Failed Chunks"

    def stuck_job_diagnostics(self, obj):
        """Comprehensive diagnostics for stuck jobs"""
        from datetime import timedelta

        from core.services.redis_decision_cache import RedisDecisionCache
        from django.utils import timezone

        html = ["<div style='font-family: monospace; font-size: 12px;'>"]

        # Job age
        age = timezone.now() - obj.created_at
        html.append(
            f"<strong>Job Age:</strong> {age.seconds//3600}h {(age.seconds%3600)//60}m<br>"
        )

        # Status
        html.append(f"<strong>Status:</strong> {obj.status}<br>")

        # Pipeline progress
        if obj.total_decisions > 0:
            html.append(f"<br><strong>Pipeline Progress:</strong><br>")
            html.append(f"  API → Redis: {obj.total_decisions}<br>")
            html.append(
                f"  Redis → Restored: {obj.decisions_restored_from_redis} ({100*obj.decisions_restored_from_redis/obj.total_decisions:.1f}%)<br>"
            )
            html.append(
                f"  Restored → Pipeline: {obj.decisions_assigned_to_pipeline} ({100*obj.decisions_assigned_to_pipeline/obj.total_decisions:.1f}%)<br>"
            )

        # Chunk progress
        if obj.total_chunks > 0:
            html.append(f"<br><strong>Chunk Progress:</strong><br>")
            html.append(f"  Total: {obj.total_chunks}<br>")
            html.append(
                f"  Completed: {obj.chunks_completed} ({100*obj.chunks_completed/obj.total_chunks:.1f}%)<br>"
            )
            html.append(f"  Failed: {obj.chunks_failed}<br>")
            missing = obj.total_chunks - obj.chunks_completed - obj.chunks_failed
            if missing > 0:
                html.append(
                    f"  <span style='color: orange;'>Missing/In Progress: {missing}</span><br>"
                )

        # [WARN]️ NEW: Chunk TTL diagnostics (helps diagnose expiration issues)
        if obj.total_chunks > 0 and obj.status in [
            ImportJobStatus.PROCESSING,
            ImportJobStatus.SPLITTING,
        ]:
            try:
                redis_cache = RedisDecisionCache()
                ttl_stats = redis_cache.get_job_ttl_stats(obj.id, sample_size=10)

                if "error" not in ttl_stats:
                    html.append(
                        f"<br><strong>Chunk TTL (sampled {ttl_stats['chunks_sampled']}):</strong><br>"
                    )
                    html.append(
                        f"  Min: {ttl_stats['ttl_min_hours']:.1f}h ({ttl_stats['ttl_min_seconds']}s)<br>"
                    )
                    html.append(
                        f"  Avg: {ttl_stats['ttl_avg_hours']:.1f}h ({ttl_stats['ttl_avg_seconds']:.0f}s)<br>"
                    )
                    html.append(
                        f"  Max: {ttl_stats['ttl_max_hours']:.1f}h ({ttl_stats['ttl_max_seconds']}s)<br>"
                    )

                    # Warn if chunks are close to expiring
                    if ttl_stats["ttl_min_hours"] < 6:
                        html.append(
                            f"  <span style='color: red;'>[WARN]️ WARNING: Chunks expiring soon!</span><br>"
                        )
                    elif ttl_stats["ttl_min_hours"] < 24:
                        html.append(
                            f"  <span style='color: orange;'>[WARN]️ CAUTION: Less than 24h remaining</span><br>"
                        )
                else:
                    html.append(
                        f"<br><span style='color: gray;'>Chunks already processed (not in Redis)</span><br>"
                    )
            except Exception as e:
                html.append(
                    f"<br><span style='color: gray;'>Could not check TTL: {str(e)}</span><br>"
                )

        # Check for stuck state
        if obj.status == ImportJobStatus.PROCESSING:
            if age > timedelta(hours=2):
                html.append(
                    f"<br><span style='color: red; font-weight: bold;'>[WARN]️ JOB STUCK: No completion after {age.seconds//3600}h</span><br>"
                )
                html.append(f"<br><strong>Suggested Actions:</strong><br>")
                html.append(f"  1. Check Celery worker logs<br>")
                html.append(f"  2. Verify Redis has chunk data<br>")
                html.append(f"  3. Use 'Retry Missing Chunks' action<br>")
                html.append(f"  4. Check if worker is running<br>")

        # Check task IDs
        if obj.chunk_task_ids:
            html.append(f"<br><strong>Task Tracking:</strong><br>")
            html.append(f"  Total tasks dispatched: {len(obj.chunk_task_ids)}<br>")
            html.append(
                f"  Tasks reported complete: {obj.chunks_completed + obj.chunks_failed}<br>"
            )
            unreported = len(obj.chunk_task_ids) - (
                obj.chunks_completed + obj.chunks_failed
            )
            if unreported > 0:
                html.append(
                    f"  <span style='color: orange;'>Tasks not reported: {unreported}</span><br>"
                )

        html.append("</div>")
        return mark_safe("".join(html))

    stuck_job_diagnostics.short_description = "Stuck Job Diagnostics"

    def retry_failed_chunks(self, request, queryset):
        """Retry all failed chunks for selected import jobs"""
        if queryset.count() != 1:
            self.message_user(
                request, "Please select exactly one import job", messages.ERROR
            )
            return

        job = queryset.first()

        # Get failed chunk task IDs
        from core.models.import_jobs import ImportFailure
        from core.tasks.tasks_decisions_import import store_decisions_from_redis

        failures = ImportFailure.objects.filter(
            import_job=job, task_id__in=job.chunk_task_ids
        )

        if not failures:
            self.message_user(
                request, f"No failed chunks found for job {job.id}", messages.WARNING
            )
            return

        # Extract chunk IDs from failures (if stored in error details)
        retried = 0
        for failure in failures:
            # Try to extract chunk_id from error message/details
            # This assumes chunk_id is stored somewhere in the failure record
            # You may need to adjust based on your actual error message format
            if "chunk_id" in (failure.error_details or {}):
                chunk_id = failure.error_details["chunk_id"]
                store_decisions_from_redis.delay(
                    chunk_id=chunk_id,
                    job_id=job.id,
                    skip_opensearch=False,
                    delay_seconds=retried * 0.5,  # Stagger retries
                )
                retried += 1

        self.message_user(
            request,
            f"Retrying {retried} failed chunks for job {job.id}",
            messages.SUCCESS,
        )

    retry_failed_chunks.short_description = "Retry failed chunks"

    def retry_missing_chunks(self, request, queryset):
        """Retry chunks that haven't reported completion (stuck/lost)"""
        if queryset.count() != 1:
            self.message_user(
                request, "Please select exactly one import job", messages.ERROR
            )
            return

        job = queryset.first()

        missing_count = job.total_chunks - job.chunks_completed - job.chunks_failed

        if missing_count <= 0:
            self.message_user(
                request, f"No missing chunks for job {job.id}", messages.INFO
            )
            return

        # Check if Redis still has the chunk data
        from core.services.redis_decision_cache import RedisDecisionCache

        RedisDecisionCache()

        # Find chunks that exist in Redis but haven't been processed
        # This requires listing all Redis keys for this job

        from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
        from django_redis import get_redis_connection

        redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)

        # Get all chunk keys for this job (pattern: decision_chunk:{date}_{chunk_num}_*)
        date_str = job.start_date.isoformat()
        pattern = f"decision_chunk:{date_str}_*"

        existing_chunks = []
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            existing_chunks.append(key_str)

        self.message_user(
            request,
            f"Found {len(existing_chunks)} chunks in Redis. Missing chunks: {missing_count}. "
            f"Check Celery worker logs for task {job.celery_task_id}. "
            f"You may need to manually retry specific chunk IDs.",
            messages.WARNING,
        )

    retry_missing_chunks.short_description = "Diagnose missing chunks"

    def diagnose_stuck_job(self, request, queryset):
        """Generate detailed diagnostic report for stuck jobs"""
        if queryset.count() != 1:
            self.message_user(
                request, "Please select exactly one import job", messages.ERROR
            )
            return

        job = queryset.first()

        import json

        from django.utils import timezone

        report = {
            "job_id": job.id,
            "status": job.status,
            "age_hours": (timezone.now() - job.created_at).seconds // 3600,
            "pipeline": {
                "total_decisions": job.total_decisions,
                "restored_from_redis": job.decisions_restored_from_redis,
                "assigned_to_pipeline": job.decisions_assigned_to_pipeline,
                "new": job.new_decisions,
                "updated": job.updated_decisions,
                "errors": job.error_count,
            },
            "chunks": {
                "total": job.total_chunks,
                "completed": job.chunks_completed,
                "failed": job.chunks_failed,
                "missing": job.total_chunks - job.chunks_completed - job.chunks_failed,
                "task_count": len(job.chunk_task_ids),
            },
            "celery_task_id": job.celery_task_id,
            "search_params": job.search_params,
        }

        # Check Redis for remaining chunks
        from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
        from django_redis import get_redis_connection

        redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)
        date_str = job.start_date.isoformat()
        pattern = f"decision_chunk:{date_str}_*"

        redis_chunks = []
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            redis_chunks.append(key_str)

        report["redis_chunks_remaining"] = len(redis_chunks)
        report["redis_chunk_keys"] = redis_chunks[:10]  # Sample

        # Download as JSON
        payload = json.dumps(report, ensure_ascii=False, indent=2)
        filename = f"stuck-job-{job.id}-diagnostic.json"
        response = HttpResponse(payload, content_type="application/json; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    diagnose_stuck_job.short_description = "Download diagnostic report (JSON)"

    # ========================================================================
    # Cancel / Purge Imports
    # ========================================================================

    @admin.action(description="Cancel selected imports (revoke tasks, clean Redis)")
    def cancel_selected_imports(self, request, queryset):
        """Cancel selected ImportJobs: revoke Celery tasks + clean Redis chunks."""
        cancelled = 0
        skipped = 0

        for job in queryset:
            result = job.cancel(revoke_task=True, clean_redis=True)
            if result.get("status") == "cancelled":
                cancelled += 1
            else:
                skipped += 1

        if cancelled > 0:
            self.message_user(
                request,
                f"[OK] Cancelled {cancelled} import job(s). Tasks revoked, Redis chunks cleaned.",
                messages.SUCCESS,
            )
        if skipped > 0:
            self.message_user(
                request,
                f"{skipped} job(s) were already in terminal state, skipped.",
                messages.WARNING,
            )

    @admin.action(
        description="Re-import from scratch (cancel if active, re-enqueue same date)"
    )
    def reimport_from_scratch(self, request, queryset):
        """Cancel selected jobs (if still active) and enqueue fresh jobs with
        the same date range and filters, then kick the queue.

        Works for stuck, cancelled, failed, AND completed jobs — useful for
        both recovering stuck imports and re-running a day from zero.
        """
        from core.services.import_job_queue import ImportJobQueue

        queue = ImportJobQueue()
        requeued = []

        for job in queryset:
            # Cancel if still in a non-terminal state (no-op otherwise)
            job.cancel(revoke_task=True, clean_redis=True)

            new_job = queue.enqueue_job(
                target_date=job.start_date,
                search_params=job.search_params or {},
                created_by=job.created_by or request.user,
                organization_id=job.organization_id,
                unit_id=job.unit_id,
                signer_id=job.signer_id,
                auto_dispatch=False,  # kick once after the loop
                skip_duplicates=False,  # old job is cancelled; always create fresh
                import_type=job.import_type,
            )
            requeued.append((job.id, new_job.id))

        # Kick the queue — dispatch_next_job only fires on enqueue/completion
        queue.dispatch_next_job()

        pairs = ", ".join(f"#{old} → #{new}" for old, new in requeued)
        self.message_user(
            request,
            f"[OK] Re-queued {len(requeued)} import(s) from scratch: {pairs}. "
            f"Queue dispatched.",
            messages.SUCCESS,
        )

    @admin.action(
        description="Delete selected (cancel if active, clean Redis, remove record)"
    )
    def delete_with_cleanup(self, request, queryset):
        """Cancel each job (if still active), clean its Redis chunks, then
        hard-delete the row. Unlike Django's built-in delete, this never
        leaves orphaned Celery tasks or Redis chunk keys behind.

        ImportFailure rows are removed automatically via FK cascade.
        """
        deleted = []

        for job in queryset:
            job.cancel(revoke_task=True, clean_redis=True)  # no-op if terminal
            deleted.append(job.id)
            job.delete()

        ids = ", ".join(f"#{i}" for i in deleted)
        self.message_user(
            request,
            f"[OK] Deleted {len(deleted)} import job(s): {ids}. "
            f"Tasks revoked and Redis chunks cleaned where applicable.",
            messages.SUCCESS,
        )

    def cancel_all_imports_view(self, request):
        """View to cancel ALL in-progress imports with optional RabbitMQ purge."""
        from core.services.import_job_queue import ImportJobQueue

        if request.method == "POST":
            purge_rabbitmq = request.POST.get("purge_rabbitmq") == "1"
            clean_redis = request.POST.get("clean_redis", "1") == "1"

            queue = ImportJobQueue()
            result = queue.cancel_all_in_progress_imports(
                purge_rabbitmq=purge_rabbitmq,
                clean_redis=clean_redis,
            )

            msg_parts = [f"Cancelled {result['jobs_cancelled']} job(s)."]
            if result.get("redis_keys_deleted"):
                msg_parts.append(f"Redis DB 2 flushed.")
            if result.get("rabbitmq_purged"):
                msg_parts.append(f"RabbitMQ queue purged.")

            self.message_user(request, " ".join(msg_parts), messages.SUCCESS)
            return JsonResponse({"success": True, **result})

        # GET: Show confirmation page
        from core.models.import_jobs import ImportJob, ImportJobStatus

        cancelable = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.PENDING,
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.SPLITTING,
                ImportJobStatus.PROCESSING,
            ]
        )

        context = {
            **self.admin_site.each_context(request),
            "title": "Cancel All In-Progress Imports",
            "cancelable_jobs": cancelable,
            "cancelable_count": cancelable.count(),
            "opts": self.model._meta,
        }

        return render(request, "admin/cancel_all_imports_confirm.html", context)

    # ========================================================================
    # Queue Monitoring Features
    # ========================================================================

    def get_urls(self):
        """Add custom URLs for queue monitoring"""
        urls = super().get_urls()
        custom_urls = [
            path(
                "monitor/",
                self.admin_site.admin_view(self.monitor_view),
                name="import_job_monitor",
            ),
            path(
                "queue-status-json/",
                self.admin_site.admin_view(self.queue_status_json),
                name="import_job_queue_status_json",
            ),
            path(
                "clear-stale/",
                self.admin_site.admin_view(self.clear_stale_action),
                name="import_job_clear_stale",
            ),
            path(
                "clear-duplicates/",
                self.admin_site.admin_view(self.clear_duplicates_action),
                name="import_job_clear_duplicates",
            ),
            path(
                "dispatch-next/",
                self.admin_site.admin_view(self.dispatch_next_action),
                name="import_job_dispatch_next",
            ),
            path(
                "cancel-all/",
                self.admin_site.admin_view(self.cancel_all_imports_view),
                name="import_job_cancel_all",
            ),
        ]
        return custom_urls + urls

    def monitor_view(self, request):
        """Main queue monitoring dashboard view"""
        queue = ImportJobQueue()
        status = self._get_enhanced_queue_status(queue)

        context = {
            **self.admin_site.each_context(request),
            "title": "Import Queue Monitor",
            "queue_status": status,
            "opts": self.model._meta,
        }

        return render(request, "admin/import_queue_monitor.html", context)

    def queue_status_json(self, request):
        """JSON endpoint for queue status (for AJAX polling)"""
        queue = ImportJobQueue()
        status = self._get_enhanced_queue_status(queue)

        # Convert datetime objects to strings for JSON serialization
        for job in status["active_jobs"]:
            if not isinstance(job["created_at"], str):
                job["created_at"] = job["created_at"].isoformat()

        for job in status["pending_jobs"]:
            if not isinstance(job["created_at"], str):
                job["created_at"] = job["created_at"].isoformat()

        for job in status["recent_completed"]:
            if job.get("completed_at") and not isinstance(job["completed_at"], str):
                job["completed_at"] = job["completed_at"].isoformat()
            if job.get("created_at") and not isinstance(job["created_at"], str):
                job["created_at"] = job["created_at"].isoformat()

        return JsonResponse(status, safe=False)

    def clear_stale_action(self, request):
        """Clear stale jobs endpoint"""
        if request.method == "POST":
            max_age_hours = int(request.POST.get("max_age_hours", 1))
            queue = ImportJobQueue()
            count = queue.clear_stale_jobs(max_age_hours)

            if count > 0:
                # Try to dispatch next job
                dispatched = queue.dispatch_next_job()
                msg = f"[OK] Marked {count} stale job(s) as failed."
                if dispatched:
                    msg += f" Auto-dispatched job #{dispatched.id}."
                messages.success(request, msg)
            else:
                messages.info(request, "No stale jobs found.")

        return JsonResponse(
            {"success": True, "count": count if "count" in locals() else 0}
        )

    def clear_duplicates_action(self, request):
        """Clear duplicate jobs endpoint"""
        if request.method == "POST":
            deleted_count = self._clear_duplicate_jobs()

            if deleted_count > 0:
                messages.success(
                    request, f"[OK] Deleted {deleted_count} duplicate job(s)."
                )
            else:
                messages.info(request, "No duplicate jobs found.")

        return JsonResponse(
            {
                "success": True,
                "count": deleted_count if "deleted_count" in locals() else 0,
            }
        )

    def dispatch_next_action(self, request):
        """Manually dispatch next job endpoint"""
        if request.method == "POST":
            queue = ImportJobQueue()
            job = queue.dispatch_next_job()

            if job:
                messages.success(
                    request, f"[OK] Dispatched job #{job.id} for {job.start_date}"
                )
                return JsonResponse({"success": True, "job_id": job.id})
            else:
                messages.warning(
                    request, "[WARN] No job dispatched (at capacity or no pending jobs)"
                )
                return JsonResponse({"success": False, "message": "No job to dispatch"})

        return JsonResponse({"success": False})

    def _get_enhanced_queue_status(self, queue):
        """Get enhanced queue status with additional metrics"""
        status = queue.get_queue_status()

        # Add age information to active jobs
        for job in status["active_jobs"]:
            age = timezone.now() - job["created_at"]
            job["age_hours"] = age.total_seconds() / 3600
            job["age_display"] = self._format_age(age)
            job["is_stale"] = job["age_hours"] > 6

        # Check for stale jobs
        stale_count = sum(1 for job in status["active_jobs"] if job["is_stale"])
        status["stale_count"] = stale_count
        status["has_stale_jobs"] = stale_count > 0

        # Get recent completed jobs
        recent_completed = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.COMPLETED,
                ImportJobStatus.PARTIALLY_COMPLETED,
                ImportJobStatus.FAILED,
            ]
        ).order_by("-completed_at")[:5]

        status["recent_completed"] = [
            {
                "id": job.id,
                "start_date": job.start_date,
                "status": job.status,
                "total_decisions": job.total_decisions,
                "completed_at": job.completed_at,
                "duration": (
                    self._format_duration(job.created_at, job.completed_at)
                    if job.completed_at
                    else "N/A"
                ),
            }
            for job in recent_completed
        ]

        # Add health status
        status["health_status"] = "healthy"
        if status["has_stale_jobs"]:
            status["health_status"] = "error"
        elif status["active_count"] == 0 and status["pending_count"] > 0:
            status["health_status"] = "warning"

        return status

    def _format_age(self, age):
        """Format timedelta as human-readable string"""
        hours = age.total_seconds() / 3600
        if hours < 1:
            minutes = age.total_seconds() / 60
            return f"{int(minutes)}m"
        elif hours < 24:
            return f"{hours:.1f}h"
        else:
            days = hours / 24
            return f"{days:.1f}d"

    def _format_duration(self, start, end):
        """Format duration between two datetimes"""
        if not end or not start:
            return "N/A"
        duration = end - start
        return self._format_age(duration)

    def _clear_duplicate_jobs(self):
        """Remove duplicate pending/active jobs, keeping the oldest"""
        pending_and_active = ImportJob.objects.filter(
            status__in=[
                ImportJobStatus.PENDING,
                ImportJobStatus.RUNNING,
                ImportJobStatus.FETCHING,
                ImportJobStatus.PROCESSING,
                ImportJobStatus.SPLITTING,
            ]
        ).order_by("start_date", "organization", "unit", "signer", "created_at")

        seen = {}
        deleted_count = 0

        for job in pending_and_active:
            key = (
                job.start_date,
                job.end_date,
                job.organization_id,
                job.unit_id,
                job.signer_id,
            )

            if key not in seen:
                seen[key] = job
            else:
                job.delete()
                deleted_count += 1

        return deleted_count

    def changelist_view(self, request, extra_context=None):
        """Add queue status to changelist view"""
        queue = ImportJobQueue()
        extra_context = extra_context or {}
        extra_context["queue_status"] = queue.get_queue_status()
        return super().changelist_view(request, extra_context=extra_context)
