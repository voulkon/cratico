"""
Search-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "search/"
from api.views import search
from api.views.search import search_history_api

urlpatterns = [
    # Basic search endpoints
    path("", search.universal_search_api, name="universal_search"),
    path("dev/", search.universal_search_api_dev, name="universal_search_dev"),
    path(
        "entities-fast/", search.entities_fast_search_api, name="entities_fast_search"
    ),
    path("stream/", search.search_stream_api, name="search_stream"),
    path(
        "autocomplete/",
        search.autocomplete_suggestions_api,
        name="autocomplete_suggestions",
    ),
    path("suggestions/", search.default_suggestions_api, name="default_suggestions"),
    path("super/", search.super_search_api, name="super_search"),
    path("org-signer/", search.org_signer_search_api, name="org_signer_search"),
    path(
        "org-signer-unit/",
        search.org_signer_unit_search_api,
        name="org_signer_unit_search",
    ),
    path(
        "organization/", search.organization_only_search_api, name="organization_search"
    ),
    path("signer/", search.signer_only_search_api, name="signer_search"),
    path("company/", search.company_only_search_api, name="company_search"),
    path(
        "company-person/",
        search.company_person_only_search_api,
        name="company_person_search",
    ),
    path(
        "company-all/",
        search.company_and_persons_search_api,
        name="company_and_persons_search",
    ),
    # Search history endpoints
    path(
        "history/",
        search_history_api.personal_search_history_api,
        name="personal_search_history",
    ),
    path(
        "history/recent-queries/",
        search_history_api.recent_search_queries_api,
        name="recent_search_queries",
    ),
    path(
        "history/recently-visited/",
        search_history_api.recently_visited_api,
        name="recently_visited",
    ),
    path(
        "history/item/",
        search_history_api.delete_single_history_item_api,
        name="delete_single_history_item",
    ),
    path(
        "history/clear/",
        search_history_api.clear_search_history_api,
        name="clear_search_history",
    ),
    path(
        "history/track-selection/",
        search_history_api.track_search_selection_api,
        name="track_search_selection",
    ),
    # Document search
    path("documents/", search.document_search_api, name="document_search"),
    path("documents-dev/", search.document_search_api_dev, name="document_search_dev"),
]
