from django.contrib import admin
from django.urls import path


class CustomAdminSite(admin.AdminSite):
    site_header = "Crati Administration"
    site_title = "Crati Admin"
    index_title = "Welcome to Crati Administration"

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            # Analytics URLs
            path(
                "analytics/",
                self._wrap_view("analytics", "redis_analytics"),
                name="redis_analytics",
            ),
            path(
                "analytics/export/",
                self._wrap_view("analytics", "export_redis_analytics"),
                name="export_analytics",
            ),
            path(
                "analytics/endpoints/",
                self._wrap_view("analytics", "endpoint_deep_dive"),
                name="endpoint_deep_dive",
            ),
            path(
                "analytics/warmup/",
                self._wrap_view("analytics", "trigger_analytics_warmup"),
                name="trigger_analytics_warmup",
            ),
            path(
                "analytics/subscription-checks/",
                self._wrap_view("analytics", "trigger_subscription_checks"),
                name="trigger_subscription_checks",
            ),
            path(
                "analytics/entity-rankings/",
                self._wrap_view("analytics", "trigger_entity_rankings"),
                name="trigger_entity_rankings",
            ),
            # Amount-Entity Linkage Analysis
            path(
                "amount-entity-analysis/",
                self._wrap_view("amount_entity_analysis", "amount_entity_analysis"),
                name="amount_entity_analysis",
            ),
            path(
                "amount-entity-analysis/samples/refresh/",
                self._wrap_view("amount_entity_analysis", "refresh_samples_api"),
                name="amount_entity_analysis_refresh_samples",
            ),
            # Decision URLs
            path(
                "decisions/coverage/",
                self._wrap_view("decisions", "coverage_explorer"),
                name="coverage_explorer",
            ),
            path(
                "decisions/entity-search/",
                self._wrap_view("decisions", "entity_search"),
                name="entity_search",
            ),
            path(
                "decisions/daily-analysis/",
                self._wrap_view("decisions", "daily_decision_analysis"),
                name="daily_decision_analysis",
            ),
            path(
                "decisions/analysis-api/",
                self._wrap_view("decisions", "decision_analysis_api"),
                name="decision_analysis_api",
            ),
            path(
                "decisions/fetch-daily/",
                self._wrap_view("decisions", "fetch_daily_decisions"),
                name="fetch_daily_decisions",
            ),
            # Organization URLs
            path(
                "organizations/network/",
                self._wrap_view("organization", "organization_network"),
                name="organization_network",
            ),
            path(
                "organizations/chart/",
                self._wrap_view("organization", "organization_org_chart"),
                name="organization_chart",
            ),
            # Document URLs
            path(
                "documents/search/",
                self._wrap_view("documents", "document_search"),
                name="document_search",
            ),
            path(
                "documents/dashboard/",
                self._wrap_view("documents", "document_processing_dashboard"),
                name="document_dashboard",
            ),
            path(
                "documents/sync-status/",
                self._wrap_view("documents", "sync_status_dashboard"),
                name="sync_status_dashboard",
            ),
            # Health Check URLs
            path(
                "health/dashboard/",
                self._wrap_view("health", "health_dashboard_view"),
                name="health_dashboard",
            ),
            path(
                "health/quick-check/",
                self._wrap_view("health", "quick_health_check_view"),
                name="quick_health_check",
            ),
            path(
                "health/bulk-check/",
                self._wrap_view("health", "bulk_check_view"),
                name="bulk_health_check",
            ),
            path(
                "health/<int:pk>/",
                self._wrap_view("health", "health_check_detail_view"),
                name="health_check_detail",
            ),
            path(
                "health/<int:pk>/refresh/",
                self._wrap_view("health", "refresh_single_check"),
                name="health_refresh_single",
            ),
            path(
                "health/<int:pk>/fix-entities/",
                self._wrap_view("health", "fix_entity_data"),
                name="health_fix_entities",
            ),
            path(
                "health/<int:pk>/retry-extraction/",
                self._wrap_view("health", "retry_document_extraction"),
                name="health_retry_extraction",
            ),
            path(
                "health/<int:pk>/reindex/",
                self._wrap_view("health", "reindex_opensearch"),
                name="health_reindex",
            ),
            path(
                "health/<int:pk>/reextract-entities/",
                self._wrap_view("health", "reextract_entities"),
                name="health_reextract_entities",
            ),
            path(
                "health/<int:pk>/relink-relations/",
                self._wrap_view("health", "relink_relations"),
                name="health_relink_relations",
            ),
            path(
                "health/<int:pk>/update-coverage/",
                self._wrap_view("health", "update_coverage"),
                name="health_update_coverage",
            ),
            # AI Job URLs
            path(
                "jobs/<int:job_id>/estimate/",
                self._wrap_view("ai_jobs", "estimate_job_cost_view"),
                name="estimate_job_cost",
            ),
            # Search Suggestion URLs
            path(
                "search-suggestions/manager/",
                self._wrap_view("search_suggestions", "search_suggestion_manager"),
                name="search_suggestion_manager",
            ),
            path(
                "search-suggestions/entity-search/",
                self._wrap_view(
                    "search_suggestions", "search_suggestion_entity_search"
                ),
                name="search_suggestion_entity_search",
            ),
            path(
                "search-suggestions/<int:pk>/delete/",
                self._wrap_view("search_suggestions", "delete_search_suggestion"),
                name="delete_search_suggestion",
            ),
            path(
                "search-suggestions/<int:pk>/toggle/",
                self._wrap_view("search_suggestions", "toggle_search_suggestion"),
                name="toggle_search_suggestion",
            ),
            path(
                "search-suggestions/<int:pk>/move-up/",
                self._wrap_view("search_suggestions", "move_suggestion_up"),
                name="move_suggestion_up",
            ),
            path(
                "search-suggestions/<int:pk>/move-down/",
                self._wrap_view("search_suggestions", "move_suggestion_down"),
                name="move_suggestion_down",
            ),
            # PostgreSQL Search Management URLs
            path(
                "search-management/postgres/",
                self._wrap_view("search_management", "postgres_search_dashboard"),
                name="postgres_search_dashboard",
            ),
            path(
                "search-management/postgres/execute/",
                self._wrap_view("search_management", "execute_search_command"),
                name="execute_search_command",
            ),
            path(
                "search-management/postgres/task/<str:task_id>/",
                self._wrap_view("search_management", "search_task_status"),
                name="search_task_status",
            ),
            # Database Storage Dashboard URLs
            path(
                "db-storage/",
                self._wrap_view("db_storage_dashboard", "db_storage_dashboard"),
                name="db_storage_dashboard",
            ),
            path(
                "db-storage/vacuum/",
                self._wrap_view("db_storage_dashboard", "run_vacuum"),
                name="run_vacuum",
            ),
            path(
                "db-storage/vacuum/bloated/",
                self._wrap_view("db_storage_dashboard", "run_vacuum_bloated"),
                name="run_vacuum_bloated",
            ),
            path(
                "db-storage/vacuum/status/<str:task_id>/",
                self._wrap_view("db_storage_dashboard", "vacuum_task_status"),
                name="vacuum_task_status",
            ),
            # Database Storage Dashboard API URLs (for lazy loading)
            path(
                "db-storage/extended-stats/",
                self._wrap_view("db_storage_dashboard", "get_extended_database_stats"),
                name="get_extended_database_stats",
            ),
            path(
                "db-storage/tables/",
                self._wrap_view("db_storage_dashboard", "get_table_stats"),
                name="get_table_stats",
            ),
            path(
                "db-storage/indexes/",
                self._wrap_view("db_storage_dashboard", "get_index_stats"),
                name="get_index_stats",
            ),
            path(
                "db-storage/columns/",
                self._wrap_view("db_storage_dashboard", "get_column_stats"),
                name="get_column_stats",
            ),
            path(
                "db-storage/bloat/",
                self._wrap_view("db_storage_dashboard", "get_bloat_stats"),
                name="get_bloat_stats",
            ),
            # Classification Job URLs
            path(
                "classification/dashboard/",
                self._wrap_view("classification_jobs", "dashboard"),
                name="classification_dashboard",
            ),
        ]
        return custom_urls + urls

    def _wrap_view(self, module_name, view_name):
        """Lazy import and wrap view to avoid circular imports"""

        def view_wrapper(request, *args, **kwargs):
            from importlib import import_module

            module = import_module(f"admin_custom.views.{module_name}")
            view = getattr(module, view_name)
            return view(request, *args, **kwargs)

        return self.admin_view(view_wrapper)

    def get_app_list(self, request, app_label=None):
        app_list = super().get_app_list(request, app_label)

        # Remove EndpointAccessLog and FlaggedIP from the default "Api" section
        # — they appear under "Security & Threat Detection" instead.
        for app in app_list:
            if app.get("app_label") == "api":
                app["models"] = [
                    m
                    for m in app["models"]
                    if m["object_name"] not in ("EndpointAccessLog", "FlaggedIP")
                ]

        # Add custom Analytics section
        analytics_app = {
            "name": "Analytics & Monitoring",
            "app_label": "analytics",
            "models": [
                {
                    "name": "Redis Analytics",
                    "object_name": "RedisAnalytics",
                    "admin_url": "/api/admin/analytics/",
                    "view_only": True,
                },
                {
                    "name": "Export Analytics",
                    "object_name": "ExportAnalytics",
                    "admin_url": "/api/admin/analytics/export/",
                    "view_only": True,
                },
                {
                    "name": "Cache Warmup",
                    "object_name": "CacheWarmup",
                    "admin_url": "/api/admin/analytics/warmup/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(analytics_app)

        # Add Security & Threat Detection section
        security_app = {
            "name": "Security & Threat Detection",
            "app_label": "security",
            "models": [
                {
                    "name": "Flagged IPs",
                    "object_name": "FlaggedIP",
                    "admin_url": "/api/admin/api/flaggedip/",
                },
                {
                    "name": "Endpoint Access Logs (Forensic)",
                    "object_name": "EndpointAccessLog",
                    "admin_url": "/api/admin/api/endpointaccesslog/",
                },
            ],
        }
        app_list.append(security_app)

        # Add custom Decision Management section
        decision_mgmt_app = {
            "name": "Decision Management",
            "app_label": "decision_management",
            "models": [
                {
                    "name": "Coverage Explorer",
                    "object_name": "CoverageExplorer",
                    "admin_url": "/api/admin/decisions/coverage/",
                    "view_only": True,
                },
                {
                    "name": "Daily Decision Analysis",
                    "object_name": "DailyDecisionAnalysis",
                    "admin_url": "/api/admin/decisions/daily-analysis/?mode=simple",
                    "view_only": True,
                },
                {
                    "name": "Entity Search",
                    "object_name": "EntitySearch",
                    "admin_url": "/api/admin/decisions/entity-search/",
                    "view_only": True,
                },
                {
                    "name": "Amount ↔ Entity Linkage",
                    "object_name": "AmountEntityLinkage",
                    "admin_url": "/api/admin/amount-entity-analysis/",
                    "view_only": True,
                },
                {
                    "name": "Batch Amount Correction",
                    "object_name": "BatchAmountCorrection",
                    "admin_url": "/api/admin/core/decision/batch-correct-amounts/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(decision_mgmt_app)

        # Add Search & User Experience section
        search_ux_app = {
            "name": "Search & User Experience",
            "app_label": "search_ux",
            "models": [
                {
                    "name": "Search Suggestion Manager",
                    "object_name": "SearchSuggestionManager",
                    "admin_url": "/api/admin/search-suggestions/manager/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(search_ux_app)

        # Add Search Infrastructure Management section
        search_infra_app = {
            "name": "Search Infrastructure",
            "app_label": "search_infrastructure",
            "models": [
                {
                    "name": "PostgreSQL Search Management",
                    "object_name": "PostgresSearchDashboard",
                    "admin_url": "/api/admin/search-management/postgres/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(search_infra_app)

        # Add Database Management section
        db_management_app = {
            "name": "Database Management",
            "app_label": "database_management",
            "models": [
                {
                    "name": "Storage Dashboard",
                    "object_name": "DatabaseStorageDashboard",
                    "admin_url": "/api/admin/db-storage/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(db_management_app)

        # Add custom Organization Tools section
        org_tools_app = {
            "name": "Organization Tools",
            "app_label": "organization_tools",
            "models": [
                {
                    "name": "Organization Network",
                    "object_name": "OrganizationNetwork",
                    "admin_url": "/api/admin/organizations/network/",
                    "view_only": True,
                },
                {
                    "name": "Organization Chart",
                    "object_name": "OrganizationChart",
                    "admin_url": "/api/admin/organizations/chart/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(org_tools_app)

        # Add custom Document Processing section
        doc_processing_app = {
            "name": "Document Processing",
            "app_label": "document_processing",
            "models": [
                {
                    "name": "Document Search",
                    "object_name": "DocumentSearch",
                    "admin_url": "/api/admin/documents/search/",
                    "view_only": True,
                },
                {
                    "name": "Processing Dashboard",
                    "object_name": "DocumentDashboard",
                    "admin_url": "/api/admin/documents/dashboard/",
                    "view_only": True,
                },
                {
                    "name": "Sync Status Dashboard",
                    "object_name": "SyncStatusDashboard",
                    "admin_url": "/api/admin/documents/sync-status/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(doc_processing_app)

        # Add custom Health Check section
        health_app = {
            "name": "Health & Diagnostics",
            "app_label": "health",
            "models": [
                {
                    "name": "Quick Health Check",
                    "object_name": "QuickHealthCheck",
                    "admin_url": "/api/admin/health/quick-check/",
                    "view_only": True,
                },
                {
                    "name": "Health Dashboard",
                    "object_name": "HealthDashboard",
                    "admin_url": "/api/admin/health/dashboard/",
                    "view_only": True,
                },
                {
                    "name": "Bulk Health Check",
                    "object_name": "BulkHealthCheck",
                    "admin_url": "/api/admin/health/bulk-check/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(health_app)

        # Add Post-Import Tasks section
        post_import_app = {
            "name": "Post-Import Tasks",
            "app_label": "post_import",
            "models": [
                {
                    "name": "Entity Rankings",
                    "object_name": "EntityRankings",
                    "admin_url": "/api/admin/analytics/entity-rankings/",
                    "view_only": True,
                },
                {
                    "name": "Cache Warmup",
                    "object_name": "CacheWarmup",
                    "admin_url": "/api/admin/analytics/warmup/",
                    "view_only": True,
                },
                {
                    "name": "Subscription Checks",
                    "object_name": "SubscriptionChecks",
                    "admin_url": "/api/admin/analytics/subscription-checks/",
                    "view_only": True,
                },
            ],
        }
        app_list.append(post_import_app)

        return app_list


# Create singleton instance
admin_site = CustomAdminSite(name="custom_admin")


# Register all models with the custom admin site
def register_all_models():
    """Register all models with the custom admin site"""
    from admin_custom.admin_classes import (
        AFMEntityStatsAdmin,
        AIJobDefinitionAdmin,
        AIJobExecutionAdmin,
        AIModelPricingAdmin,
        APIAnalyticsAdmin,
        AttachmentAdmin,
        BackupAdmin,
        ClassificationJobAdmin,
        CustomUserAdmin,
        DailyTrafficAdmin,
        DecisionAdmin,
        DecisionHealthCheckAdmin,
        DecisionHealthSummaryAdmin,
        DocumentAnalysisAdmin,
        DocumentEmbeddingAdmin,
        DocumentExtractionAdmin,
        EndpointAccessLogAdmin,
        EndpointStatsAdmin,
        FeatureFlagAdmin,
        FeatureFlagAuditLogAdmin,
        FlaggedIPAdmin,
        ImportJobAdmin,
        ImportThresholdAdmin,
        LegalDocumentAdmin,
        NotificationAdmin,
        NotificationBatchAdmin,
        NotificationBatchDecisionAdmin,
        NotificationSubscriptionAdmin,
        OrganizationAdmin,
        SignerAdmin,
        SubscriptionAdmin,
        TaskOutputEstimateAdmin,
        UnitAdmin,
    )
    from admin_custom.admin_classes.afm_scoring import (
        AFMEntityAdmin,
        AFMEntityScoreAdmin,
        AFMScoringConfigAdmin,
        AFMScoringJobAdmin,
    )
    from api.models import APIAnalytics, DailyTraffic, EndpointStats
    from api.models import EndpointAccessLog, FlaggedIP
    from core.models.ai_pricing import (
        AIJobDefinition,
        AIJobExecution,
        AIModelPricing,
        TaskOutputEstimate,
    )
    from core.models.backups import Backup
    from core.models.classification_job import ClassificationJob
    from core.models.decision_health import DecisionHealthCheck, DecisionHealthSummary
    from core.models.decisions import Attachment, Decision
    from core.models.document_analysis import (
        DocumentAnalysis,
        DocumentEmbedding,
        DocumentExtraction,
    )
    from core.models.feature_flags import FeatureFlag, FeatureFlagAuditLog
    from core.models.import_jobs import DateCoverage, ImportJob
    from core.models.import_thresholds import ImportThreshold
    from core.models.organizations import Organization, Signer, Unit
    from core.models.terms import LegalDocument
    from notifications.models import (
        Notification,
        NotificationBatch,
        NotificationBatchDecision,
        NotificationSubscription,
    )
    from users.models import CustomUser, Subscription

    # Register Decision models
    admin_site.register(Decision, DecisionAdmin)
    admin_site.register(Attachment, AttachmentAdmin)
    admin_site.register(Organization, OrganizationAdmin)
    admin_site.register(Unit, UnitAdmin)
    admin_site.register(Signer, SignerAdmin)

    # Register Document models
    admin_site.register(DocumentExtraction, DocumentExtractionAdmin)
    admin_site.register(DocumentAnalysis, DocumentAnalysisAdmin)
    admin_site.register(DocumentEmbedding, DocumentEmbeddingAdmin)

    # Register AI Pricing models
    admin_site.register(AIModelPricing, AIModelPricingAdmin)
    admin_site.register(TaskOutputEstimate, TaskOutputEstimateAdmin)
    admin_site.register(AIJobDefinition, AIJobDefinitionAdmin)
    admin_site.register(AIJobExecution, AIJobExecutionAdmin)

    # Register Health models
    admin_site.register(DecisionHealthCheck, DecisionHealthCheckAdmin)
    admin_site.register(DecisionHealthSummary, DecisionHealthSummaryAdmin)

    # Register Analytics models
    admin_site.register(APIAnalytics, APIAnalyticsAdmin)
    admin_site.register(EndpointStats, EndpointStatsAdmin)
    admin_site.register(EndpointAccessLog, EndpointAccessLogAdmin)
    admin_site.register(FlaggedIP, FlaggedIPAdmin)
    admin_site.register(DailyTraffic, DailyTrafficAdmin)
    admin_site.register(ImportJob, ImportJobAdmin)
    admin_site.register(DateCoverage)

    # Register User models
    admin_site.register(CustomUser, CustomUserAdmin)
    admin_site.register(Subscription, SubscriptionAdmin)

    # Register Backup models
    admin_site.register(Backup, BackupAdmin)

    # Register Import Validation models
    admin_site.register(ImportThreshold, ImportThresholdAdmin)

    # Register Legal Documents models
    admin_site.register(LegalDocument, LegalDocumentAdmin)

    # Register Notification models
    admin_site.register(NotificationSubscription, NotificationSubscriptionAdmin)
    admin_site.register(Notification, NotificationAdmin)
    admin_site.register(NotificationBatch, NotificationBatchAdmin)

    # Register Feature Flag models
    admin_site.register(FeatureFlag, FeatureFlagAdmin)
    admin_site.register(FeatureFlagAuditLog, FeatureFlagAuditLogAdmin)

    # Register Classification Job models
    admin_site.register(ClassificationJob, ClassificationJobAdmin)

    # Register AFM Scoring models
    from core.models.afm_entity_stats import AFMEntityStats
    from core.models.afm_scoring import AFMEntityScore, AFMScoringConfig
    from core.models.afm_scoring_job import AFMScoringJob
    from core.models.entities import AFMEntity

    admin_site.register(AFMEntityStats, AFMEntityStatsAdmin)
    admin_site.register(AFMEntity, AFMEntityAdmin)
    admin_site.register(AFMScoringConfig, AFMScoringConfigAdmin)
    admin_site.register(AFMEntityScore, AFMEntityScoreAdmin)
    admin_site.register(AFMScoringJob, AFMScoringJobAdmin)

    # Note: SearchSuggestion uses custom manager interface, not default admin
    admin_site.register(NotificationBatchDecision, NotificationBatchDecisionAdmin)

    # Register django-celery-beat models for periodic task management
    from django_celery_beat.admin import (
        ClockedScheduleAdmin,
        CrontabScheduleAdmin,
        IntervalScheduleAdmin,
        PeriodicTaskAdmin,
        SolarScheduleAdmin,
    )
    from django_celery_beat.models import (
        ClockedSchedule,
        CrontabSchedule,
        IntervalSchedule,
        PeriodicTask,
        SolarSchedule,
    )

    admin_site.register(PeriodicTask, PeriodicTaskAdmin)
    admin_site.register(CrontabSchedule, CrontabScheduleAdmin)
    admin_site.register(IntervalSchedule, IntervalScheduleAdmin)
    admin_site.register(ClockedSchedule, ClockedScheduleAdmin)
    admin_site.register(SolarSchedule, SolarScheduleAdmin)


# Auto-register models when module is imported
register_all_models()
