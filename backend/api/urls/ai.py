"""
AI-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "ai/"

from api.views.ai.ai_decisions import (
    get_analysis,
    request_extraction,
    request_summary,
)
from api.views.ai.ai_interactions import (
    interactions_detail,
    interactions_list,
    interactions_summary,
    interactions_system_report,
)
from api.views.ai.ai_pipelines import pipelines_detail, pipelines_list
from api.views.ai.ai_settings import (
    ai_settings,
    ai_settings_create,
    ai_settings_row,
    list_models,
    sync_models,
    test_key,
)

urlpatterns = [
    # Settings
    path("settings/", ai_settings, name="ai_settings"),
    path("settings/test-key/", test_key, name="ai_test_key"),
    path("settings/rows/", ai_settings_create, name="ai_settings_create"),
    path("settings/rows/<int:pk>/", ai_settings_row, name="ai_settings_row"),
    # Models
    path("models/", list_models, name="ai_models_list"),
    path("models/sync/", sync_models, name="ai_models_sync"),
    # Interactions
    path("interactions/", interactions_list, name="ai_interactions_list"),
    path("interactions/summary/", interactions_summary, name="ai_interactions_summary"),
    path("interactions/system-report/", interactions_system_report, name="ai_system_report"),
    path("interactions/<int:pk>/", interactions_detail, name="ai_interaction_detail"),
    # Pipelines
    path("pipelines/", pipelines_list, name="ai_pipelines_list"),
    path("pipelines/<int:pk>/", pipelines_detail, name="ai_pipeline_detail"),
    # Decision AI (extraction + summarization)
    path("decisions/<int:decision_id>/extract/", request_extraction, name="ai_decision_extract"),
    path("decisions/<int:decision_id>/summarize/", request_summary, name="ai_decision_summarize"),
    path("decisions/<int:decision_id>/analysis/", get_analysis, name="ai_decision_analysis"),
]
