"""
Import all tasks to maintain backward compatibility
"""

from .afm_entity_stats_tasks import recompute_all_entity_stats
from .health_check_tasks import (
    auto_fix_simple_issues,
    backfill_health_checks_for_import_job,
    check_recent_decisions_health,
    check_single_decision_health,
    cleanup_old_health_checks,
    refresh_problematic_decisions,
    retry_failed_decisions_for_import_job,
)
from .tasks_auto_import import (
    auto_daily_import_task,
    find_next_oldest_missing_day,
    trigger_next_backfill,
    trigger_next_company_gemi_batch,
)
from .tasks_backups import create_backup_task, restore_backup_task
from .tasks_data_migration import (
    recompute_issue_date_fields_task,
    recompute_publish_date_fields_task,
)
from .tasks_db_vacuum import vacuum_multiple_tables_task, vacuum_table_task
from .tasks_decisions import (
    collect_results,
    daily_decisions_sync_task,
    fetch_decisions_for_increment,
    import_decisions_task,
    import_ministry_decisions_task,
    process_fetch_period,
    reconcile_daily_counts,
    update_coverage_stats,
)
from .tasks_decisions_import import (
    fetch_daily_decisions_distributed,
    fetch_daily_decisions_to_redis,
    store_decisions_from_pickle,
    store_decisions_from_redis,
)

# Import all tasks from sub-modules
from .tasks_documents import (  # LEGACY: Use run_decision_pipeline_task instead; [TARGET] SINGLE SOURCE OF TRUTH
    collect_batch_results,
    generate_summary_task,
    process_document_batch,
    process_document_task,
    process_document_task_enhanced,
    process_documents_task,
    process_documents_task_enhanced,
    process_scanned_document_task,
    run_decision_pipeline_task,
)
from .tasks_entities import (
    fetch_company_data_for_entities,
    fetch_company_data_for_single_afm,
    process_entities_needing_company_data,
)
from .tasks_import_validation import (
    update_thresholds_from_analysis,
    validate_and_backfill_imports,
    validate_single_day,
)
from .tasks_misc import ping, test_tracing
from .tasks_opensearch import (
    bulk_reindex_missing_documents,
    check_opensearch_sync,
    create_opensearch_backup,
    daily_opensearch_backup,
    index_recent_documents,
    reindex_specific_adas,
)
from .tasks_org_decisions import (
    fetch_all_orgs_decisions,
    fetch_org_decisions_to_pickle,
    store_org_decisions_from_pickle,
)
from .tasks_post_import import (
    post_daily_import_orchestrator, 
    compute_entity_rankings,
    trigger_check_all_subscriptions
    )
from .tasks_periodic_validation import periodic_validation_task
from .tasks_search_management import (
    backfill_search_vectors_batch_task,
    backfill_search_vectors_task,
    cleanup_search_vectors_task,
    manage_postgres_search_task,
)

# This ensures all tasks are available when importing from core.tasks
__all__ = [
    "backfill_search_vectors_batch_task",
    "backfill_search_vectors_task",
    "cleanup_search_vectors_task",
    "manage_postgres_search_task",
    # Auto Import (Autofarming)
    "auto_daily_import_task",
    "trigger_next_backfill",
    "find_next_oldest_missing_day",
    # Auto Company GEMI Import (Virtuous Cycle)
    "trigger_next_company_gemi_batch",
    # Documents
    "process_document_task",
    "process_scanned_document_task",
    "generate_summary_task",
    "process_document_batch",
    "collect_batch_results",
    "process_document_task_enhanced",
    "process_documents_task_enhanced",
    "process_documents_task",
    # Decisions Import (New)
    "fetch_daily_decisions_to_pickle",
    "store_decisions_from_pickle",
    "fetch_daily_decisions_distributed",
    # Decisions (Legacy)
    "fetch_decisions_for_increment",
    "process_fetch_period",
    "collect_results",
    "import_ministry_decisions_task",
    "import_decisions_task",
    "update_coverage_stats",
    "daily_decisions_sync_task",
    "reconcile_daily_counts",
    # OpenSearch
    "index_recent_documents",
    "check_opensearch_sync",
    "create_opensearch_backup",
    "daily_opensearch_backup",
    "bulk_reindex_missing_documents",
    "reindex_specific_adas",
    # Entities
    "fetch_company_data_for_entities",
    "process_entities_needing_company_data",
    # Misc
    "ping",
    "test_tracing",
    # Health Checks
    "check_recent_decisions_health",
    "refresh_problematic_decisions",
    "cleanup_old_health_checks",
    "auto_fix_simple_issues",
    "check_single_decision_health",
    "backfill_health_checks_for_import_job",
    "retry_failed_decisions_for_import_job",
    "fetch_org_decisions_to_pickle",
    "store_org_decisions_from_pickle",
    "fetch_all_orgs_decisions",
    # Import Validation
    "validate_and_backfill_imports",
    "validate_single_day",
    "update_thresholds_from_analysis",
    "periodic_validation_task",
    "vacuum_table_task",
    "vacuum_multiple_tables_task",
    "recompute_all_entity_stats",
    # Data migrations
    "recompute_issue_date_fields_task",
    "recompute_publish_date_fields_task",
    "post_daily_import_orchestrator",
    "compute_entity_rankings",
    "trigger_check_all_subscriptions"
]
