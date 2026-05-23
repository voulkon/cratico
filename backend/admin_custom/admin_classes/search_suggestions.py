"""Admin interface for Search Suggestions"""

from core.models import SearchSuggestion
from django.contrib import admin


@admin.register(SearchSuggestion)
class SearchSuggestionAdmin(admin.ModelAdmin):
    """Admin interface for Search Suggestions"""

    list_display = (
        "order",
        "suggestion_type",
        "entity_display_name",
        "entity_id",
        "is_active",
        "click_count",
        "last_clicked_at",
        "updated_at",
    )

    list_filter = ("suggestion_type", "is_active", "created_at", "updated_at")

    search_fields = ("entity_id", "description")

    ordering = ("order", "-click_count")

    readonly_fields = ("click_count", "last_clicked_at", "created_at", "updated_at")

    fieldsets = (
        ("Entity Information", {"fields": ("suggestion_type", "entity_id")}),
        ("Display Settings", {"fields": ("order", "is_active", "description")}),
        (
            "Analytics",
            {"fields": ("click_count", "last_clicked_at"), "classes": ("collapse",)},
        ),
        ("System", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["activate_suggestions", "deactivate_suggestions", "clear_click_counts"]

    def entity_display_name(self, obj):
        """Show the actual entity name"""
        return obj.get_entity_display_name()

    entity_display_name.short_description = "Entity Name"

    def activate_suggestions(self, request, queryset):
        """Activate selected suggestions"""
        count = queryset.update(is_active=True)
        self.message_user(request, f"{count} suggestion(s) activated.")

    activate_suggestions.short_description = "Activate selected suggestions"

    def deactivate_suggestions(self, request, queryset):
        """Deactivate selected suggestions"""
        count = queryset.update(is_active=False)
        self.message_user(request, f"{count} suggestion(s) deactivated.")

    deactivate_suggestions.short_description = "Deactivate selected suggestions"

    def clear_click_counts(self, request, queryset):
        """Reset click counts to zero"""
        count = queryset.update(click_count=0, last_clicked_at=None)
        self.message_user(request, f"Click counts reset for {count} suggestion(s).")

    clear_click_counts.short_description = "Clear click counts"

    class Media:
        css = {"all": ("admin/css/search_suggestions.css",)}
