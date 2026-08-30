"""
Decision-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "decisions/"

from api.views import decisions as decisions_views
from api.views import decisions_unified
from api.views import decision_lists
from api.views import search
from api.views import text_processes

urlpatterns = [
    # ── Unified decisions endpoint ──────────────────────────────────
    # GET /api/decisions/unified/?source=temporal&view=statistics
    path(
        "unified/",
        decisions_unified.decisions_unified_api,
        name="decisions_unified",
    ),
    # ── Top-N decision list endpoints (cached + pre-warmed) ─────────
    path(
        "top-payments/",
        decision_lists.top_payments_api,
        name="top_payments",
    ),
    path(
        "top-direct-assignments/",
        decision_lists.top_direct_assignments_api,
        name="top_direct_assignments",
    ),
    path(
        "top-by-amount/",
        decision_lists.top_by_amount_api,
        name="top_by_amount",
    ),
    # Decision detail endpoints (using integer ID)
    path("<int:decision_id>/", decisions_views.decision_detail, name="decision_detail"),
    path(
        "<int:decision_id>/entities/",
        decisions_views.decision_entities,
        name="decision_entities",
    ),
    path(
        "<int:decision_id>/related/",
        decisions_views.decision_related,
        name="decision_related",
    ),
    path(
        "<int:decision_id>/companies/",
        decisions_views.decision_companies,
        name="decision-companies",
    ),
    # Document content (legacy path - consider deprecating in favor of decisions/<id>/content/)
    path(
        "<int:decision_id>/content/",
        search.get_document_content_api_dev,
        name="decision_content_dev",
    ),
    # Run a text process on demand (amount, dates, ...)
    path(
        "<int:decision_id>/processes/run/",
        text_processes.run_text_process,
        name="decision_run_text_process",
    ),
]
