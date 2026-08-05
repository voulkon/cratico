"""
Text process URL patterns.
"""

from django.urls import path

PREFIX = "processes/"

from api.views import text_processes

urlpatterns = [
    path("", text_processes.list_text_processes, name="list_text_processes"),
]
