"""
Entity and exploration-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "entity/"
from api.views import search

urlpatterns = [
    # Entity analytics
    path(
        "<str:entity_type>/<str:entity_id>/statistics/",
        search.entity_statistics_api_dev,
        name="entity_statistics_dev",
    ),
    path(
        "<str:entity_type>/<str:entity_id>/decisions/",
        search.entity_decisions_api_dev,
        name="entity_decisions_dev",
    ),
    path(
        "<str:entity_type>/<str:entity_id>/documents/",
        search.entity_search_documents_api_dev,
        name="entity_documents_dev",
    ),
    path(
        "<str:entity_type>/<str:entity_id>/timeline/",
        search.entity_timeline_api_dev,
        name="entity_timeline_dev",
    ),
    path(
        "<str:entity_type>/<str:entity_id>/decision-types/",
        search.entity_decision_types_api_dev,
        name="entity_decision_types_dev",
    ),
    path(
        "<str:entity_type>/<str:entity_id>/date-range/",
        search.entity_date_range_api_dev,
        name="entity_date_range_dev",
    ),
]
