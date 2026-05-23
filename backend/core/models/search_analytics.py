from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _


class SearchAnalytics(models.Model):
    """Track search queries and their effectiveness"""

    # Search query details
    query = models.CharField(_("Search Query"), max_length=500, db_index=True)
    normalized_query = models.CharField(
        _("Normalized Query"),
        max_length=500,
        db_index=True,
        help_text=_("Lowercased, trimmed query for grouping"),
    )

    # Search context
    search_types = models.JSONField(
        _("Search Types"),
        default=list,
        help_text=_("Types searched: ['metadata', 'content', 'summary']"),
    )
    entity_type = models.CharField(
        _("Entity Type"), max_length=50, null=True, blank=True, db_index=True
    )
    entity_id = models.CharField(
        _("Entity ID"), max_length=255, null=True, blank=True, db_index=True
    )

    # Search results
    results_count = models.IntegerField(_("Results Count"), default=0)
    response_time_ms = models.IntegerField(
        _("Response Time (ms)"), null=True, blank=True
    )

    # User interaction
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="search_queries",
    )
    user_clicked_result = models.BooleanField(_("User Clicked Result"), default=False)
    clicked_result_type = models.CharField(
        _("Clicked Result Type"), max_length=50, null=True, blank=True
    )  # 'decision', 'document', 'organization', etc.
    clicked_result_id = models.CharField(
        _("Clicked Result ID"), max_length=255, null=True, blank=True
    )
    click_position = models.IntegerField(
        _("Click Position"),
        null=True,
        blank=True,
        help_text=_("Position of clicked result (1-based)"),
    )

    # Session tracking
    session_key = models.CharField(
        _("Session Key"), max_length=40, null=True, blank=True, db_index=True
    )
    ip_address = models.GenericIPAddressField(_("IP Address"), null=True, blank=True)
    user_agent = models.TextField(_("User Agent"), null=True, blank=True)

    # Search filters applied
    filters_applied = models.JSONField(
        _("Filters Applied"),
        default=dict,
        help_text=_("Filters like date range, status, etc."),
    )

    # Timing
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = _("Search Analytics")
        verbose_name_plural = _("Search Analytics")
        indexes = [
            models.Index(fields=["normalized_query", "entity_type"]),
            models.Index(fields=["created_at", "results_count"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["session_key", "created_at"]),
        ]

    def __str__(self):
        return f"Search: '{self.query}' ({self.results_count} results)"

    @classmethod
    def normalize_query(cls, query):
        """Normalize query for consistent tracking"""
        return query.strip().lower()

    @classmethod
    def log_search(
        cls,
        query,
        results_count,
        search_types=None,
        entity_type=None,
        entity_id=None,
        user=None,
        session_key=None,
        ip_address=None,
        user_agent=None,
        filters_applied=None,
        response_time_ms=None,
    ):
        """Log a search query"""

        if not query or not query.strip():
            return None

        return cls.objects.create(
            query=query.strip(),
            normalized_query=cls.normalize_query(query),
            search_types=search_types or [],
            entity_type=entity_type,
            entity_id=entity_id,
            results_count=results_count,
            response_time_ms=response_time_ms,
            user=user,
            session_key=session_key,
            ip_address=ip_address,
            user_agent=user_agent,
            filters_applied=filters_applied or {},
        )

    def log_click(self, result_type, result_id, position):
        """Log when user clicks on a search result"""
        self.user_clicked_result = True
        self.clicked_result_type = result_type
        self.clicked_result_id = result_id
        self.click_position = position
        self.save(
            update_fields=[
                "user_clicked_result",
                "clicked_result_type",
                "clicked_result_id",
                "click_position",
            ]
        )


class PopularQuery(models.Model):
    """Aggregated popular queries for performance"""

    normalized_query = models.CharField(
        _("Normalized Query"), max_length=500, unique=True, db_index=True
    )
    search_count = models.IntegerField(_("Search Count"), default=0)
    click_count = models.IntegerField(_("Click Count"), default=0)
    avg_results_count = models.FloatField(_("Average Results Count"), default=0)
    click_through_rate = models.FloatField(
        _("Click Through Rate"), default=0
    )  # clicks / searches

    # Context popularity
    entity_types = models.JSONField(
        _("Entity Types"), default=dict, help_text=_("Count by entity type")
    )
    search_types = models.JSONField(
        _("Search Types"), default=dict, help_text=_("Count by search type")
    )

    # Timing
    first_searched = models.DateTimeField(_("First Searched"), auto_now_add=True)
    last_searched = models.DateTimeField(_("Last Searched"), auto_now=True)
    last_updated = models.DateTimeField(_("Last Updated"), auto_now=True)

    class Meta:
        verbose_name = _("Popular Query")
        verbose_name_plural = _("Popular Queries")
        indexes = [
            models.Index(fields=["-search_count", "-click_through_rate"]),
            models.Index(fields=["-last_searched"]),
        ]

    def __str__(self):
        return f"'{self.normalized_query}' ({self.search_count} searches, {self.click_count} clicks)"

    @classmethod
    def update_popularity(
        cls,
        normalized_query,
        entity_type=None,
        search_types=None,
        results_count=0,
        user_clicked=False,
    ):
        """Update popularity metrics for a query"""

        popular_query, created = cls.objects.get_or_create(
            normalized_query=normalized_query,
            defaults={
                "search_count": 0,
                "click_count": 0,
                "avg_results_count": 0,
                "click_through_rate": 0,
                "entity_types": {},
                "search_types": {},
            },
        )

        # Update search count
        popular_query.search_count += 1

        # Update click count
        if user_clicked:
            popular_query.click_count += 1

        # Update average results count
        popular_query.avg_results_count = (
            popular_query.avg_results_count * (popular_query.search_count - 1)
            + results_count
        ) / popular_query.search_count

        # Update click through rate
        popular_query.click_through_rate = (
            popular_query.click_count / popular_query.search_count
        )

        # Update entity type popularity
        if entity_type:
            popular_query.entity_types[entity_type] = (
                popular_query.entity_types.get(entity_type, 0) + 1
            )

        # Update search type popularity
        if search_types:
            for search_type in search_types:
                if "search_types" not in popular_query.search_types:
                    popular_query.search_types = {}
                popular_query.search_types[search_type] = (
                    popular_query.search_types.get(search_type, 0) + 1
                )

        popular_query.save()
        return popular_query
