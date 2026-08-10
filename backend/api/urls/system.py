"""
System configuration URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "system/"

from api.views import system as system_views

urlpatterns = [
    path("config/auth/", system_views.auth_config, name="auth_config"),
    # Legal documents - single endpoint for all documents
    path("legal/", system_views.get_legal_documents, name="legal_documents"),
    # Rate-limit management (staff only)
    path(
        "rate-limit/reset/",
        system_views.admin_reset_rate_limit,
        name="admin_reset_rate_limit",
    ),
    path(
        "rate-limit/request-reset/",
        system_views.request_rate_limit_reset,
        name="request_rate_limit_reset",
    ),
    path(
        "rate-limit/status/<int:user_id>/",
        system_views.get_rate_limit_status,
        name="rate_limit_status",
    ),
    path(
        "rate-limit/pending-requests/",
        system_views.list_pending_reset_requests,
        name="list_pending_reset_requests",
    ),
]
