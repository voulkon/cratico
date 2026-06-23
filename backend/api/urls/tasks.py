"""
Background task management URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "tasks/"

from api.custom_views.document_processing import ProcessDocumentsView
from api.custom_views.import_decisions import calendar_bulk_import
from api.custom_views.say_hi import SayHiView
from api.custom_views.task_status import TaskStatusView

urlpatterns = [
    path("process/", ProcessDocumentsView.as_view(), name="process-documents"),
    path("import-decisions/", calendar_bulk_import, name="admin_import_decisions"),
    path("say-hi-to-worker/", SayHiView.as_view(), name="say-hi-to-worker"),
    path("status/<str:task_id>/", TaskStatusView.as_view(), name="task-status"),
]
