from django.contrib import admin
from django.contrib.auth.admin import UserAdmin


class CustomUserAdmin(UserAdmin):
    """Admin interface for CustomUser model"""

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


class SubscriptionAdmin(admin.ModelAdmin):
    """Admin interface for Subscription model"""

    list_display = (
        "name",
        "max_requests_per_day",
        "price",
        "can_access_premium_data",
        "can_queue_bulk_tasks",
    )
    list_filter = ("can_access_premium_data", "can_queue_bulk_tasks")
    search_fields = ("name",)
