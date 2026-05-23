"""
System configuration URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "system/"

from api.views import system as system_views

urlpatterns = [
    path("config/", system_views.system_config, name="system_config"),
    path("config/auth/", system_views.auth_config, name="auth_config"),
    # Legal documents - single endpoint for all documents
    path("legal/", system_views.get_legal_documents, name="legal_documents"),
]
