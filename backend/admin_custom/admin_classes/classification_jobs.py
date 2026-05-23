"""
Admin interface for managing classification batch jobs.

Provides:
- Dashboard with classification statistics
- Job creation with validation
- Progress monitoring
- Job control (pause/resume/cancel)
- Detailed logs view
"""

import uuid

from core.models.classification_job import (
    ClassificationJob,
    ClassificationJobLog,
    JobStatus,
)
from core.models.decision_classification import DecisionClassification
from core.models.decisions import Decision
from core.tasks.classification_tasks import (
    get_job_progress,
    resume_paused_classification_job,
    start_batch_classification_job,
)
from django import forms
from django.contrib import admin, messages
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import path, reverse
from django.utils.html import format_html


class ClassificationJobForm(forms.ModelForm):
    """Form for creating classification jobs"""

    class Meta:
        model = ClassificationJob
        fields = [
            "processing_mode",
            "start_date",
            "end_date",
            "batch_size",
            "max_decisions",
            "reclassify",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        processing_mode = cleaned_data.get("processing_mode")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        # Validate date range for date_range mode
        if processing_mode == "date_range":
            if not start_date and not end_date:
                raise forms.ValidationError(
                    "Date range mode requires at least a start or end date"
                )
            if start_date and end_date and start_date > end_date:
                raise forms.ValidationError("Start date must be before end date")

        return cleaned_data


class ClassificationJobLogInline(admin.TabularInline):
    """Inline display of job logs"""

    model = ClassificationJobLog
    extra = 0
    readonly_fields = (
        "timestamp",
        "level",
        "message",
        "batch_number",
        "decisions_in_batch",
    )

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(ClassificationJob)
class ClassificationJobAdmin(admin.ModelAdmin):
    """Admin interface for classification jobs"""

    form = ClassificationJobForm
    inlines = [ClassificationJobLogInline]

    list_display = [
        "job_id",
        "processing_mode",
        "status_colored",
        "progress_bar",
        "processed_count",
        "total_decisions",
        "direct_assignments_found",
        "error_count",
        "created_at",
        "actions_column",
    ]

    list_filter = ["status", "processing_mode", "created_at"]
    search_fields = ["job_id", "created_by__username"]
    readonly_fields = [
        "job_id",
        "created_by",
        "status",
        "celery_task_id",
        "total_decisions",
        "processed_count",
        "direct_assignments_found",
        "non_direct_assignments",
        "created_count",
        "updated_count",
        "error_count",
        "started_at",
        "completed_at",
        "estimated_completion",
        "duration_display",
        "rate_display",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            "Job Configuration",
            {
                "fields": (
                    "job_id",
                    "created_by",
                    "processing_mode",
                    "start_date",
                    "end_date",
                    "batch_size",
                    "max_decisions",
                    "reclassify",
                )
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "celery_task_id",
                    "started_at",
                    "completed_at",
                    "estimated_completion",
                )
            },
        ),
        (
            "Progress",
            {
                "fields": (
                    "total_decisions",
                    "processed_count",
                    "direct_assignments_found",
                    "non_direct_assignments",
                    "created_count",
                    "updated_count",
                    "error_count",
                    "duration_display",
                    "rate_display",
                )
            },
        ),
        ("Error Information", {"fields": ("last_error",), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related("created_by")

    def status_colored(self, obj):
        """Color-coded status display"""
        colors = {
            JobStatus.PENDING.value: "gray",
            JobStatus.RUNNING.value: "blue",
            JobStatus.PAUSED.value: "orange",
            JobStatus.COMPLETED.value: "green",
            JobStatus.FAILED.value: "red",
            JobStatus.CANCELLED.value: "gray",
        }
        color = colors.get(obj.status, "black")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_colored.short_description = "Status"
    status_colored.admin_order_field = "status"

    def progress_bar(self, obj):
        """Visual progress bar"""
        percentage = obj.progress_percentage
        color = "green" if percentage == 100 else "blue"
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 20px; border-radius: 3px;"></div>'
            "</div>"
            '<span style="font-size: 11px;">{}%</span>',
            percentage,
            color,
            percentage,
        )

    progress_bar.short_description = "Progress"

    def duration_display(self, obj):
        """Human-readable duration"""
        seconds = obj.duration_seconds
        if seconds == 0:
            return "Not started"

        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)

        if hours > 0:
            return f"{hours}h {minutes}m {secs}s"
        elif minutes > 0:
            return f"{minutes}m {secs}s"
        else:
            return f"{secs}s"

    duration_display.short_description = "Duration"

    def rate_display(self, obj):
        """Processing rate"""
        rate = obj.decisions_per_second
        if rate == 0:
            return "-"
        return f"{rate:.1f} decisions/sec"

    rate_display.short_description = "Rate"

    def actions_column(self, obj):
        """Action buttons based on job status"""
        buttons = []

        if obj.status == JobStatus.RUNNING.value:
            pause_url = reverse("admin:classification_job_pause", args=[obj.job_id])
            buttons.append(
                f'<a href="{pause_url}" class="button" style="background-color: orange;">Pause</a>'
            )

        if obj.status == JobStatus.PAUSED.value:
            resume_url = reverse("admin:classification_job_resume", args=[obj.job_id])
            buttons.append(
                f'<a href="{resume_url}" class="button" style="background-color: green;">Resume</a>'
            )

        if obj.status in [
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
        ]:
            cancel_url = reverse("admin:classification_job_cancel", args=[obj.job_id])
            buttons.append(
                f'<a href="{cancel_url}" class="button" style="background-color: red;">Cancel</a>'
            )

        if obj.status == JobStatus.COMPLETED.value:
            view_url = reverse("admin:classification_job_detail", args=[obj.job_id])
            buttons.append(f'<a href="{view_url}" class="button">View Details</a>')

        return format_html(" ".join(buttons))

    actions_column.short_description = "Actions"

    def save_model(self, request, obj, form, change):
        """Create job and queue task"""
        if not change:  # New job
            obj.job_id = str(uuid.uuid4())
            obj.created_by = request.user
            obj.save()

            # Queue the task
            task = start_batch_classification_job.delay(job_id=obj.job_id)
            obj.celery_task_id = task.id
            obj.save(update_fields=["celery_task_id"])

            messages.success(
                request,
                f"Classification job {obj.job_id} created and queued for processing",
            )
        else:
            super().save_model(request, obj, form, change)

    def get_urls(self):
        """Custom URLs for job actions"""
        urls = super().get_urls()
        custom_urls = [
            path(
                "<str:job_id>/pause/",
                self.admin_site.admin_view(self.pause_job),
                name="classification_job_pause",
            ),
            path(
                "<str:job_id>/resume/",
                self.admin_site.admin_view(self.resume_job),
                name="classification_job_resume",
            ),
            path(
                "<str:job_id>/cancel/",
                self.admin_site.admin_view(self.cancel_job),
                name="classification_job_cancel",
            ),
            path(
                "<str:job_id>/progress/",
                self.admin_site.admin_view(self.job_progress),
                name="classification_job_progress",
            ),
            path(
                "<str:job_id>/detail/",
                self.admin_site.admin_view(self.job_detail),
                name="classification_job_detail",
            ),
            path(
                "dashboard/",
                self.admin_site.admin_view(self.dashboard),
                name="classification_dashboard",
            ),
        ]
        return custom_urls + urls

    def pause_job(self, request, job_id):
        """Pause a running job"""
        job = get_object_or_404(ClassificationJob, job_id=job_id)

        if job.status == JobStatus.RUNNING.value:
            job.pause()
            messages.success(request, f"Job {job_id} paused")
        else:
            messages.warning(request, f"Job {job_id} is not running")

        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/admin/"))

    def resume_job(self, request, job_id):
        """Resume a paused job"""
        job = get_object_or_404(ClassificationJob, job_id=job_id)

        if job.status == JobStatus.PAUSED.value:
            resume_paused_classification_job.delay(job_id=job_id)
            messages.success(request, f"Job {job_id} resumed")
        else:
            messages.warning(request, f"Job {job_id} is not paused")

        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/admin/"))

    def cancel_job(self, request, job_id):
        """Cancel a job"""
        job = get_object_or_404(ClassificationJob, job_id=job_id)

        if job.status in [
            JobStatus.PENDING.value,
            JobStatus.RUNNING.value,
            JobStatus.PAUSED.value,
        ]:
            job.cancel()
            messages.success(request, f"Job {job_id} cancelled")
        else:
            messages.warning(request, f"Job {job_id} cannot be cancelled")

        return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/admin/"))

    def job_progress(self, request, job_id):
        """API endpoint for progress updates"""
        progress = get_job_progress(job_id)
        return JsonResponse(progress)

    def job_detail(self, request, job_id):
        """Detailed view of completed job"""
        job = get_object_or_404(ClassificationJob, job_id=job_id)

        # Get recent logs
        logs = job.logs.all()[:100]

        context = {
            **self.admin_site.each_context(request),
            "job": job,
            "logs": logs,
            "title": f"Classification Job {job_id}",
        }

        return render(request, "admin/classification_job_detail.html", context)

    def dashboard(self, request):
        """Classification statistics dashboard"""
        # Overall statistics
        total_decisions = Decision.objects.count()
        classified_count = DecisionClassification.objects.count()
        unclassified_count = total_decisions - classified_count

        direct_assignments = DecisionClassification.objects.filter(
            is_direct_assignment=True
        ).count()

        # Recent jobs
        recent_jobs = ClassificationJob.objects.all()[:10]

        # Active jobs
        active_jobs = ClassificationJob.objects.filter(
            status__in=[JobStatus.PENDING.value, JobStatus.RUNNING.value]
        )

        context = {
            **self.admin_site.each_context(request),
            "total_decisions": total_decisions,
            "classified_count": classified_count,
            "unclassified_count": unclassified_count,
            "direct_assignments": direct_assignments,
            "classification_rate": (
                round((classified_count / total_decisions * 100), 2)
                if total_decisions > 0
                else 0
            ),
            "direct_assignment_rate": (
                round((direct_assignments / classified_count * 100), 2)
                if classified_count > 0
                else 0
            ),
            "recent_jobs": recent_jobs,
            "active_jobs": active_jobs,
            "title": "Classification Dashboard",
        }

        return render(request, "admin/classification_dashboard.html", context)

    def changelist_view(self, request, extra_context=None):
        """Add dashboard link and active jobs to changelist"""
        extra_context = extra_context or {}
        extra_context["dashboard_url"] = reverse("admin:classification_dashboard")

        # Show active jobs in the changelist
        extra_context["active_jobs"] = ClassificationJob.objects.filter(
            status__in=[
                JobStatus.PENDING.value,
                JobStatus.RUNNING.value,
                JobStatus.PAUSED.value,
            ]
        ).order_by("-created_at")

        return super().changelist_view(request, extra_context)
