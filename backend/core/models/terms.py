from django.db import models


class LegalDocument(models.Model):
    """
    Stores the full legal page content (Terms, Privacy, Cookies, etc.) as a single
    markdown document per language. Admins edit this freely from the admin page.
    """

    LANGUAGE_CHOICES = [
        ("en", "English"),
        ("el", "Greek"),
    ]

    language = models.CharField(
        max_length=5,
        choices=LANGUAGE_CHOICES,
        unique=True,
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

    def __str__(self):
        return f"Legal Document ({self.get_language_display()})"

    @classmethod
    def get_or_create_default(cls, language="en"):
        try:
            return cls.objects.get(language=language)
        except cls.DoesNotExist:
            from core.utils.default_legal_content import get_default_legal_page

            return cls.objects.create(
                language=language,
                content=get_default_legal_page(language),
            )
