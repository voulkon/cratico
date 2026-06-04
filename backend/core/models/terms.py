from django.db import models


class LegalDocument(models.Model):
    """
    Stores legal page content (Terms, Privacy, About, etc.) as individual
    markdown documents. Each document is identified by a unique (type, language)
    pair. Admins create and edit these freely from the admin page.

    The ``type`` field acts as the URL slug (e.g. 'tos', 'privacy', 'about')
    and the ``title`` field is the human-readable label shown in the footer.
    """

    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("el", "Greek"),
    ]

    type = models.SlugField(
        max_length=50,
        default="",
        help_text="URL-safe identifier, e.g. 'tos', 'privacy', 'about'",
    )

    title = models.CharField(
        max_length=100,
        default="",
        help_text="Display name shown in the footer, e.g. 'Terms of Service'",
    )

    language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        default="en",
    )

    content = models.TextField(help_text="Full legal page content in Markdown format")

    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        "users.CustomUser",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Legal Document"
        verbose_name_plural = "Legal Documents"
        unique_together = ("type", "language")

    def __str__(self):
        return f"{self.title} ({self.get_language_display()})"

    @classmethod
    def get_or_create_default(cls, type, language="en"):
        """Get or create a default legal document for the given type and language."""
        try:
            return cls.objects.get(type=type, language=language)
        except cls.DoesNotExist:
            from core.utils.default_legal_content import get_default_legal_content

            return cls.objects.create(
                type=type,
                title=get_default_legal_content(type, "title", language),
                language=language,
                content=get_default_legal_content(type, "content", language),
            )
