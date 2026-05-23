"""
Admin interface for AFM Scoring and Fetch Queue Management

Provides:
1. Configuration management for scoring criteria
2. View/search scored entities
3. Cockpit dashboard for queue monitoring and control
"""

from core.models.afm_scoring import AFMEntityScore, AFMScoringConfig
from core.models.afm_scoring_job import AFMScoringJob
from core.models.entities import AFMEntity
from core.services.afm_fetch_queue_service import AFMFetchQueueService
from core.tasks.afm_scoring_tasks import start_afm_scoring_job
from django import forms
from django.contrib import admin, messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.html import format_html
from loguru import logger


class AFMEntityAdmin(admin.ModelAdmin):
    """Read-only admin for viewing AFM entities."""

    list_display = [
        "afm",
        "name",
        "entity_type",
        "total_appearances",
        "gemi_status_badge",
        "first_seen",
        "last_seen",
    ]
    list_filter = [
        "entity_type",
        "gemi_lookup_success",
    ]
    search_fields = ["afm", "name"]
    readonly_fields = [
        "afm",
        "entity_type",
        "name",
        "first_seen",
        "last_seen",
        "total_appearances",
        "gemi_lookup_attempted",
        "gemi_lookup_success",
        "gemi_companies_count",
        "last_error",
        "error_count",
    ]

    fieldsets = (
        ("Basic Information", {"fields": ("afm", "name", "entity_type")}),
        (
            "Activity Metadata",
            {"fields": ("total_appearances", "first_seen", "last_seen")},
        ),
        (
            "GEMI Lookup Status",
            {
                "fields": (
                    "gemi_lookup_attempted",
                    "gemi_lookup_success",
                    "gemi_companies_count",
                    "last_error",
                    "error_count",
                )
            },
        ),
    )

    def gemi_status_badge(self, obj):
        if obj.gemi_lookup_success:
            return format_html(
                '<span style="color: green;">[OK] Success ({} companies)</span>',
                obj.gemi_companies_count,
            )
        elif obj.gemi_lookup_attempted:
            return format_html(
                '<span style="color: orange;">[WARN] Failed ({} errors)</span>',
                obj.error_count,
            )
        return format_html('<span style="color: gray;">Not attempted</span>')

    gemi_status_badge.short_description = "GEMI Status"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class AFMScoringConfigForm(forms.ModelForm):
    """Custom form with weight validation."""

    class Meta:
        model = AFMScoringConfig
        exclude = ["created_by"]  # Set automatically in admin, avoid circular import
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned_data = super().clean()

        # Validate weights sum to 1.0 (now 5 weights)
        freq_weight = cleaned_data.get("frequency_weight", 0)
        amount_weight = cleaned_data.get("amount_weight", 0)
        org_weight = cleaned_data.get("organization_weight", 0)
        direct_count_weight = cleaned_data.get("direct_assignment_count_weight", 0)
        direct_pct_weight = cleaned_data.get("direct_assignment_percentage_weight", 0)

        total = (
            freq_weight
            + amount_weight
            + org_weight
            + direct_count_weight
            + direct_pct_weight
        )
        if not (0.99 <= total <= 1.01):
            raise forms.ValidationError(
                f"Weights must sum to 1.0, got {total:.3f}. "
                f"Frequency={freq_weight}, Amount={amount_weight}, Organization={org_weight}, "
                f"DirectCount={direct_count_weight}, DirectPct={direct_pct_weight}"
            )

        return cleaned_data


@admin.register(AFMScoringConfig)
class AFMScoringConfigAdmin(admin.ModelAdmin):
    """Admin for scoring configuration."""

    form = AFMScoringConfigForm

    change_list_template = "admin/afm_scoring_config_changelist.html"

    list_display = [
        "name",
        "is_active_badge",
        "weight_summary",
        "threshold_summary",
        "actions_column",
    ]
    list_filter = ["is_active", "enable_recency_boost"]
    search_fields = ["name", "notes"]

    fieldsets = (
        ("Basic Info", {"fields": ("name", "is_active", "notes")}),
        (
            "Normalization Strategy",
            {
                "fields": ("normalization_strategy",),
                "description": "How to normalize features before weighting. ROBUST is recommended for data with outliers.",
            },
        ),
        (
            "Scoring Weights (must sum to 1.0)",
            {
                "fields": (
                    ("frequency_weight", "frequency_impact"),
                    ("amount_weight", "amount_impact"),
                    ("organization_weight", "organization_impact"),
                    (
                        "direct_assignment_count_weight",
                        "direct_assignment_count_impact",
                    ),
                    (
                        "direct_assignment_percentage_weight",
                        "direct_assignment_percentage_impact",
                    ),
                ),
                "description": "Weights determine contribution to total score. Impact determines if higher values are better (POSITIVE) or worse (NEGATIVE).",
            },
        ),
        (
            "Filtering Thresholds",
            {
                "fields": (
                    "min_appearances",
                    "min_total_amount",
                    "min_unique_organizations",
                    "min_direct_assignments",
                ),
                "description": "Minimum requirements for an entity to be eligible for fetching.",
            },
        ),
        (
            "Retry Configuration",
            {
                "fields": (
                    "retry_failed_after_days",
                    "never_retry_after_failures",
                ),
            },
        ),
        (
            "Recency Boost (Optional)",
            {
                "fields": (
                    "enable_recency_boost",
                    "recency_days_threshold",
                    "recency_boost_multiplier",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    def is_active_badge(self, obj):
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-weight: bold;">[OK] ACTIVE</span>'
            )
        return format_html('<span style="color: gray;">Inactive</span>')

    is_active_badge.short_description = "Status"

    def weight_summary(self, obj):
        return format_html(
            '<small style="line-height: 1.6;">'
            "F:{} A:{} O:{}<br/>"
            "DC:{} DP:{}"
            "</small>",
            f"{obj.frequency_weight:.0%}",
            f"{obj.amount_weight:.0%}",
            f"{obj.organization_weight:.0%}",
            f"{obj.direct_assignment_count_weight:.0%}",
            f"{obj.direct_assignment_percentage_weight:.0%}",
        )

    weight_summary.short_description = "Weights (F/A/O/DC/DP)"

    def threshold_summary(self, obj):
        return format_html(
            '<small style="line-height: 1.6;">'
            "≥{} apps | ≥€{}<br/>"
            "≥{} orgs | ≥{} direct"
            "</small>",
            obj.min_appearances,
            f"{obj.min_total_amount:,.0f}",
            obj.min_unique_organizations,
            obj.min_direct_assignments,
        )

    threshold_summary.short_description = "Thresholds"

    def actions_column(self, obj):
        if obj.is_active:
            return format_html(
                '<a class="button" href="{}">Run Scoring Now</a>',
                reverse("admin:afm_cockpit") + f"?config_id={obj.id}&action=score",
            )
        return "-"

    actions_column.short_description = "Actions"


@admin.register(AFMEntityScore)
class AFMEntityScoreAdmin(admin.ModelAdmin):
    """Admin for viewing scored entities."""

    change_list_template = "admin/afm_entity_score_changelist.html"

    list_display = [
        "afm_link",
        "priority_badge",
        "total_score_bar",
        "score_breakdown_display",
        "eligibility_badge",
        "metrics_summary",
        "gemi_status",
        "scored_at",
    ]
    list_filter = [
        "is_eligible",
        "entity__gemi_lookup_success",
        "entity__entity_type",
        "config_used",
    ]
    search_fields = ["entity__afm", "entity__name"]
    readonly_fields = [
        "entity",
        "total_score",
        "frequency_score",
        "amount_score",
        "organization_score",
        "direct_assignment_count_score",
        "direct_assignment_percentage_score",
        "total_appearances",
        "total_amount",
        "unique_organizations",
        "direct_assignment_count",
        "direct_assignment_percentage",
        "is_eligible",
        "fetch_priority",
        "config_used",
        "normalization_stats",
        "scored_at",
    ]

    # Default ordering: highest priority first
    ordering = ["fetch_priority"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def afm_link(self, obj):
        admin_url = reverse("admin:core_afmentity_change", args=[obj.entity.pk])
        return format_html(
            '<a href="{}" target="_blank"><strong>{}</strong></a><br/><small>{}</small>',
            admin_url,
            obj.entity.afm,
            obj.entity.name[:50] if obj.entity.name else "No name",
        )

    afm_link.short_description = "AFM Entity"

    def priority_badge(self, obj):
        if not obj.is_eligible:
            return format_html('<span style="color: gray;">-</span>')

        # Color code by priority
        if obj.fetch_priority <= 10:
            color = "#d32f2f"  # Red for top 10
        elif obj.fetch_priority <= 50:
            color = "#f57c00"  # Orange for top 50
        elif obj.fetch_priority <= 100:
            color = "#fbc02d"  # Yellow for top 100
        else:
            color = "#757575"  # Gray for others

        return format_html(
            '<span style="background: {}; color: white; padding: 3px 8px; border-radius: 3px; font-weight: bold;">#{}</span>',
            color,
            obj.fetch_priority,
        )

    priority_badge.short_description = "Priority"

    def total_score_bar(self, obj):
        # Visual progress bar for score
        width = min(obj.total_score, 100)

        # Color gradient
        if width >= 75:
            color = "#4caf50"  # Green
        elif width >= 50:
            color = "#ff9800"  # Orange
        else:
            color = "#9e9e9e"  # Gray

        return format_html(
            '<div style="width: 100px; background: #e0e0e0; border-radius: 3px; overflow: hidden;">'
            '<div style="width: {}%; background: {}; color: white; text-align: center; font-size: 11px; font-weight: bold; padding: 2px 0;">'
            "{}"
            "</div></div>",
            width,
            color,
            f"{obj.total_score:.1f}",
        )

    total_score_bar.short_description = "Score"

    def eligibility_badge(self, obj):
        if obj.is_eligible:
            return format_html('<span style="color: green;">[OK] Eligible</span>')
        return format_html('<span style="color: #999;">[FAIL] Ineligible</span>')

    eligibility_badge.short_description = "Eligible"

    def score_breakdown_display(self, obj):
        """Show normalized scores for each component."""
        return format_html(
            '<small style="line-height: 1.4; font-family: monospace;">'
            "F:{} A:{} O:{}<br/>"
            "DC:{} DP:{}"
            "</small>",
            f"{obj.frequency_score:.2f}",
            f"{obj.amount_score:.2f}",
            f"{obj.organization_score:.2f}",
            f"{obj.direct_assignment_count_score:.2f}",
            f"{obj.direct_assignment_percentage_score:.2f}",
        )

    score_breakdown_display.short_description = "Component Scores"

    def metrics_summary(self, obj):
        return format_html(
            '<small style="line-height: 1.4;">'
            "{} apps | €{}<br/>"
            "{} orgs | {} direct ({}%)"
            "</small>",
            obj.total_appearances,
            f"{obj.total_amount:,.0f}",
            obj.unique_organizations,
            obj.direct_assignment_count,
            f"{obj.direct_assignment_percentage:.0f}",
        )

    metrics_summary.short_description = "Raw Metrics"

    def gemi_status(self, obj):
        entity = obj.entity

        if entity.gemi_lookup_success:
            return format_html(
                '<span style="color: green;">[OK] Fetched</span><br/>'
                "<small>{} companies</small>",
                entity.gemi_companies_count,
            )
        elif entity.gemi_lookup_attempted:
            return format_html(
                '<span style="color: orange;">[WARN] Failed</span><br/>'
                "<small>{} attempts</small>",
                entity.error_count,
            )
        else:
            return format_html('<span style="color: gray;">Not attempted</span>')

    gemi_status.short_description = "GEMI Status"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "cockpit/",
                self.admin_site.admin_view(self.cockpit_view),
                name="afm_cockpit",
            ),
            path(
                "cockpit/score/",
                self.admin_site.admin_view(self.run_scoring_view),
                name="afm_run_scoring",
            ),
            path(
                "cockpit/populate/",
                self.admin_site.admin_view(self.populate_queue_view),
                name="afm_populate_queue",
            ),
            path(
                "cockpit/process/",
                self.admin_site.admin_view(self.process_batch_view),
                name="afm_process_batch",
            ),
            path(
                "cockpit/add-to-queue/",
                self.admin_site.admin_view(self.add_to_queue_view),
                name="afm_add_to_queue",
            ),
            path(
                "cockpit/bulk-add-to-queue/",
                self.admin_site.admin_view(self.bulk_add_to_queue_view),
                name="afm_bulk_add_to_queue",
            ),
            path(
                "cockpit/remove-from-queue/",
                self.admin_site.admin_view(self.remove_from_queue_view),
                name="afm_remove_from_queue",
            ),
            path(
                "cockpit/boost-priority/",
                self.admin_site.admin_view(self.boost_priority_view),
                name="afm_boost_priority",
            ),
            path(
                "cockpit/mark-excluded/",
                self.admin_site.admin_view(self.mark_excluded_view),
                name="afm_mark_excluded",
            ),
            path(
                "cockpit/bulk-mark-excluded/",
                self.admin_site.admin_view(self.bulk_mark_excluded_view),
                name="afm_bulk_mark_excluded",
            ),
            path(
                "cockpit/recover-stuck/",
                self.admin_site.admin_view(self.recover_stuck_view),
                name="afm_recover_stuck",
            ),
            path(
                "cockpit/status/",
                self.admin_site.admin_view(self.queue_status_api),
                name="afm_queue_status_api",
            ),
        ]
        return custom_urls + urls

    def cockpit_view(self, request):
        """Main cockpit dashboard."""

        # Get active config
        config = AFMScoringConfig.get_active()

        # Get queue service
        queue_service = AFMFetchQueueService()
        queue_status = queue_service.get_queue_status()

        # Get active scoring job (if any)
        active_job = (
            AFMScoringJob.objects.filter(status__in=["pending", "running", "paused"])
            .select_related("config", "created_by")
            .first()
        )

        # Get recent completed jobs
        recent_jobs = (
            AFMScoringJob.objects.filter(status="completed")
            .select_related("config", "created_by")
            .order_by("-completed_at")[:5]
        )

        # Get top entities (from database - all eligible)
        top_unfetched = (
            AFMEntityScore.objects.filter(
                is_eligible=True, entity__gemi_lookup_success=False
            )
            .select_related("entity")
            .order_by("-total_score")[:20]
        )  # Highest scores first

        # Get current queue contents (from Redis)
        queue_contents = []
        if queue_status.get("top_pending"):
            afms_in_queue = [item["afm"] for item in queue_status["top_pending"]]
            queue_scores = AFMEntityScore.objects.filter(
                entity__afm__in=afms_in_queue
            ).select_related("entity")

            # Create a dict for quick lookup
            score_dict = {score.entity.afm: score for score in queue_scores}

            # Maintain Redis queue order
            for item in queue_status["top_pending"]:
                if item["afm"] in score_dict:
                    score_obj = score_dict[item["afm"]]
                    score_obj.redis_score = item["score"]  # Add Redis score for display
                    queue_contents.append(score_obj)

        # Get currently processing AFMs (from ACTIVE set in Redis)
        active_processing = []
        if queue_status.get("active", 0) > 0:
            active_afms = queue_service.redis_client.smembers(queue_service.ACTIVE_KEY)
            active_afm_list = [
                afm.decode("utf-8") if isinstance(afm, bytes) else afm
                for afm in active_afms
            ]

            if active_afm_list:
                active_scores = AFMEntityScore.objects.filter(
                    entity__afm__in=active_afm_list
                ).select_related("entity")
                active_processing = list(active_scores)

        # Get recently fetched
        recently_fetched = AFMEntity.objects.filter(
            gemi_lookup_success=True, gemi_lookup_attempted__isnull=False
        ).order_by("-gemi_lookup_attempted")[:10]

        # Get overall statistics
        total_entities = AFMEntity.objects.count()
        total_scored = AFMEntityScore.objects.count()
        eligible_count = AFMEntityScore.objects.filter(is_eligible=True).count()
        fetched_count = AFMEntity.objects.filter(gemi_lookup_success=True).count()

        context = {
            **self.admin_site.each_context(request),
            "title": "AFM Fetch Queue Management",
            "config": config,
            "queue_status": queue_status,
            "active_job": active_job,
            "recent_jobs": recent_jobs,
            "top_unfetched": top_unfetched,
            "queue_contents": queue_contents,
            "active_processing": active_processing,
            "recently_fetched": recently_fetched,
            "total_entities": total_entities,
            "total_scored": total_scored,
            "eligible_count": eligible_count,
            "fetched_count": fetched_count,
            "fetch_percentage": (
                round(fetched_count / eligible_count * 100, 1)
                if eligible_count > 0
                else 0
            ),
        }

        return render(request, "admin/afm_cockpit.html", context)

    def run_scoring_view(self, request):
        """Create and start a scoring job."""
        if request.method == "POST":
            try:
                # Get config
                config_id = request.POST.get("config_id")
                if config_id:
                    config = AFMScoringConfig.objects.get(id=config_id)
                else:
                    config = AFMScoringConfig.get_active()

                if not config:
                    messages.error(request, "No active scoring configuration found")
                    return redirect("admin:afm_cockpit")

                # Check if there's already an active job
                active_job = AFMScoringJob.objects.filter(
                    status__in=["pending", "running", "paused"]
                ).first()

                if active_job:
                    messages.warning(
                        request,
                        f"A scoring job is already {active_job.get_status_display()}. "
                        f"Wait for it to complete or cancel it first.",
                    )
                    return redirect("admin:afm_cockpit")

                # Create new job
                import uuid

                job = AFMScoringJob.objects.create(
                    job_id=str(uuid.uuid4()),
                    created_by=request.user,
                    config=config,
                    batch_size=1000,
                    exclude_already_fetched=False,
                )

                # Start the job
                task = start_afm_scoring_job.delay(job_id=job.job_id)
                job.celery_task_id = task.id
                job.save(update_fields=["celery_task_id"])

                messages.success(
                    request,
                    f"Scoring job created and started! "
                    f"Job ID: {job.job_id[:8]}... | Task ID: {task.id}",
                )

            except Exception as e:
                messages.error(request, f"Failed to create scoring job: {str(e)}")

        return redirect("admin:afm_cockpit")

    def populate_queue_view(self, request):
        """Populate Redis queue from scores."""
        if request.method == "POST":
            try:
                limit = request.POST.get("limit")
                limit = int(limit) if limit else None
                force = request.POST.get("force_refresh") == "on"

                queue_service = AFMFetchQueueService()
                stats = queue_service.populate_queue_from_scores(
                    limit=limit,
                    force_refresh=force,
                    auto_trigger=False,  # Don't auto-trigger on bulk populate - user can manually start
                )

                messages.success(
                    request,
                    f"Queue populated! Added: {stats['added']}, "
                    f"Total pending: {stats['total_pending']}. "
                    f"Click 'Start Processing' to begin fetching.",
                )

            except Exception as e:
                messages.error(request, f"Queue population failed: {str(e)}")

        return redirect("admin:afm_cockpit")

    def process_batch_view(self, request):
        """Dispatch Celery task to process the queue."""
        if request.method == "POST":
            try:
                from core.tasks.tasks_entities import process_afm_fetch_queue

                # Get optional limit (None = process entire queue)
                max_items = request.POST.get("max_items")
                max_items = int(max_items) if max_items else None

                # Check queue status
                queue_service = AFMFetchQueueService()
                pending = queue_service.get_pending_count()

                if pending == 0:
                    messages.info(request, "Queue is empty - nothing to process")
                    return redirect("admin:afm_cockpit")

                # Dispatch Celery task (non-blocking)
                task = process_afm_fetch_queue.delay(max_items=max_items)

                items_msg = f"{max_items} items" if max_items else "all items"
                messages.success(
                    request,
                    f"[OK] Queue processing started in background! Processing {items_msg} from {pending} pending. "
                    f"Task ID: {task.id[:8]}... (This will take time due to rate limiting)",
                )

            except Exception as e:
                messages.error(request, f"Failed to start queue processing: {str(e)}")

        return redirect("admin:afm_cockpit")

    def add_to_queue_view(self, request):
        """Add a single AFM to the queue (with optional priority jump)."""
        if request.method == "POST":
            try:
                afm = request.POST.get("afm")
                jump_queue = request.POST.get("jump_queue") == "on"

                if not afm:
                    messages.error(request, "AFM is required")
                    return redirect("admin:afm_cockpit")

                queue_service = AFMFetchQueueService()
                added = queue_service.add_single_afm(
                    afm=afm,
                    jump_queue=jump_queue,
                    auto_trigger=True,  # Auto-trigger for single AFM additions
                )

                if added:
                    if jump_queue:
                        messages.success(
                            request,
                            f"AFM {afm} added to queue with PRIORITY and processing started!",
                        )
                    else:
                        messages.success(
                            request, f"AFM {afm} added to queue and processing started!"
                        )
                else:
                    messages.warning(
                        request, f"AFM {afm} is already in queue or has been processed"
                    )

            except Exception as e:
                messages.error(request, f"Failed to add AFM: {str(e)}")

        return redirect("admin:afm_cockpit")

    def remove_from_queue_view(self, request):
        """Remove an AFM from the queue."""
        if request.method == "POST":
            try:
                afm = request.POST.get("afm")

                if not afm:
                    messages.error(request, "AFM is required")
                    return redirect("admin:afm_cockpit")

                queue_service = AFMFetchQueueService()
                removed = queue_service.redis_client.zrem(
                    queue_service.PENDING_KEY, afm
                )

                if removed:
                    messages.success(request, f"AFM {afm} removed from queue")
                else:
                    messages.warning(request, f"AFM {afm} was not in queue")

            except Exception as e:
                messages.error(request, f"Failed to remove AFM: {str(e)}")

        return redirect("admin:afm_cockpit")

    def boost_priority_view(self, request):
        """Boost an AFM's priority to process it sooner."""
        if request.method == "POST":
            try:
                afm = request.POST.get("afm")

                if not afm:
                    messages.error(request, "AFM is required")
                    return redirect("admin:afm_cockpit")

                queue_service = AFMFetchQueueService()

                # Get current score
                current_score = queue_service.redis_client.zscore(
                    queue_service.PENDING_KEY, afm
                )

                if current_score is None:
                    messages.warning(request, f"AFM {afm} is not in queue")
                else:
                    # Boost score significantly to move it to front
                    new_score = 999999.0
                    queue_service.redis_client.zadd(
                        queue_service.PENDING_KEY, {afm: new_score}
                    )
                    messages.success(
                        request,
                        f"AFM {afm} priority boosted! Moved to front of queue (score: {current_score:.1f} → {new_score:.0f})",
                    )

            except Exception as e:
                messages.error(request, f"Failed to boost priority: {str(e)}")

        return redirect("admin:afm_cockpit")

    def mark_excluded_view(self, request):
        """Mark an entity as manually excluded (fake/typo company)."""
        if request.method == "POST":
            try:
                afm = request.POST.get("afm")

                if not afm:
                    messages.error(request, "AFM is required")
                    return redirect("admin:afm_cockpit")

                # Get the entity
                from core.models.entities import AFMEntity

                entity = AFMEntity.objects.get(afm=afm)

                # Mark as "looked up and found nothing" (excluded)
                from django.utils import timezone

                entity.gemi_lookup_attempted = timezone.now()
                entity.gemi_lookup_success = (
                    True  # Pretend success but with 0 companies
                )
                entity.gemi_companies_count = 0
                entity.save(
                    update_fields=[
                        "gemi_lookup_attempted",
                        "gemi_lookup_success",
                        "gemi_companies_count",
                    ]
                )

                # Also remove from queue if present
                queue_service = AFMFetchQueueService()
                queue_service.redis_client.zrem(queue_service.PENDING_KEY, afm)

                messages.success(
                    request,
                    f"AFM {afm} marked as excluded (treated as fake/typo company). "
                    f"It will no longer appear in eligible entities.",
                )

            except AFMEntity.DoesNotExist:
                messages.error(request, f"AFM {afm} not found")
            except Exception as e:
                messages.error(request, f"Failed to mark as excluded: {str(e)}")

        return redirect("admin:afm_cockpit")

    def bulk_add_to_queue_view(self, request):
        """Bulk add multiple AFMs to the queue."""
        if request.method == "POST":
            try:
                afms = request.POST.getlist("afms")
                jump_queue = request.POST.get("jump_queue") == "on"

                if not afms:
                    messages.error(request, "No AFMs selected")
                    return redirect("admin:afm_cockpit")

                queue_service = AFMFetchQueueService()
                added_count = 0
                already_exists_count = 0

                # Add all AFMs WITHOUT auto-triggering on each one
                for afm in afms:
                    added = queue_service.add_single_afm(
                        afm=afm, jump_queue=jump_queue, auto_trigger=False
                    )
                    if added:
                        added_count += 1
                    else:
                        already_exists_count += 1

                # Trigger processing ONCE after all AFMs are added
                if added_count > 0:
                    from core.tasks.tasks_entities import process_afm_fetch_queue

                    task = process_afm_fetch_queue.delay()
                    logger.info(
                        f"Triggered queue processing for {added_count} AFMs, task: {task.id}"
                    )

                priority_msg = " with PRIORITY" if jump_queue else ""
                msg = f"Added {added_count} AFM(s) to queue{priority_msg}."
                if already_exists_count > 0:
                    msg += f" {already_exists_count} already in queue or processed."

                messages.success(request, msg)

            except Exception as e:
                messages.error(request, f"Failed to add AFMs: {str(e)}")

        return redirect("admin:afm_cockpit")

    def bulk_mark_excluded_view(self, request):
        """Bulk mark multiple entities as excluded."""
        if request.method == "POST":
            try:
                afms = request.POST.getlist("afms")

                if not afms:
                    messages.error(request, "No AFMs selected")
                    return redirect("admin:afm_cockpit")

                from core.models.entities import AFMEntity
                from django.utils import timezone

                # Update all selected entities
                updated_count = AFMEntity.objects.filter(afm__in=afms).update(
                    gemi_lookup_attempted=timezone.now(),
                    gemi_lookup_success=True,
                    gemi_companies_count=0,
                )

                # Remove from queue if present
                queue_service = AFMFetchQueueService()
                for afm in afms:
                    queue_service.redis_client.zrem(queue_service.PENDING_KEY, afm)

                messages.success(
                    request,
                    f"Marked {updated_count} AFM(s) as excluded. They will no longer appear in eligible entities.",
                )

            except Exception as e:
                messages.error(request, f"Failed to mark as excluded: {str(e)}")

        return redirect("admin:afm_cockpit")

    def recover_stuck_view(self, request):
        """Recover AFMs stuck in ACTIVE set."""
        if request.method == "POST":
            try:
                queue_service = AFMFetchQueueService()
                result = queue_service.recover_stuck_active()

                recovered_count = result.get("recovered", 0)

                if recovered_count > 0:
                    messages.success(
                        request,
                        f"Recovered {recovered_count} stuck AFM(s) from ACTIVE set and moved back to queue.",
                    )
                else:
                    messages.info(request, "No stuck items found in ACTIVE set.")

            except Exception as e:
                messages.error(request, f"Failed to recover stuck items: {str(e)}")

        return redirect("admin:afm_cockpit")

    def queue_status_api(self, request):
        """API endpoint for real-time queue status (AJAX)."""
        try:
            queue_service = AFMFetchQueueService()
            status = queue_service.get_queue_status()
            return JsonResponse(status)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@admin.register(AFMScoringJob)
class AFMScoringJobAdmin(admin.ModelAdmin):
    """Admin for managing AFM scoring jobs."""

    list_display = [
        "job_id_short",
        "status_badge",
        "config_name",
        "progress_bar",
        "stats_summary",
        "created_by",
        "created_at",
        "actions_column",
    ]

    list_filter = ["status", "config", "exclude_already_fetched"]
    search_fields = ["job_id", "created_by__username"]
    readonly_fields = [
        "job_id",
        "created_by",
        "config",
        "batch_size",
        "exclude_already_fetched",
        "celery_task_id",
        "total_entities",
        "processed_count",
        "scored_count",
        "eligible_count",
        "ineligible_count",
        "error_count",
        "started_at",
        "completed_at",
        "estimated_completion",
        "last_error",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        ("Job Info", {"fields": ("job_id", "created_by", "config", "status")}),
        ("Configuration", {"fields": ("batch_size", "exclude_already_fetched")}),
        (
            "Progress",
            {
                "fields": (
                    "total_entities",
                    "processed_count",
                    "scored_count",
                    "eligible_count",
                    "ineligible_count",
                    "error_count",
                )
            },
        ),
        (
            "Timing",
            {
                "fields": (
                    "started_at",
                    "completed_at",
                    "estimated_completion",
                )
            },
        ),
        (
            "Task Info",
            {
                "fields": ("celery_task_id", "last_error"),
                "classes": ("collapse",),
            },
        ),
    )

    def job_id_short(self, obj):
        return str(obj.job_id)[:8] + "..."

    job_id_short.short_description = "Job ID"

    def status_badge(self, obj):
        colors = {
            "pending": "#6c757d",
            "running": "#007bff",
            "paused": "#ffc107",
            "completed": "#28a745",
            "failed": "#dc3545",
            "cancelled": "#6c757d",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background: {}; color: white; padding: 3px 10px; border-radius: 3px; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"

    def config_name(self, obj):
        return obj.config.name if obj.config else "-"

    config_name.short_description = "Config"

    def progress_bar(self, obj):
        if obj.total_entities == 0:
            return "-"

        percentage = obj.progress_percentage
        return format_html(
            '<div style="width: 100px; background: #e0e0e0; border-radius: 3px; overflow: hidden;">'
            '<div style="width: {}%; background: var(--primary); color: white; text-align: center; font-size: 11px; font-weight: bold; padding: 2px 0;">'
            "{}%"
            "</div></div>",
            percentage,
            percentage,
        )

    progress_bar.short_description = "Progress"

    def stats_summary(self, obj):
        return format_html(
            "<small>Scored: {} | Eligible: {} | Errors: {}</small>",
            obj.scored_count,
            obj.eligible_count,
            obj.error_count,
        )

    stats_summary.short_description = "Stats"

    def actions_column(self, obj):
        actions = []

        if obj.status == "pending":
            actions.append(
                format_html(
                    '<a class="button" href="{}">Start</a>',
                    reverse("admin:core_afmscoringjob_start", args=[obj.pk]),
                )
            )

        if obj.status == "running":
            actions.append(
                format_html(
                    '<a class="button" href="{}">Pause</a>',
                    reverse("admin:core_afmscoringjob_pause", args=[obj.pk]),
                )
            )

        if obj.status == "paused":
            actions.append(
                format_html(
                    '<a class="button" href="{}">Resume</a>',
                    reverse("admin:core_afmscoringjob_resume", args=[obj.pk]),
                )
            )

        if obj.status in ["pending", "running", "paused"]:
            actions.append(
                format_html(
                    '<a class="button" href="{}" style="background: #dc3545;">Cancel</a>',
                    reverse("admin:core_afmscoringjob_cancel", args=[obj.pk]),
                )
            )

        return format_html(" ".join(actions)) if actions else "-"

    actions_column.short_description = "Actions"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/start/",
                self.admin_site.admin_view(self.start_job_view),
                name="core_afmscoringjob_start",
            ),
            path(
                "<path:object_id>/pause/",
                self.admin_site.admin_view(self.pause_job_view),
                name="core_afmscoringjob_pause",
            ),
            path(
                "<path:object_id>/resume/",
                self.admin_site.admin_view(self.resume_job_view),
                name="core_afmscoringjob_resume",
            ),
            path(
                "<path:object_id>/cancel/",
                self.admin_site.admin_view(self.cancel_job_view),
                name="core_afmscoringjob_cancel",
            ),
        ]
        return custom_urls + urls

    def start_job_view(self, request, object_id):
        """Start a pending job."""
        job = AFMScoringJob.objects.get(pk=object_id)

        if job.status != "pending":
            messages.error(request, f"Cannot start job in {job.status} state")
        else:
            task = start_afm_scoring_job.delay(job_id=job.job_id)
            job.celery_task_id = task.id
            job.save(update_fields=["celery_task_id"])
            messages.success(
                request, f"Job {job.job_id} started with task ID {task.id}"
            )

        return redirect("admin:core_afmscoringjob_changelist")

    def pause_job_view(self, request, object_id):
        """Pause a running job."""
        job = AFMScoringJob.objects.get(pk=object_id)
        job.pause()
        messages.success(request, f"Job {job.job_id} paused")
        return redirect("admin:core_afmscoringjob_changelist")

    def resume_job_view(self, request, object_id):
        """Resume a paused job."""
        job = AFMScoringJob.objects.get(pk=object_id)

        if job.status != "paused":
            messages.error(request, f"Cannot resume job in {job.status} state")
        else:
            from core.tasks.afm_scoring_tasks import resume_paused_scoring_job

            resume_paused_scoring_job.delay(job_id=job.job_id)
            messages.success(request, f"Job {job.job_id} resumed")

        return redirect("admin:core_afmscoringjob_changelist")

    def cancel_job_view(self, request, object_id):
        """Cancel a job."""
        job = AFMScoringJob.objects.get(pk=object_id)
        job.cancel()
        messages.success(request, f"Job {job.job_id} cancelled")
        return redirect("admin:core_afmscoringjob_changelist")

    def has_add_permission(self, request):
        return False  # Jobs should be created via management command or cockpit

    def has_change_permission(self, request, obj=None):
        return False  # Jobs are read-only once created
