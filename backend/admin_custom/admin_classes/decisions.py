from django import forms
from django.contrib import admin, messages


class ImportDecisionsForm(forms.Form):
    """Form for importing decisions"""

    pass  # Add form fields as needed


class DecisionAdmin(admin.ModelAdmin):
    """Admin interface for Decision model"""

    list_display = ("ada", "subject", "organization", "issue_date", "status")
    list_filter = ("status", "decision_type", "has_private_data")
    search_fields = ("ada", "subject", "protocol_number")
    date_hierarchy = "issue_date"

    actions = ["import_decisions", "check_pipeline_health", "fix_common_issues"]

    def import_decisions(self, request, queryset=None):
        """Import decisions action"""
        # Implementation

    def check_pipeline_health(self, request, queryset):
        """Run health checks on selected decisions"""
        from core.models.decision_health import HealthStatus
        from core.services.decision_health_service import DecisionHealthService

        health_service = DecisionHealthService()
        decisions = list(queryset)

        if len(decisions) > 50:
            messages.warning(
                request,
                f"Health check limited to 50 decisions (selected {len(decisions)})",
            )
            decisions = decisions[:50]

        # Run bulk health checks
        results = health_service.bulk_check_decisions(decisions)

        # Show summary message
        summary = results["summary"]
        messages.success(
            request,
            f"Health check completed: {summary['healthy']} healthy, "
            f"{summary['warnings']} warnings, {summary['errors']} errors",
        )

        # Show specific issues if any
        if summary["errors"] > 0:
            error_decisions = [
                hc.decision.ada
                for hc in results["health_checks"]
                if hc.overall_status == HealthStatus.ERROR
            ][
                :5
            ]  # Show first 5
            messages.error(
                request,
                f"Decisions with errors: {', '.join(error_decisions)}"
                + (
                    f" and {summary['errors'] - 5} more"
                    if summary["errors"] > 5
                    else ""
                ),
            )

    check_pipeline_health.short_description = "[SCAN] Check pipeline health"

    def fix_common_issues(self, request, queryset):
        """Attempt to fix common issues for selected decisions"""
        from core.tasks.health_check_tasks import auto_fix_simple_issues

        decision_count = queryset.count()

        if decision_count > 20:
            messages.warning(
                request, f"Auto-fix limited to 20 decisions (selected {decision_count})"
            )
            decision_adas = list(queryset[:20].values_list("ada", flat=True))
        else:
            decision_adas = list(queryset.values_list("ada", flat=True))

        # Queue auto-fix task for these specific decisions
        try:
            auto_fix_simple_issues.delay(decision_adas=decision_adas)

            messages.success(
                request,
                f"Queued auto-fix for {len(decision_adas)} decisions. "
                "Check back in a few minutes to see results.",
            )
        except Exception as e:
            messages.error(request, f"Failed to queue auto-fix: {str(e)}")

    fix_common_issues.short_description = "[CONFIG] Attempt auto-fix"


class AttachmentAdmin(admin.ModelAdmin):
    """Admin interface for Attachment model"""

    list_display = ("id", "decision", "filename", "mime_type")
    list_filter = ("mime_type",)
    search_fields = ("filename", "decision__ada")


class OrganizationAdmin(admin.ModelAdmin):
    """Admin interface for Organization model"""

    list_display = ("label", "vat_number", "category")
    list_filter = ("category",)
    search_fields = ("label", "vat_number")


class UnitAdmin(admin.ModelAdmin):
    """Admin interface for Unit model"""

    list_display = ("label", "uid", "organization")
    search_fields = ("label", "uid")
    list_filter = ("organization",)


class SignerAdmin(admin.ModelAdmin):
    """Admin interface for Signer model"""

    list_display = ("uid", "first_name", "last_name", "organization", "active")
    search_fields = ("uid", "first_name", "last_name")
    list_filter = ("active", "organization")
