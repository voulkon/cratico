"""
Read-only admin for counterpart-recovery history.

Operators need to answer "what did recovery do, and why?" without shell access.
The live relationship is the source of truth; these rows are the audit trail
(status, old/new AFM, method, confidence, OCR provider, evidence, AI cost).
"""

from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html


class CounterpartRecoveryAttemptAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "decision_link",
        "status_colored",
        "original_afm",
        "chosen_afm",
        "method",
        "confidence",
        "ocr_provider",
    )
    list_filter = ("status", "method", "ocr_provider")
    search_fields = (
        "decision__ada",
        "decision__subject",
        "original_afm",
        "chosen_afm",
        "span_text",
    )
    date_hierarchy = "created_at"
    ordering = ("-created_at",)
    list_select_related = ("decision",)

    readonly_fields = (
        "decision",
        "extraction",
        "method",
        "status",
        "provider",
        "model",
        "candidate_afms",
        "chosen_afm",
        "confidence",
        "original_relationship",
        "original_afm",
        "original_entity_id",
        "original_entity_name",
        "original_role",
        "original_parent_key_path",
        "original_source_field_name",
        "original_raw_context",
        "previous_confidence",
        "new_relationship",
        "span_start",
        "span_end",
        "span_text",
        "evidence",
        "ocr_provider",
        "ocr_confidence",
        "cost_usd",
        "input_tokens",
        "output_tokens",
        "error_message",
        "created_at",
        "completed_at",
    )

    fieldsets = (
        (
            "Attempt",
            {
                "fields": (
                    "decision",
                    "extraction",
                    "status",
                    "method",
                    "confidence",
                    "created_at",
                    "completed_at",
                )
            },
        ),
        (
            "Counterpart",
            {
                "fields": (
                    "original_afm",
                    "original_entity_id",
                    "original_entity_name",
                    "original_role",
                    "original_parent_key_path",
                    "original_source_field_name",
                    "previous_confidence",
                    "chosen_afm",
                    "candidate_afms",
                )
            },
        ),
        (
            "Evidence",
            {
                "fields": (
                    "span_start",
                    "span_end",
                    "span_text",
                    "evidence",
                    "ocr_provider",
                    "ocr_confidence",
                )
            },
        ),
        (
            "AI",
            {
                "fields": (
                    "provider",
                    "model",
                    "cost_usd",
                    "input_tokens",
                    "output_tokens",
                    "error_message",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Rows",
            {
                "fields": (
                    "original_relationship",
                    "new_relationship",
                    "original_raw_context",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Decision")
    def decision_link(self, obj):
        url = reverse("admin:core_decision_change", args=[obj.decision_id])
        return format_html('<a href="{}">{}</a>', url, obj.decision.ada)

    @admin.display(description="Status")
    def status_colored(self, obj):
        colors = {
            "APPLIED": "#198754",
            "NEEDS_REVIEW": "#b8860b",
            "NO_CANDIDATE": "#6c757d",
            "REJECTED": "#dc3545",
            "FAILED": "#dc3545",
        }
        return format_html(
            '<strong style="color:{}">{}</strong>',
            colors.get(obj.status, "inherit"),
            obj.status,
        )

    def has_add_permission(self, request):
        return False

    def has_view_permission(self, request, obj=None):
        return bool(request.user and request.user.is_active and request.user.is_staff)

    def has_change_permission(self, request, obj=None):
        # Read-only audit trail: allow viewing the change form, never editing.
        return False
