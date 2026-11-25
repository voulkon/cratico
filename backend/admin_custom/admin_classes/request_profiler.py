"""Admin integration for persisted request-profiler runs."""

from django.contrib import admin
from django.utils import timezone

from core.models.request_profile_run import RequestProfileRun


class RequestProfileRunAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "label",
        "status",
        "target_count",
        "total_wall_ms",
        "total_db_ms",
        "user",
    )
    list_filter = ("status",)
    search_fields = ("label", "task_id")
    list_display_links = ("created_at", "label")
    ordering = ("-created_at",)
    actions = ("revoke_selected",)
    readonly_fields = (
        "id",
        "task_id",
        "user",
        "label",
        "status",
        "targets",
        "options",
        "result",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    )

    def has_add_permission(self, request):
        return False

    def revoke_selected(self, request, queryset):
        from diavgeia_project.celery import app as celery_app

        running = queryset.exclude(
            status__in=[
                RequestProfileRun.Status.SUCCESS,
                RequestProfileRun.Status.FAILURE,
                RequestProfileRun.Status.REVOKED,
            ]
        )
        count = 0
        for run in running:
            try:
                celery_app.control.revoke(run.task_id, terminate=True, signal="SIGKILL")
            except Exception:  # noqa: BLE001 - DB status is the source of truth
                pass
            run.status = RequestProfileRun.Status.REVOKED
            run.finished_at = timezone.now()
            run.save(update_fields=["status", "finished_at"])
            count += 1
        self.message_user(request, f"Revoked {count} run(s).")

    revoke_selected.short_description = "Revoke selected running profiles"
