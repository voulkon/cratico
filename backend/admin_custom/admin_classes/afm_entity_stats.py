"""
Admin interface for AFMEntityStats - simple aggregated entity statistics.

Displays raw totals in a clean, sortable list view.
"""

from core.models.afm_entity_stats import AFMEntityStats
from core.tasks.afm_entity_stats_tasks import recompute_all_entity_stats
from django.contrib import admin, messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html


@admin.register(AFMEntityStats)
class AFMEntityStatsAdmin(admin.ModelAdmin):
    """Read-only admin displaying raw aggregated stats per AFM entity."""

    change_list_template = "admin/afm_entity_stats_changelist.html"

    list_display = [
        "entity_link",
        "entity_type_badge",
        "decisions_badge",
        "total_amount_display",
        "avg_amount_display",
        "max_amount_display",
        "orgs_display",
        "counterparts_display",
        "direct_assignment_display",
        "computed_at",
    ]
    list_filter = [
        "entity__entity_type",
    ]
    search_fields = ["entity__afm", "entity__name"]
    readonly_fields = [
        "entity",
        "total_decisions",
        "distinct_roles",
        "total_amount",
        "average_amount_per_decision",
        "max_single_amount",
        "distinct_organizations",
        "distinct_counterpart_entities",
        "direct_assignment_count",
        "direct_assignment_percentage",
        "computed_at",
    ]

    # Default ordering: highest total amount first
    ordering = ["-total_amount"]

    # ------------------------------------------------------------------
    # List display helpers
    # ------------------------------------------------------------------

    def entity_link(self, obj):
        from django.urls import reverse

        admin_url = reverse("admin:core_afmentity_change", args=[obj.entity.pk])
        return format_html(
            '<a href="{}" target="_blank"><strong>{}</strong></a>'
            "<br/><small style='color:#666;'>{}</small>",
            admin_url,
            obj.entity.afm,
            (obj.entity.name or "No name")[:60],
        )

    entity_link.short_description = "AFM Entity"

    def entity_type_badge(self, obj):
        colors = {
            "company": "#1976d2",
            "person": "#7b1fa2",
            "organization": "#00796b",
            "unknown": "#757575",
        }
        color = colors.get(obj.entity.entity_type, "#757575")
        return format_html(
            '<span style="background:{};color:#fff;padding:2px 8px;'
            'border-radius:3px;font-size:11px;font-weight:bold;">{}</span>',
            color,
            obj.entity.get_entity_type_display(),
        )

    entity_type_badge.short_description = "Type"

    def decisions_badge(self, obj):
        return format_html(
            '<span style="font-size:14px;font-weight:bold;">{}</span>',
            f"{obj.total_decisions:,}",
        )

    decisions_badge.short_description = "Decisions"
    decisions_badge.admin_order_field = "total_decisions"

    def total_amount_display(self, obj):
        formatted = f"{float(obj.total_amount):,.0f}"
        if obj.total_amount >= 1_000_000:
            return format_html(
                '<span style="font-weight:bold;color:#d32f2f;">€{}</span>',
                formatted,
            )
        if obj.total_amount >= 100_000:
            return format_html(
                '<span style="font-weight:bold;color:#f57c00;">€{}</span>',
                formatted,
            )
        return format_html("€{}", formatted)

    total_amount_display.short_description = "Total Amount"
    total_amount_display.admin_order_field = "total_amount"

    def avg_amount_display(self, obj):
        return format_html("€{}", f"{float(obj.average_amount_per_decision):,.0f}")

    avg_amount_display.short_description = "Avg / Decision"
    avg_amount_display.admin_order_field = "average_amount_per_decision"

    def max_amount_display(self, obj):
        return format_html("€{}", f"{float(obj.max_single_amount):,.0f}")

    max_amount_display.short_description = "Max Single"
    max_amount_display.admin_order_field = "max_single_amount"

    def orgs_display(self, obj):
        return format_html(
            '<span style="font-size:14px;">{}</span>',
            f"{obj.distinct_organizations:,}",
        )

    orgs_display.short_description = "Orgs"
    orgs_display.admin_order_field = "distinct_organizations"

    def counterparts_display(self, obj):
        return format_html(
            '<span style="font-size:14px;">{}</span>',
            f"{obj.distinct_counterpart_entities:,}",
        )

    counterparts_display.short_description = "Counterparts"
    counterparts_display.admin_order_field = "distinct_counterpart_entities"

    def direct_assignment_display(self, obj):
        if obj.direct_assignment_percentage > 50:
            color = "#d32f2f"
        elif obj.direct_assignment_percentage > 20:
            color = "#f57c00"
        else:
            color = "#388e3c"

        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span> '
            '<small style="color:#999;">({}%)</small>',
            color,
            f"{obj.direct_assignment_count:,}",
            f"{obj.direct_assignment_percentage:.0f}",
        )

    direct_assignment_display.short_description = "Direct Assignments"
    direct_assignment_display.admin_order_field = "direct_assignment_count"

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ------------------------------------------------------------------
    # Custom actions & URLs
    # ------------------------------------------------------------------

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "recompute/",
                self.admin_site.admin_view(self.recompute_view),
                name="afm_entity_stats_recompute",
            ),
            path(
                "api/",
                self.admin_site.admin_view(self.stats_api),
                name="afm_entity_stats_api",
            ),
        ]
        return custom_urls + urls

    def recompute_view(self, request):
        """Dispatch a background Celery task to recompute all entity stats."""
        if request.method == "POST":
            try:
                result = recompute_all_entity_stats.delay()
                messages.success(
                    request,
                    f"Stats recomputation queued! "
                    f"Task ID: {result.id}. "
                    "Check the Celery worker logs for progress.",
                )
            except Exception as e:
                messages.error(
                    request,
                    f"Failed to queue recomputation task: {e}",
                )

        return redirect("admin:core_afmentitystats_changelist")

    def stats_api(self, request):
        """Quick JSON summary for AJAX."""
        try:
            from django.db.models import Sum

            agg = AFMEntityStats.objects.aggregate(
                total=Sum("total_decisions"),
                total_amt=Sum("total_amount"),
            )
            return JsonResponse(
                {
                    "total_entities_with_stats": AFMEntityStats.objects.count(),
                    "sum_decisions": agg["total"] or 0,
                    "sum_amount": str(agg["total_amt"] or "0.00"),
                }
            )
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)
