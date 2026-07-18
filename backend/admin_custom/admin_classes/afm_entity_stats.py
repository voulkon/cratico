"""
Admin interface for AFMEntityStats - simple aggregated entity statistics.

Displays raw totals in a clean, sortable list view.
"""

from core.models.afm_entity_stats import AFMEntityStats
from core.models.entities import EntityType
from core.models.types import ActType
from core.tasks.afm_entity_stats_tasks import recompute_all_entity_stats
from django.contrib import admin, messages
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html


class EntityTypeListFilter(admin.SimpleListFilter):
    """Custom list filter for entity type with a clean label."""

    title = "Entity Type"
    parameter_name = "entity_type"

    def lookups(self, request, model_admin):
        return EntityType.choices

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(entity__entity_type=self.value())
        return queryset


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
        "direct_assignment_30k_38k_display",
        "payment_30k_38k_display",
        "computed_at",
    ]
    list_filter = [
        EntityTypeListFilter,
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
        "direct_assignment_30k_38k",
        "payment_30k_38k",
        "computed_at",
    ]

    # Default ordering: highest total amount first
    ordering = ["-total_amount"]

    # ------------------------------------------------------------------
    # List display helpers
    # ------------------------------------------------------------------

    def entity_link(self, obj):
        return format_html(
            '<a href="/entity/afm/{}/" target="_blank"><strong>{}</strong></a>'
            "<br/><small style='color:#666;'>{}</small>",
            obj.entity.afm,
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

    def direct_assignment_30k_38k_display(self, obj):
        if obj.direct_assignment_30k_38k >= 10:
            color = "#d32f2f"
        elif obj.direct_assignment_30k_38k >= 3:
            color = "#f57c00"
        else:
            color = "#757575"

        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            color,
            f"{obj.direct_assignment_30k_38k:,}",
        )

    direct_assignment_30k_38k_display.short_description = "DA €30k-€38k"
    direct_assignment_30k_38k_display.admin_order_field = "direct_assignment_30k_38k"

    def payment_30k_38k_display(self, obj):
        if obj.payment_30k_38k >= 10:
            color = "#d32f2f"
        elif obj.payment_30k_38k >= 3:
            color = "#f57c00"
        else:
            color = "#757575"

        return format_html(
            '<span style="color:{};font-weight:bold;">{}</span>',
            color,
            f"{obj.payment_30k_38k:,}",
        )

    payment_30k_38k_display.short_description = "Pay €30k-€38k"
    payment_30k_38k_display.admin_order_field = "payment_30k_38k"

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    # ------------------------------------------------------------------
    # Default filter: start with "Company" selected
    # ------------------------------------------------------------------

    def changelist_view(self, request, extra_context=None):
        if extra_context is None:
            extra_context = {}
        # Load act types for the amount-filter dropdown in the template.
        extra_context.setdefault(
            "act_types",
            ActType.objects.filter(allowed_in_decisions=True).order_by("uid"),
        )
        if "entity_type" not in request.GET:
            # Only default to Company on the very first visit in this session,
            # so the user can click "All" to undo the filter without being redirected back.
            if not request.session.get("afm_entity_stats_visited"):
                request.session["afm_entity_stats_visited"] = True
                q = request.GET.copy()
                q["entity_type"] = "company"
                return redirect(f"{request.path}?{q.urlencode()}")
        return super().changelist_view(request, extra_context)

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
        """Dispatch a background Celery task to recompute all entity stats.

        Reads decision_type_uid from POST body (set by the template dropdown).
        When provided, only amounts & counterpart entities are filtered;
        decision counts, roles, orgs, and direct-assignment stats remain global.
        """
        if request.method == "POST":
            try:
                decision_type_uid = request.POST.get("decision_type_uid") or None
                result = recompute_all_entity_stats.delay(
                    decision_type_uid=decision_type_uid,
                )
                uid_suffix = f" (amounts from {decision_type_uid})" if decision_type_uid else ""
                messages.success(
                    request,
                    f"Stats recomputation queued{uid_suffix}! "
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
