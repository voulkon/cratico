"""
Main API URL Configuration

This module organizes API URLs into logical groups for better maintainability.
Each group is in its own file under the api/urls/ directory.

Each URL module declares its own PREFIX constant, which is used by the stealth
middleware to automatically determine which endpoints should be exempt from
authentication requirements.

URL Structure:
- /api/auth/* - Authentication endpoints (exempt from stealth mode)
- /api/search/* - Search endpoints
- /api/entity/* - Entity analytics
- /api/explore/* - Temporal exploration
- /api/notifications/* - Notification subscriptions and batches
- /api/decisions/* - Decision details
- /api/companies/* - Company information
- /api/browse/* - Alphabetical entity browsing
- /api/organizations/* - Organization information
- /api/direct-assignments/* - Direct assignment analytics
- /api/system/* - System configuration
- /api/tasks/* - Background task management
"""

# Import URL modules to get their PREFIX constants (single source of truth)
from api.urls import (
    ai,
    auth,
    browse,
    companies,
    decisions,
    direct_assignments,
    entities,
    explore,
    notifications,
    organizations,
    search,
    system,
    tasks,
    public,
    text_processes,
)
from api.views import entities as entities_views
from api.views.direct_assignments import entity_direct_assignment_top_organizations
from api.views.organization_entity_relationships import (
    entity_top_organizations_api,
    relationship_date_range_api,
    relationship_decisions_api,
    relationship_decision_types_api,
    relationship_statistics_api,
)

# Import remaining views not extracted to modules
from api.views.organization_views import (
    organization_chart_api,
    organization_chart_api_dev,
)
from api.views.summary import amounts as summary_amounts_views
from api.views.tracing_test_views import tracing_test_views
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from users.views import UserDataViewSet

# Create router for user data
router = DefaultRouter()
router.register("user-data", UserDataViewSet, basename="user-data")

urlpatterns = [
    # Include router URLs
    path("", include(router.urls)),
    # Public sharing endpoints (no auth required - exempted from stealth mode)
    path(public.PREFIX, include("api.urls.public")),
    # Modular URL includes using PREFIX constants (single source of truth)
    # The PREFIX from each module is used both here AND in the stealth middleware
    path(auth.PREFIX, include("api.urls.auth")),
    path(ai.PREFIX, include("api.urls.ai")),
    path(notifications.PREFIX, include("api.urls.notifications")),
    path(search.PREFIX, include("api.urls.search")),
    path(entities.PREFIX, include("api.urls.entities")),
    path(explore.PREFIX, include("api.urls.explore")),
    path(decisions.PREFIX, include("api.urls.decisions")),
    path(companies.PREFIX, include("api.urls.companies")),
    path(organizations.PREFIX, include("api.urls.organizations")),
    path(browse.PREFIX, include("api.urls.browse")),
    path(direct_assignments.PREFIX, include("api.urls.direct_assignments")),
    path(system.PREFIX, include("api.urls.system")),
    path(tasks.PREFIX, include("api.urls.tasks")),
    path(text_processes.PREFIX, include("api.urls.text_processes")),
    # Legacy organization chart endpoints (TODO: consider moving to organizations module)
    path("org-chart-api/", organization_chart_api, name="org-chart-api"),
    path("org-chart-api-dev/", organization_chart_api_dev, name="org-chart-api-dev"),
    # Legacy entity endpoints (TODO: consider moving to entities module or using /api/entity/ prefix)
    path(
        "entity/afm/<str:afm>/",
        entities_views.afm_entity_detail,
        name="afm_entity_detail",
    ),
    path(
        "entity/afm/<str:afm>/decisions/",
        entities_views.afm_entity_decisions,
        name="afm_entity_decisions",
    ),
    path(
        "entity/afm/<str:afm>/decision-types/",
        entities_views.afm_entity_decision_types,
        name="afm_entity_decision_types",
    ),
    path(
        "entity/afm/<str:afm>/statistics/",
        entities_views.afm_entity_statistics,
        name="afm_entity_statistics",
    ),
    path(
        "entity/afm/<str:afm>/date-range/",
        entities_views.afm_entity_date_range,
        name="afm_entity_date_range",
    ),
    path(
        "entity/afm/<str:afm>/request-fetch/",
        entities_views.request_afm_fetch,
        name="afm_entity_request_fetch",
    ),
    path(
        "entities/<str:afm>/top-organizations/",
        entity_top_organizations_api,
        name="entity_top_organizations",
    ),
    path(
        "entities/<str:afm>/direct-assignments/top-organizations/",
        entity_direct_assignment_top_organizations,
        name="entity_direct_assignment_top_orgs",
    ),
    # Transaction summaries (TODO: consider creating a transactions module)
    path(
        "transactions/top/",
        summary_amounts_views.top_transactions,
        name="top-transactions",
    ),
    # Relationship detail endpoints
    path(
        "relationship/entity/<str:afm>/org/<str:orgUid>/date-range/",
        relationship_date_range_api,
        name="relationship_date_range",
    ),
    path(
        "relationship/entity/<str:afm>/org/<str:orgUid>/statistics/",
        relationship_statistics_api,
        name="relationship_statistics",
    ),
    path(
        "relationship/entity/<str:afm>/org/<str:orgUid>/decision-types/",
        relationship_decision_types_api,
        name="relationship_decision_types",
    ),
    path(
        "relationship/entity/<str:afm>/org/<str:orgUid>/decisions/",
        relationship_decisions_api,
        name="relationship_decisions",
    ),
    # Debug/tracing endpoints (TODO: move to debug module or remove in production)
    path(
        "debug-tracing/test-tracing/",
        tracing_test_views.test_tracing,
        name="test-tracing",
    ),
    path(
        "debug-tracing/test-tracing-verbose/",
        tracing_test_views.test_tracing_verbose,
        name="test-tracing-verbose",
    ),
    path(
        "debug-tracing/force-export/",
        tracing_test_views.force_trace_export,
        name="force-export",
    ),
    path(
        "debug-tracing/environment/",
        tracing_test_views.debug_environment,
        name="debug-environment",
    ),
    path(
        "debug-tracing/test-celery/",
        tracing_test_views.test_celery_tracing,
        name="test-celery",
    ),
    path(
        "debug-tracing/test-simple-task/",
        tracing_test_views.test_simple_task,
        name="test-simple-task",
    ),
    path(
        "debug-tracing/test-error/",
        tracing_test_views.test_error_tracing,
        name="test-error",
    ),
    path(
        "debug-tracing/test-nested/",
        tracing_test_views.test_nested_tracing,
        name="test-nested",
    ),
]
