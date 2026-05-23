"""
Admin classes for Notification models.
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from notifications.models import NotificationBatchDecision


class NotificationSubscriptionAdmin(admin.ModelAdmin):
    """Admin interface for NotificationSubscription model."""

    list_display = [
        "id",
        "user",
        "subscription_type_display",
        "target_display",
        "is_active",
        "created_at",
        "last_checked",
    ]

    list_filter = ["is_active", "created_at", "last_checked"]

    search_fields = [
        "user__username",
        "user__email",
        "organization__label",
        "organization__uid",
        "entity__afm",
        "entity__name",
        "person_name",
        "signer_name",
    ]

    readonly_fields = ["created_at", "subscription_type"]

    fieldsets = (
        ("User", {"fields": ("user",)}),
        (
            "Target (What to Watch)",
            {
                "description": "Select one target type (organization, entity, relationship, person, or signer)",
                "fields": (
                    "organization",
                    "entity",
                    "relationship_org",
                    "relationship_entity",
                    "person_name",
                    "signer_name",
                ),
            },
        ),
        (
            "Filters (Optional)",
            {
                "description": "Additional filters to narrow down matches",
                "fields": (
                    "keywords",
                    "keyword_match_operator",
                    "amount_min",
                    "amount_max",
                    "decision_types",
                ),
            },
        ),
        ("Status", {"fields": ("is_active", "created_at", "last_checked")}),
    )

    def subscription_type_display(self, obj):
        """Display subscription type with color coding."""
        colors = {
            "organization": "blue",
            "entity": "green",
            "relationship": "purple",
            "person": "orange",
            "signer": "red",
            "filter": "gray",
        }
        color = colors.get(obj.subscription_type, "black")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            (
                obj.get_subscription_type_display()
                if hasattr(obj, "get_subscription_type_display")
                else obj.subscription_type.title()
            ),
        )

    subscription_type_display.short_description = "Type"

    def target_display(self, obj):
        """Display the target of the subscription."""
        if obj.subscription_type == "organization":
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:core_organization_change", args=[obj.organization.uid]),
                obj.organization.label[:50] if obj.organization else "N/A",
            )
        elif obj.subscription_type == "entity":
            return format_html(
                '<a href="{}">{}</a>',
                reverse("admin:core_afmentity_change", args=[obj.entity.id]),
                f"{obj.entity.afm} - {obj.entity.name}"[:50] if obj.entity else "N/A",
            )
        elif obj.subscription_type == "relationship":
            return format_html(
                "{} ↔ {}",
                obj.relationship_org.label[:25] if obj.relationship_org else "N/A",
                obj.relationship_entity.afm if obj.relationship_entity else "N/A",
            )
        elif obj.subscription_type == "person":
            return obj.person_name
        elif obj.subscription_type == "signer":
            return obj.signer_name
        else:
            return "Filter only"

    target_display.short_description = "Target"


class NotificationAdmin(admin.ModelAdmin):
    """Admin interface for Notification model."""

    list_display = [
        "id",
        "user",
        "subscription_type",
        "decision_link",
        "match_reason",
        "is_read",
        "is_dismissed",
        "created_at",
    ]

    list_filter = ["match_reason", "is_read", "is_dismissed", "created_at"]

    search_fields = [
        "user__username",
        "user__email",
        "decision__ada",
        "decision__subject",
    ]

    readonly_fields = [
        "user",
        "subscription",
        "decision",
        "match_reason",
        "match_details",
        "created_at",
        "read_at",
    ]

    fieldsets = (
        ("User & Subscription", {"fields": ("user", "subscription")}),
        ("Decision", {"fields": ("decision", "match_reason", "match_details")}),
        ("Status", {"fields": ("is_read", "is_dismissed", "created_at", "read_at")}),
    )

    def subscription_type(self, obj):
        """Display subscription type."""
        return obj.subscription.subscription_type.title()

    subscription_type.short_description = "Subscription Type"

    def decision_link(self, obj):
        """Display decision with link."""
        return format_html(
            '<a href="{}">{}</a><br/><small>{}</small>',
            reverse("admin:core_decision_change", args=[obj.decision.id]),
            obj.decision.ada,
            obj.decision.subject[:50] if obj.decision.subject else "",
        )

    decision_link.short_description = "Decision"

    def has_add_permission(self, request):
        """Prevent manual creation of notifications in admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing notifications in admin (read-only)."""
        return False


class NotificationBatchDecisionInline(admin.TabularInline):
    """Inline admin for NotificationBatchDecision."""

    model = NotificationBatchDecision
    extra = 0
    can_delete = False
    readonly_fields = [
        "decision_link",
        "match_reason",
        "match_details",
        "is_viewed",
        "viewed_at",
        "added_at",
    ]
    fields = ["decision_link", "match_reason", "is_viewed", "added_at"]

    def decision_link(self, obj):
        """Display decision with link."""
        if obj.decision:
            return format_html(
                '<a href="{}" target="_blank">{}</a><br/><small>{}</small>',
                reverse("admin:core_decision_change", args=[obj.decision.id]),
                obj.decision.ada,
                obj.decision.subject[:50] if obj.decision.subject else "",
            )
        return "N/A"

    decision_link.short_description = "Decision"

    def has_add_permission(self, request, obj=None):
        """Prevent manual addition."""
        return False


class NotificationBatchAdmin(admin.ModelAdmin):
    """Admin interface for NotificationBatch model."""

    list_display = [
        "id",
        "user",
        "subscription_display",
        "match_count",
        "check_window_display",
        "is_read",
        "is_dismissed",
        "created_at",
    ]

    list_filter = ["is_read", "is_dismissed", "created_at"]

    search_fields = [
        "user__username",
        "user__email",
        "subscription__alias",
        "subscription__organization__label",
        "subscription__entity__afm",
    ]

    readonly_fields = [
        "user",
        "subscription",
        "check_window_start",
        "check_window_end",
        "match_count",
        "aggregate_stats_display",
        "created_at",
        "read_at",
        "dismissed_at",
    ]

    fieldsets = (
        ("User & Subscription", {"fields": ("user", "subscription")}),
        (
            "Check Window",
            {"fields": ("check_window_start", "check_window_end", "match_count")},
        ),
        ("Statistics", {"fields": ("aggregate_stats_display",)}),
        (
            "Status",
            {
                "fields": (
                    "is_read",
                    "is_dismissed",
                    "created_at",
                    "read_at",
                    "dismissed_at",
                )
            },
        ),
    )

    inlines = [NotificationBatchDecisionInline]

    def subscription_display(self, obj):
        """Display subscription with link."""
        if obj.subscription:
            return format_html(
                '<a href="{}">{}</a>',
                reverse(
                    "admin:notifications_notificationsubscription_change",
                    args=[obj.subscription.id],
                ),
                str(obj.subscription)[:50],
            )
        return "N/A"

    subscription_display.short_description = "Subscription"

    def check_window_display(self, obj):
        """Display check window as a date range."""
        return format_html(
            "<small>{}<br/>to<br/>{}</small>",
            (
                obj.check_window_start.strftime("%Y-%m-%d %H:%M")
                if obj.check_window_start
                else "N/A"
            ),
            (
                obj.check_window_end.strftime("%Y-%m-%d %H:%M")
                if obj.check_window_end
                else "N/A"
            ),
        )

    check_window_display.short_description = "Check Window"

    def aggregate_stats_display(self, obj):
        """Display aggregate statistics in a readable format."""
        if not obj.aggregate_stats:
            return "No statistics"

        stats_html = '<table style="border-collapse: collapse;">'
        for key, value in obj.aggregate_stats.items():
            stats_html += f'<tr><td style="padding: 2px 10px 2px 0;"><strong>{key}:</strong></td><td style="padding: 2px;">{value}</td></tr>'
        stats_html += "</table>"
        return format_html(stats_html)

    aggregate_stats_display.short_description = "Aggregate Statistics"

    def has_add_permission(self, request):
        """Prevent manual creation of batches in admin."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing batches in admin (read-only)."""
        return False


class NotificationBatchDecisionAdmin(admin.ModelAdmin):
    """Admin interface for NotificationBatchDecision model."""

    list_display = [
        "id",
        "batch_link",
        "decision_link",
        "match_reason",
        "is_viewed",
        "added_at",
    ]

    list_filter = ["match_reason", "is_viewed", "added_at"]

    search_fields = ["batch__id", "decision__ada", "decision__subject"]

    readonly_fields = [
        "batch",
        "decision",
        "match_reason",
        "match_details_display",
        "is_viewed",
        "viewed_at",
        "added_at",
    ]

    fieldsets = (
        ("Batch & Decision", {"fields": ("batch", "decision")}),
        ("Match Info", {"fields": ("match_reason", "match_details_display")}),
        ("Status", {"fields": ("is_viewed", "viewed_at", "added_at")}),
    )

    def batch_link(self, obj):
        """Display batch with link."""
        if obj.batch:
            return format_html(
                '<a href="{}">Batch #{}</a>',
                reverse(
                    "admin:notifications_notificationbatch_change", args=[obj.batch.id]
                ),
                obj.batch.id,
            )
        return "N/A"

    batch_link.short_description = "Batch"

    def decision_link(self, obj):
        """Display decision with link."""
        if obj.decision:
            return format_html(
                '<a href="{}" target="_blank">{}</a><br/><small>{}</small>',
                reverse("admin:core_decision_change", args=[obj.decision.id]),
                obj.decision.ada,
                obj.decision.subject[:50] if obj.decision.subject else "",
            )
        return "N/A"

    decision_link.short_description = "Decision"

    def match_details_display(self, obj):
        """Display match details in a readable format."""
        if not obj.match_details:
            return "No details"

        details_html = '<table style="border-collapse: collapse;">'
        for key, value in obj.match_details.items():
            # Truncate long values
            str_value = str(value)
            if len(str_value) > 100:
                str_value = str_value[:100] + "..."
            details_html += f'<tr><td style="padding: 2px 10px 2px 0;"><strong>{key}:</strong></td><td style="padding: 2px;">{str_value}</td></tr>'
        details_html += "</table>"
        return format_html(details_html)

    match_details_display.short_description = "Match Details"

    def has_add_permission(self, request):
        """Prevent manual creation."""
        return False

    def has_change_permission(self, request, obj=None):
        """Prevent editing (read-only)."""
        return False
