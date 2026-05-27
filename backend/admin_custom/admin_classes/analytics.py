import json

from core.models.decision_health import HealthStatus
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from core.tasks import (
    backfill_health_checks_for_import_job,
    retry_failed_decisions_for_import_job,
)
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
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
