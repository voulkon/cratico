"""
Direct assignment analytics URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "direct-assignments/"

from api.views.direct_assignments import (
    direct_assignment_stats,
    direct_assignment_top_entities_global,
    direct_assignment_top_organizations_global,
    direct_assignment_top_pairs_global,
)

urlpatterns = [
    # Global direct assignment analytics
    path("stats/", direct_assignment_stats, name="direct_assignments_stats"),
    path(
        "top-entities/",
        direct_assignment_top_entities_global,
        name="direct_assignment_top_entities_global",
    ),
    path(
        "top-organizations/",
        direct_assignment_top_organizations_global,
        name="direct_assignment_top_organizations_global",
    ),
    path(
        "top-pairs/",
        direct_assignment_top_pairs_global,
        name="direct_assignment_top_pairs_global",
    ),
]
