"""
Admin interface for Legal Documents.

Simple markdown-based editor for Terms of Service, Privacy Policy, etc.
"""

from core.models import LegalDocument
from django import forms
from django.contrib import admin


class LegalDocumentForm(forms.ModelForm):
    """Form with large textarea for markdown editing."""

    class Meta:
        model = LegalDocument
        fields = "__all__"
        widgets = {
            "content": forms.Textarea(
                attrs={
                    "rows": 40,
                    "cols": 120,
                    "style": "font-family: monospace; font-size: 13px; line-height: 1.5;",
                    "placeholder": "Enter content in Markdown format...",
                }
            ),
        }


@admin.register(LegalDocument)
class LegalDocumentAdmin(admin.ModelAdmin):
    """Simple admin interface for legal documents."""

    form = LegalDocumentForm

    list_display = [
        "language",
        "updated_at",
        "updated_by",
    ]

    list_filter = [
        "language",
    ]

    readonly_fields = [
        "updated_at",
    ]

    fieldsets = (
        ("Document", {"fields": ("language",)}),
        (
            "Content (Markdown)",
            {
                "fields": ("content",),
                "description": (
                    "Edit the full legal page content using Markdown. "
                    "Use headings (##) to separate sections like Terms, Privacy, Cookies. "
                    '<a href="https://www.markdownguide.org/basic-syntax/" target="_blank">Markdown Guide</a>'
                ),
            },
        ),
        (
            "Metadata",
            {"fields": ("updated_at", "updated_by"), "classes": ("collapse",)},
        ),
    )

    def save_model(self, request, obj, form, change):
        """Track who updated the document."""
        if not obj.pk:  # New document
            obj.updated_by = request.user
        else:  # Updated document
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)
