"""Admin for Diavgeia feedback-reporting jobs and per-decision reports."""

from django.contrib import admin


class DiavgeiaFeedbackJobAdmin(admin.ModelAdmin):
    """Read-only admin for feedback jobs (history view)."""

    list_display = (
        "job_id", "status", "total_candidates", "processed_count",
        "reported", "errors", "dry_run", "created_by", "created_at",
    )
    list_filter = ("status", "dry_run", "created_at")
    search_fields = ("job_id",)
    readonly_fields = [
        "job_id", "created_by", "reporter_email", "feedback_errors",
        "limit", "dry_run", "start_date", "end_date",
        "status", "celery_task_id", "total_candidates", "processed_count",
        "reported", "already_reported", "skipped", "errors",
        "started_at", "completed_at", "last_error", "created_at", "updated_at",
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Allow viewing but not editing — jobs are driven by tasks.
        return request.method == "GET" or super().has_change_permission(request, obj)


class DiavgeiaFeedbackJobResultAdmin(admin.ModelAdmin):
    """Read-only admin for per-decision feedback results."""

    list_display = ("job", "decision", "status", "reference", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("decision__ada", "reference")
    readonly_fields = [
        "job", "decision", "status", "reason", "reference", "response",
        "created_at",
    ]

    def has_add_permission(self, request):
        return False


class DiavgeiaFeedbackReportAdmin(admin.ModelAdmin):
    """Admin for per-decision feedback reports (one row per reported decision)."""

    list_display = (
        "decision", "reported", "reported_at", "reference", "created_at",
    )
    list_filter = ("reported", "reported_at", "created_at")
    search_fields = ("decision__ada", "decision__subject", "reference")
    readonly_fields = [
        "decision", "reported", "reported_at", "reference", "response",
        "reporter_email", "feedback_errors", "created_at", "updated_at",
    ]
    raw_id_fields = ("decision",)

    def has_add_permission(self, request):
        return False
