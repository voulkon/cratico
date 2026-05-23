from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.html import format_html

from .models import AllowedUser, CustomUser, Subscription


@admin.register(CustomUser)
class CustomUserAdmin(UserAdmin):
    list_display = (
        "username",
        "email",
        "subscription",
        "usage_this_month",
        "is_staff",
        "is_active",
    )
    list_filter = ("subscription", "is_active", "is_staff")
    search_fields = ("username", "email")
    ordering = ("username",)

    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Personal info", {"fields": ("email", "first_name", "last_name")}),
        (
            "Subscription",
            {
                "fields": (
                    "subscription",
                    "subscription_expires",
                    "api_key",
                    "usage_this_month",
                )
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    readonly_fields = ("usage_this_month",)


@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "max_requests_per_day",
        "price",
        "can_access_premium_data",
        "can_queue_bulk_tasks",
    )


class DocumentExtractionAdmin(admin.ModelAdmin):
    list_display = (
        "decision_link",
        "extraction_status_colored",
        "extraction_provider",
        "page_count",
        "character_count",
        "is_scanned_document",
        "extraction_date",
        "processing_time",
    )

    list_filter = ("extraction_status", "extraction_provider", "is_scanned_document")
    search_fields = ("decision__ada", "decision__subject")
    date_hierarchy = "extraction_date"
    readonly_fields = (
        "search_vector",
        "created_at",
        "updated_at",
        "task_id",
        "processing_time_ms",
    )

    fieldsets = (
        ("Decision", {"fields": ("decision",)}),
        (
            "Extraction Status",
            {"fields": ("extraction_status", "extraction_provider", "extraction_date")},
        ),
        (
            "Document Info",
            {"fields": ("page_count", "character_count", "is_scanned_document")},
        ),
        ("Content", {"fields": ("raw_text",)}),
        (
            "Processing",
            {
                "fields": (
                    "error_message",
                    "retry_count",
                    "processing_time_ms",
                    "task_id",
                )
            },
        ),
        ("System", {"fields": ("created_at", "updated_at")}),
    )

    def decision_link(self, obj):
        from django.urls import reverse
        from django.utils.html import format_html

        url = reverse("admin:core_decision_change", args=[obj.decision.id])
        return format_html('<a href="{}">{}</a>', url, obj.decision.ada)

    decision_link.short_description = "Decision"

    def extraction_status_colored(self, obj):
        from django.utils.html import format_html

        status_colors = {
            "COMPLETED": "green",
            "FAILED": "red",
            "PROCESSING": "blue",
            "PENDING": "orange",
            "NEEDS_VISION": "purple",
        }
        color = status_colors.get(obj.extraction_status, "black")
        return format_html(
            '<span style="color: {};">{}</span>', color, obj.extraction_status
        )

    extraction_status_colored.short_description = "Status"

    def processing_time(self, obj):
        if obj.processing_time_ms:
            if obj.processing_time_ms < 1000:
                return f"{obj.processing_time_ms} ms"
            return f"{obj.processing_time_ms / 1000:.2f} sec"
        return "-"

    processing_time.short_description = "Processing Time"


@admin.register(AllowedUser)
class AllowedUserAdmin(admin.ModelAdmin):
    """Admin interface for managing allowed users in stealth mode"""

    list_display = (
        "status_icon",
        "email",
        "name",
        "clerk_user_id",
        "created_at",
        "created_by",
    )
    list_filter = ("is_active", "created_at")
    search_fields = ("email", "name", "clerk_user_id", "notes")
    ordering = ("-created_at",)
    date_hierarchy = "created_at"

    fieldsets = (
        ("User Information", {"fields": ("email", "name", "clerk_user_id")}),
        (
            "Access Control",
            {
                "fields": ("is_active",),
                "description": 'Uncheck "Is active" to temporarily revoke access without deleting the user.',
            },
        ),
        ("Notes", {"fields": ("notes",), "classes": ("collapse",)}),
        (
            "Metadata",
            {
                "fields": ("created_by", "created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = ("created_at", "updated_at", "created_by")

    def status_icon(self, obj):
        """Display a visual indicator of active/inactive status"""
        if obj.is_active:
            return format_html(
                '<span style="color: green; font-size: 16px;">[OK]</span>'
            )
        return format_html('<span style="color: red; font-size: 16px;">[FAIL]</span>')

    status_icon.short_description = "Status"

    def save_model(self, request, obj, form, change):
        """Automatically set created_by when creating a new allowed user"""
        if not change:  # Only on creation
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    actions = ["activate_users", "deactivate_users"]

    @admin.action(description="Activate selected users")
    def activate_users(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f"{updated} user(s) activated.")

    @admin.action(description="Deactivate selected users")
    def deactivate_users(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f"{updated} user(s) deactivated.")
