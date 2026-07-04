"""
Admin interface for Legal Documents.

Markdown-based editor for Terms of Service, Privacy Policy, etc.
Each document is identified by a unique (type, language) pair.
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
    """Admin interface for legal documents.  One entry per (type, language)."""

    form = LegalDocumentForm

    list_display = [
        "type",
        "title",
        "language",
        "updated_at",
        "updated_by",
    ]

    list_filter = [
        "language",
        "type",
    ]

    search_fields = [
        "type",
        "title",
    ]

    readonly_fields = [
        "updated_at",
    ]

    fieldsets = (
        ("Document Identity", {"fields": ("type", "title", "language")}),
        (
            "Content (Markdown)",
            {
                "fields": ("content",),
                "description": (
                    "Edit the legal page content using Markdown. "
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
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
