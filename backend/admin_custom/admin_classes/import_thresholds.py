"""
Admin interface for Import Threshold configuration.
"""

from datetime import date, timedelta

from core.models.import_thresholds import ImportThreshold
from django.contrib import admin, messages
from django.shortcuts import redirect, render
from django.urls import path
from django.utils.html import format_html


class ImportThresholdAdmin(admin.ModelAdmin):
    """
    Admin interface for configuring decision count thresholds.

    These thresholds are used by the import validation system to determine
    if historical imports were complete. Adjust based on observed patterns
    from the coverage explorer.
    """

    list_display = (
        "enabled",
        "weekday_threshold",
        "saturday_threshold",
        "sunday_threshold",
        "last_updated",
        "action_buttons",
    )

    list_editable = ("enabled",)
    list_display_links = (
        "weekday_threshold",
    )  # Make weekday_threshold the clickable link

    fieldsets = (
        (
            "System Control",
            {
                "fields": ("enabled",),
                "description": (
                    "[STOP] Toggle to enable/disable automatic import validation.<br><br>"
                    "<strong>When ENABLED:</strong> Periodic task runs daily (if configured via Celery Beat) "
                    "to check last 7 days and dispatch re-imports for incomplete days.<br>"
                    "<strong>When DISABLED:</strong> Periodic validation stops. Manual action buttons below still work.<br><br>"
                    "[SYS]️ <strong>Setup required:</strong> Configure Celery Beat periodic task for automatic operation. "
                    "See <code>docs/import-validation-setup.md</code> for instructions."
                ),
            },
        ),
        (
            "Threshold Configuration",
            {
                "fields": (
                    "weekday_threshold",
                    "saturday_threshold",
                    "sunday_threshold",
                ),
                "description": (
                    "Set minimum expected decision counts by day-of-week. "
                    "Use the Coverage Explorer at /admin/decisions/coverage/?entity_type=all "
                    "to analyze actual patterns before adjusting these values."
                ),
            },
        ),
        (
            "Notes & Metadata",
            {
                "fields": ("notes", "last_updated"),
                "description": "Document your threshold adjustments and data range analyzed.",
            },
        ),
    )

    readonly_fields = ("last_updated",)

    def action_buttons(self, obj):
        """Add action buttons to trigger validation"""
        return format_html(
            '<a class="button" href="{}">[SCAN] Analyze (60 days)</a> '
            '<a class="button" href="{}">[TEST] Test (Dry Run)</a> '
            '<a class="button" href="{}">▶️ Run Validation</a>',
            f"analyze/",
            f"test-validation/",
            f"run-validation/",
        )

    action_buttons.short_description = "Actions"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "analyze/",
                self.admin_site.admin_view(self.analyze_view),
                name="importthreshold_analyze",
            ),
            path(
                "test-validation/",
                self.admin_site.admin_view(self.test_validation_view),
                name="importthreshold_test",
            ),
            path(
                "run-validation/",
                self.admin_site.admin_view(self.run_validation_view),
                name="importthreshold_run",
            ),
        ]
        return custom_urls + urls

    def analyze_view(self, request):
        """Run analysis command and show results"""
        from io import StringIO

        from django.core.management import call_command

        output = StringIO()
        try:
            call_command("analyze_decision_counts", "--days", "60", stdout=output)
            messages.success(request, "Analysis complete! See results below.")
            return render(
                request,
                "admin/import_threshold_output.html",
                {
                    "title": "Decision Count Analysis",
                    "output": output.getvalue(),
                },
            )
        except Exception as e:
            messages.error(request, f"Analysis failed: {str(e)}")
            return redirect("..")

    def test_validation_view(self, request):
        """Run validation in dry-run mode"""
        from io import StringIO

        from django.core.management import call_command

        # Get parameters from query string (for quick tests) or use defaults
        days_back = int(request.GET.get("days", 60))

        end_date = date.today()
        start_date = end_date - timedelta(days=days_back)

        output = StringIO()
        try:
            call_command(
                "validate_imports",
                "--start-date",
                start_date.isoformat(),
                "--end-date",
                end_date.isoformat(),
                "--dry-run",
                stdout=output,
            )
            messages.success(request, "Dry run complete! No tasks were dispatched.")
            return render(
                request,
                "admin/import_threshold_output.html",
                {
                    "title": f"Validation Test (Dry Run - Last {days_back} Days)",
                    "output": output.getvalue(),
                },
            )
        except Exception as e:
            messages.error(request, f"Test failed: {str(e)}")
            return redirect("..")

    def run_validation_view(self, request):
        """Run actual validation and dispatch re-import tasks"""
        from io import StringIO

        from django.core.management import call_command

        # Confirm action with form
        if request.method != "POST":
            end_date = date.today()
            start_date = end_date - timedelta(days=60)
            return render(
                request,
                "admin/import_threshold_confirm.html",
                {
                    "title": "Run Import Validation",
                    "today": date.today(),
                },
            )

        # Get parameters from form
        use_custom_dates = request.POST.get("use_custom_dates") == "on"

        if use_custom_dates:
            end_date_str = request.POST.get("end_date")
            days_back = int(request.POST.get("days_back", 60))
            end_date = (
                date.fromisoformat(end_date_str) if end_date_str else date.today()
            )
            start_date = end_date - timedelta(days=days_back)
        else:
            days_back = int(request.POST.get("days_back", 60))
            end_date = date.today()
            start_date = end_date - timedelta(days=days_back)

        max_reimports = request.POST.get("max_reimports")
        if max_reimports:
            max_reimports = int(max_reimports)

        output = StringIO()
        try:
            # Build kwargs for call_command (using underscore versions of argument names)
            cmd_kwargs = {
                "start_date": start_date,  # Pass as date object, not string
                "end_date": end_date,  # Pass as date object, not string
                "stdout": output,
            }

            if max_reimports:
                cmd_kwargs["max_reimports"] = max_reimports

            call_command("validate_imports", **cmd_kwargs)

            msg = f"Validation complete! Check ImportJobs for progress."
            if max_reimports:
                msg += f" (Limited to {max_reimports} re-imports)"
            messages.success(request, msg)

            return render(
                request,
                "admin/import_threshold_output.html",
                {
                    "title": f"Validation Results (Last {days_back} Days)",
                    "output": output.getvalue(),
                },
            )
        except Exception as e:
            messages.error(request, f"Validation failed: {str(e)}")
            return redirect("..")

    def has_add_permission(self, request):
        """Only allow one instance (singleton pattern)"""
        return not ImportThreshold.objects.exists()

    def has_delete_permission(self, request, obj=None):
        """Don't allow deletion of the singleton instance"""
        return False
