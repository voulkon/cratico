"""
Temporal exploration-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "explore/"
from api.views import search
from api.views.organization_entity_relationships import (
    temporal_top_relationship_pairs_api,
)

urlpatterns = [
    # Temporal exploration
    path(
        "date-range/", search.explore_date_range_api_dev, name="explore_date_range_dev"
    ),
    path(
        "statistics/", search.explore_statistics_api_dev, name="explore_statistics_dev"
    ),
    path("decisions/", search.explore_decisions_api_dev, name="explore_decisions_dev"),
    path(
        "decision-types/",
        search.explore_decision_types_api_dev,
        name="explore_decision_types_dev",
    ),
    path(
        "organizations/",
        search.explore_organizations_api_dev,
        name="explore_organizations_dev",
    ),
    path(
        "decisions-optimized/",
        search.explore_decisions_optimized_api,
        name="explore_decisions_optimized",
    ),
    path(
        "temporal/top-relationships/",
        temporal_top_relationship_pairs_api,
        name="temporal-top-relationships",
    ),
]
