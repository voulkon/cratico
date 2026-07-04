"""
Browse-related URL patterns.
"""

from api.views.browse import browse_entities_api
from django.urls import path

# URL prefix for this module
PREFIX = "browse/"

urlpatterns = [
    path("entities/", browse_entities_api, name="browse_entities"),
]
