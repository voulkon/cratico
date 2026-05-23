import time

from api.utils.common import get_client_ip
from core.models.search_analytics import PopularQuery, SearchAnalytics
from django.db.models import Avg, Count, Q
from django.utils import timezone


class SearchAnalyticsService:
    """Service for handling search analytics and query ranking"""

    @classmethod
    def log_search_start(
        cls,
        query,
        search_types=None,
        entity_type=None,
        entity_id=None,
        request=None,
        filters_applied=None,
    ):
        """Log the start of a search and return tracking info"""

        # Extract request info
        user = (
            request.user
            if request and hasattr(request, "user") and request.user.is_authenticated
            else None
        )
        session_key = (
            request.session.session_key
            if request and hasattr(request, "session")
            else None
        )
        ip_address = get_client_ip(request) if request else None
        user_agent = request.META.get("HTTP_USER_AGENT") if request else None

        # Start timing
        start_time = time.time()

        return {
            "query": query,
            "search_types": search_types,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "user": user,
            "session_key": session_key,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "filters_applied": filters_applied,
            "start_time": start_time,
        }

    @classmethod
    def log_search_complete(cls, tracking_info, results_count):
        """Complete the search logging with results"""

        if not tracking_info or not tracking_info.get("query"):
            return None

        # Calculate response time
        response_time_ms = None
        if tracking_info.get("start_time"):
            response_time_ms = int((time.time() - tracking_info["start_time"]) * 1000)

        # Log to SearchAnalytics
        search_log = SearchAnalytics.log_search(
            query=tracking_info["query"],
            results_count=results_count,
            search_types=tracking_info.get("search_types"),
            entity_type=tracking_info.get("entity_type"),
            entity_id=tracking_info.get("entity_id"),
            user=tracking_info.get("user"),
            session_key=tracking_info.get("session_key"),
            ip_address=tracking_info.get("ip_address"),
            user_agent=tracking_info.get("user_agent"),
            filters_applied=tracking_info.get("filters_applied"),
            response_time_ms=response_time_ms,
        )

        # Update popularity metrics
        if search_log:
            PopularQuery.update_popularity(
                normalized_query=search_log.normalized_query,
                entity_type=tracking_info.get("entity_type"),
                search_types=tracking_info.get("search_types"),
                results_count=results_count,
                user_clicked=False,  # Will be updated when user clicks
            )

        return search_log

    @classmethod
    def log_result_click(cls, search_log_id, result_type, result_id, position):
        """Log when a user clicks on a search result"""
        try:
            search_log = SearchAnalytics.objects.get(id=search_log_id)
            search_log.log_click(result_type, result_id, position)

            # Update popularity with click
            PopularQuery.update_popularity(
                normalized_query=search_log.normalized_query,
                entity_type=search_log.entity_type,
                search_types=search_log.search_types,
                results_count=search_log.results_count,
                user_clicked=True,
            )

            return search_log
        except SearchAnalytics.DoesNotExist:
            return None

    @classmethod
    def get_popular_queries(cls, entity_type=None, limit=10, min_searches=2):
        """Get popular queries for suggestions"""

        qs = PopularQuery.objects.filter(search_count__gte=min_searches)

        if entity_type:
            # Filter by entity type if specified
            qs = qs.filter(entity_types__has_key=entity_type)

        return qs.order_by("-search_count", "-click_through_rate")[:limit]

    @classmethod
    def get_query_suggestions(cls, partial_query, entity_type=None, limit=5):
        """Get query suggestions based on popular searches"""

        if not partial_query or len(partial_query) < 2:
            return []

        # Find popular queries that start with the partial query
        qs = PopularQuery.objects.filter(
            normalized_query__startswith=partial_query.lower(), search_count__gte=2
        )

        if entity_type:
            qs = qs.filter(entity_types__has_key=entity_type)

        suggestions = qs.order_by("-search_count", "-click_through_rate")[:limit]

        return [
            {
                "query": suggestion.normalized_query,
                "search_count": suggestion.search_count,
                "click_through_rate": suggestion.click_through_rate,
            }
            for suggestion in suggestions
        ]

    @classmethod
    def get_search_stats(cls, days=30):
        """Get search statistics for the last N days"""

        since_date = timezone.now() - timezone.timedelta(days=days)

        stats = SearchAnalytics.objects.filter(created_at__gte=since_date).aggregate(
            total_searches=Count("id"),
            unique_queries=Count("normalized_query", distinct=True),
            avg_results_per_search=Avg("results_count"),
            searches_with_clicks=Count("id", filter=Q(user_clicked_result=True)),
            avg_response_time=Avg("response_time_ms"),
        )

        # Calculate click through rate
        total_searches = stats["total_searches"] or 0
        searches_with_clicks = stats["searches_with_clicks"] or 0
        stats["click_through_rate"] = (
            (searches_with_clicks / total_searches * 100) if total_searches > 0 else 0
        )

        return stats
