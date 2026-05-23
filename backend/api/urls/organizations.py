"""
Organization-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "organizations/"

from api.views.direct_assignments import organization_direct_assignment_top_recipients
from api.views.organization_entity_relationships import (
    organization_top_counterparts_api,
)
from api.views.organy import details as details_between_companies_and_orgs
from api.views.summary import amounts as summary_amounts_views

urlpatterns = [
    path(
        "<str:organization_uid>/expenditures/",
        summary_amounts_views.organization_expenditures_summary,
        name="organization-expenditures",
    ),
    path(
        "<str:organization_uid>/transactions/",
        details_between_companies_and_orgs.organization_entity_transactions,
        name="organization-transactions",
    ),
    path(
        "<str:organization_uid>/transactions/<str:afm>/",
        details_between_companies_and_orgs.organization_entity_transactions,
        name="organization-entity-transactions",
    ),
    path(
        "<str:organization_uid>/top-counterparts/",
        organization_top_counterparts_api,
        name="organization_top_counterparts",
    ),
    path(
        "<str:organization_uid>/direct-assignments/top-recipients/",
        organization_direct_assignment_top_recipients,
        name="org_direct_assignment_top_recipients",
    ),
]
