import json
from datetime import datetime

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.services.decision_health_service import DecisionHealthService
from django.contrib import admin, messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe


class DecisionHealthCheckAdmin(admin.ModelAdmin):
    """Admin interface for viewing and managing decision health checks"""

    list_display = [
        "decision_ada",
        "overall_status_badge",
        "component_status_summary",
        "last_checked_at",
        "check_duration_ms",
        "action_buttons",
    ]

    list_filter = [
        "overall_status",
        "has_errors",
        "has_warnings",
        "ingestion_status",
        "relations_status",
        "entities_status",
        "document_extraction_status",
        "opensearch_status",
        "coverage_status",
        "last_checked_at",
    ]

    search_fields = [
        "decision__ada",
        "decision__subject",
        "decision__organization__label",
    ]

    readonly_fields = [
        "decision",
        "overall_status",
        "last_checked_at",
        "check_duration_ms",
        "findings_display",
        "component_details",
    ]

    actions = ["refresh_health_checks", "export_health_report"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:pk>/refresh/",
                self.admin_site.admin_view(self.refresh_single_check),
                name="core_decisionhealthcheck_refresh",
            ),
        ]
        return custom_urls + urls

    def decision_ada(self, obj):
        """Display decision ADA with link to decision admin"""
        if obj.decision:
            url = reverse("admin:core_decision_change", args=[obj.decision.id])
            return format_html('<a href="{}">{}</a>', url, obj.decision.ada)
        return "-"

    decision_ada.short_description = "Decision ADA"

    def overall_status_badge(self, obj):
        """Display status as colored badge"""
        colors = {
            HealthStatus.HEALTHY: "green",
            HealthStatus.WARNING: "orange",
            HealthStatus.ERROR: "red",
            HealthStatus.UNKNOWN: "gray",
        }
        color = colors.get(obj.overall_status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 2px 6px; border-radius: 3px; font-size: 11px;">{}</span>',
            color,
            obj.overall_status,
        )

    overall_status_badge.short_description = "Status"

    def component_status_summary(self, obj):
        """Display component statuses as emoji summary"""
        statuses = obj.component_statuses
        icons = {
            HealthStatus.HEALTHY: "[OK]",
            HealthStatus.WARNING: "[WARN]️",
            HealthStatus.ERROR: "[ERROR]",
            HealthStatus.UNKNOWN: "[UNKNOWN]",
        }

        summary_parts = []
        for component, status in statuses.items():
            icon = icons.get(status, "[UNKNOWN]")
            summary_parts.append(f"{component[:3]}{icon}")

        return format_html(" ".join(summary_parts))

    component_status_summary.short_description = "Components"

    def action_buttons(self, obj):
        """Display action buttons"""
        refresh_url = reverse("admin:core_decisionhealthcheck_refresh", args=[obj.pk])
        return format_html(
            '<a class="button" href="{}">[RETRY] Refresh</a>', refresh_url
        )

    action_buttons.short_description = "Actions"

    def findings_display(self, obj):
        """Display detailed findings in a readable format"""
        if not obj.findings:
            return "No detailed findings available"

        html_parts = []
        for component, finding in obj.findings.items():
            status = finding.get("status", "UNKNOWN")
            message = finding.get("message", "No message")
            details = finding.get("details", {})

            color = {
                "HEALTHY": "green",
                "WARNING": "orange",
                "ERROR": "red",
                "UNKNOWN": "gray",
            }.get(status, "gray")

            html_parts.append(
                f"""
                <div style="margin: 10px 0; padding: 10px; border-left: 4px solid {color};">
                    <strong>{component.title()}</strong> ({status})<br>
                    {message}<br>
                    {json.dumps(details, indent=2) if details else ''}
                </div>
            """
            )

        return mark_safe(
            "".join(html_parts)
        )  # nosec: B703/B308 - Safe HTML for admin display (internal data only)

    findings_display.short_description = "Detailed Findings"

    def component_details(self, obj):
        """Display component statuses in a table format"""
        components = obj.component_statuses

        html = """
        <table style="width: 100%; border-collapse: collapse;">
            <tr><th style="border: 1px solid #ddd; padding: 8px;">Component</th>
                <th style="border: 1px solid #ddd; padding: 8px;">Status</th></tr>
        """

        for component, status in components.items():
            color = {
                "HEALTHY": "#d4edda",
                "WARNING": "#fff3cd",
                "ERROR": "#f8d7da",
                "UNKNOWN": "#e2e3e5",
            }.get(status, "#e2e3e5")

            html += f"""
            <tr>
                <td style="border: 1px solid #ddd; padding: 8px;">{component.replace('_', ' ').title()}</td>
                <td style="border: 1px solid #ddd; padding: 8px; background-color: {color};">{status}</td>
            </tr>
            """

        html += "</table>"
        return mark_safe(
            html
        )  # nosec: B703/B308 - Safe HTML for admin display (internal data only)

    component_details.short_description = "Component Status Details"

    def refresh_health_checks(self, request, queryset):
        """Admin action to refresh health checks for selected decisions"""
        health_service = DecisionHealthService()
        refreshed_count = 0

        for health_check in queryset:
            try:
                health_service.check_decision_health(
                    health_check.decision, force_refresh=True
                )
                refreshed_count += 1
            except Exception as e:
                messages.error(
                    request, f"Failed to refresh {health_check.decision.ada}: {str(e)}"
                )

        messages.success(request, f"Refreshed {refreshed_count} health checks")

    refresh_health_checks.short_description = "Refresh selected health checks"

    def export_health_report(self, request, queryset):
        """Export health report as JSON"""
        data = []
        for health_check in queryset:
            data.append(
                {
                    "ada": health_check.decision.ada,
                    "overall_status": health_check.overall_status,
                    "component_statuses": health_check.component_statuses,
                    "findings": health_check.findings,
                    "last_checked": health_check.last_checked_at.isoformat(),
                }
            )

        response = JsonResponse(
            {"health_checks": data}, json_dumps_params={"indent": 2}
        )
        response["Content-Disposition"] = (
            f'attachment; filename="health_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json"'
        )
        return response

    export_health_report.short_description = "Export health report (JSON)"

    def refresh_single_check(self, request, pk):
        """Refresh health check for a single decision"""
        health_check = get_object_or_404(DecisionHealthCheck, pk=pk)
        health_service = DecisionHealthService()

        try:
            health_service.check_decision_health(
                health_check.decision, force_refresh=True
            )
            messages.success(
                request,
                f"Health check refreshed for decision {health_check.decision.ada}",
            )
        except Exception as e:
            messages.error(request, f"Failed to refresh health check: {str(e)}")

        return redirect("admin:core_decisionhealthcheck_changelist")


class DecisionHealthSummaryAdmin(admin.ModelAdmin):
    """Admin interface for health summaries"""

    list_display = [
        "date",
        "organization",
        "total_decisions",
        "health_percentage",
        "error_decisions",
        "warning_decisions",
        "last_updated",
    ]

    list_filter = ["date", "organization", "last_updated"]

    readonly_fields = ["health_percentage"]

    def health_percentage(self, obj):
        return f"{obj.health_percentage}%"

    health_percentage.short_description = "Health %"
