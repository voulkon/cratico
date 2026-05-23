"""
Company-related URL patterns.
"""

from django.urls import path

# URL prefix for this module
PREFIX = "companies/"

from api.views.companies.details import (
    company_decision_stats,
    company_decisions,
    company_detail,
)
from api.views.summary import amounts as summary_amounts_views

urlpatterns = [
    path("<int:company_id>/", company_detail, name="company-detail"),
    path("<int:company_id>/decisions/", company_decisions, name="company-decisions"),
    path(
        "<int:company_id>/stats/", company_decision_stats, name="company-decision-stats"
    ),
    path(
        "<str:afm>/transactions/",
        summary_amounts_views.company_transactions_summary,
        name="company-transactions",
    ),
]
