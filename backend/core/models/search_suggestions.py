"""
Search Suggestions Model

Provides configurable default search suggestions for the homepage search.
Allows admins to configure trending/popular entities through the admin interface.
"""

from django.core.cache import cache
from django.db import models
from django.utils import timezone


class SearchSuggestion(models.Model):
    """
    Model for storing default search suggestions.

    Admins can configure popular organizations, signers, or other entities
    to show as suggestions when users click on the search without typing.
    """

    SUGGESTION_TYPES = [
        ("organization", "Organization"),
        ("signer", "Signer"),
        ("unit", "Unit"),
        ("company", "Company"),
        ("company_person", "Company Person"),
        ("afmentity", "AFM Entity"),
    ]

    # Type and reference
    suggestion_type = models.CharField(
        max_length=50, choices=SUGGESTION_TYPES, help_text="Type of entity to suggest"
    )

    entity_id = models.CharField(
        max_length=255,
        help_text="UID of the entity (organization.uid, signer.uid, etc.)",
    )

    # Ordering and visibility
    order = models.IntegerField(
        default=0, help_text="Display order (lower numbers appear first)"
    )

    is_active = models.BooleanField(
        default=True, help_text="Whether this suggestion is currently active"
    )

    # Metadata
    description = models.TextField(
        blank=True, help_text="Optional description or reason for featuring this entity"
    )

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Analytics
    click_count = models.IntegerField(
        default=0, help_text="Number of times this suggestion was clicked"
    )

    last_clicked_at = models.DateTimeField(
        null=True, blank=True, help_text="Last time this suggestion was clicked"
    )

    class Meta:
        db_table = "core_search_suggestion"
        verbose_name = "Search Suggestion"
        verbose_name_plural = "Search Suggestions"
        ordering = ["order", "-click_count"]
        indexes = [
            models.Index(fields=["suggestion_type", "is_active", "order"]),
            models.Index(fields=["is_active", "order"]),
        ]

    def __str__(self):
        return f"{self.get_suggestion_type_display()}: {self.get_entity_display_name()}"

    def get_entity_display_name(self):
        """Get the actual name of the referenced entity"""
        try:
            if self.suggestion_type == "organization":
                from core.models.organizations import Organization

                return Organization.objects.get(uid=self.entity_id).label
            elif self.suggestion_type == "signer":
                from core.models.organizations import Signer

                signer = Signer.objects.get(uid=self.entity_id)
                return f"{signer.first_name} {signer.last_name}"
            elif self.suggestion_type == "unit":
                from core.models.organizations import Unit

                return Unit.objects.get(uid=self.entity_id).label
            elif self.suggestion_type == "company":
                from core.models.companies import Company

                company = Company.objects.get(ar_gemi=self.entity_id)
                return company.co_name_el or "No name"
            elif self.suggestion_type == "company_person":
                from core.models.companies import CompanyPerson

                person = CompanyPerson.objects.get(id=self.entity_id)
                return person.person_name or person.business_name or "No name"
            elif self.suggestion_type == "afmentity":
                from core.models.entities import AFMEntity

                entity = AFMEntity.objects.get(id=self.entity_id)
                return entity.name or f"AFM: {entity.afm}"
        except Exception:
            return f"{self.suggestion_type} #{self.entity_id} (not found)"
        return self.entity_id

    @classmethod
    def get_active_suggestions(cls, limit=10):
        """Get active suggestions in display order."""
        cache_key = f"search_suggestions_active_{limit}"
        suggestions = cache.get(cache_key)

        if suggestions is None:
            suggestions = list(
                cls.objects.filter(is_active=True).order_by("order", "-click_count")[
                    :limit
                ]
            )
            # Cache for 5 minutes
            cache.set(cache_key, suggestions, 300)

        return suggestions

    @classmethod
    def clear_cache(cls):
        """Clear all cached suggestions."""
        # You might want to clear multiple cache keys if you have different limits
        for limit in [5, 10, 15, 20]:
            cache.delete(f"search_suggestions_active_{limit}")

    def save(self, *args, **kwargs):
        """Override save to clear cache when suggestions are updated."""
        super().save(*args, **kwargs)
        self.__class__.clear_cache()

    def delete(self, *args, **kwargs):
        """Override delete to clear cache when suggestions are removed."""
        super().delete(*args, **kwargs)
        self.__class__.clear_cache()

    def record_click(self):
        """Record a click on this suggestion."""
        self.click_count += 1
        self.last_clicked_at = timezone.now()
        self.save(update_fields=["click_count", "last_clicked_at"])
