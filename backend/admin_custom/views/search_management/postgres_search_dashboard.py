"""
PostgreSQL Search Management Dashboard

Admin interface for managing PostgreSQL full-text search infrastructure:
- View status of feature flags, triggers, and indexes
- Execute management commands (backfill, cleanup, enable/disable) as async Celery tasks
- Monitor disk usage and record counts
- Safe execution with confirmation dialogs
"""

import json

from celery.result import AsyncResult
from core.services.feature_flag_service import feature_flags
from core.tasks.tasks_search_management import (
    backfill_search_vectors_task,
    cleanup_search_vectors_task,
    manage_postgres_search_task,
)
from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from loguru import logger


@staff_member_required
def postgres_search_dashboard(request):
    """Main dashboard for PostgreSQL search management"""

    # Get aggregate status for all models
    all_models_status = _get_all_models_status()

    # Get feature flag status
    opensearch_enabled = feature_flags.is_enabled("INDEX_THE_OPENSEARCH")
    postgres_enabled = feature_flags.is_enabled("INDEX_THE_POSTGRES")

    # Calculate aggregate summary statistics
    total_records = all_models_status["total_count"]
    total_indexed = all_models_status["indexed_count"]
    total_null = all_models_status["null_count"]

    # Calculate estimated space usage
    total_index_size_gb = all_models_status["total_index_size_gb"]

    # Estimate search_vector data size (rough: ~7GB for 500k DocumentExtraction records, less for others)
    estimated_vector_size_gb = all_models_status["estimated_vector_size_gb"]
    total_search_size_gb = total_index_size_gb + estimated_vector_size_gb

    context = {
        "title": "PostgreSQL Search Management",
        "all_models_status": all_models_status,
        "opensearch_enabled": opensearch_enabled,
        "postgres_enabled": postgres_enabled,
        "summary": {
            "total_records": total_records,
            "total_indexed": total_indexed,
            "total_null": total_null,
            "index_size_gb": round(total_index_size_gb, 2),
            "estimated_vector_size_gb": round(estimated_vector_size_gb, 2),
            "total_search_size_gb": round(total_search_size_gb, 2),
            "indexing_percentage": round(
                (total_indexed / total_records * 100) if total_records > 0 else 0, 1
            ),
        },
        # Workflow recommendations
        "workflows": _get_workflow_recommendations(
            opensearch_enabled, postgres_enabled, all_models_status
        ),
    }

    return render(request, "admin/postgres_search_dashboard.html", context)


@staff_member_required
def execute_search_command(request):
    """Execute a PostgreSQL search management command via AJAX as async Celery task"""

    logger.info(
        f"execute_search_command called - Method: {request.method}, Body: {request.body[:200] if request.body else 'empty'}"
    )

    if request.method != "POST":
        logger.warning(f"Invalid method: {request.method}")
        return JsonResponse({"success": False, "error": "POST required"}, status=405)

    try:
        data = json.loads(request.body)
        logger.info(f"Parsed data: {data}")

        command_type = data.get("command")
        model_scope = data.get("model_scope", "all")  # 'all', 'extraction', or 'others'
        options = data.get("options", {})

        logger.info(
            f"Command: {command_type}, Model Scope: {model_scope}, Options: {options}"
        )

        # Validate command type
        valid_commands = [
            "backfill_search_vectors",
            "cleanup_search_vectors",
            "disable_trigger",
            "enable_trigger",
            "drop_index",
            "create_index",
            "disable_all",
            "enable_all",
            "check_status",
        ]

        if command_type not in valid_commands:
            logger.error(f"Invalid command: {command_type}")
            return JsonResponse(
                {"success": False, "error": f"Invalid command: {command_type}"},
                status=400,
            )

        # Execute the command as async task (or synchronously for quick operations)
        result = _execute_command(command_type, model_scope, options)
        logger.info(f"Command result: {result}")

        return JsonResponse(result)

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}", exc_info=True)
        return JsonResponse(
            {"success": False, "error": f"Invalid JSON: {str(e)}"}, status=400
        )
    except Exception as e:
        logger.error(f"Error executing search command: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": str(e)}, status=500)


@staff_member_required
def search_task_status(request, task_id):
    """Check the status of an async search management task"""

    try:
        task_result = AsyncResult(task_id)

        if task_result.ready():
            # Task completed
            result = task_result.get()
            return JsonResponse(
                {
                    "ready": True,
                    "success": result.get("status") == "success",
                    "result": result,
                }
            )
        else:
            # Task still running
            state = task_result.state
            info = task_result.info or {}

            return JsonResponse(
                {
                    "ready": False,
                    "state": state,
                    "status": info.get("status", "Running..."),
                    "meta": info,
                }
            )

    except Exception as e:
        logger.error(f"Error checking task status: {e}", exc_info=True)
        return JsonResponse(
            {"ready": True, "success": False, "error": str(e)}, status=500
        )


def _get_all_models_status():
    """Get aggregate status for all models with search_vector fields"""

    # All models with search_vector fields
    MODELS = {
        "extraction": {
            "table": "core_documentextraction",
            "trigger": "document_extraction_search_vector_update",
            "index": "core_docume_search__d7ddb0_gin",
            "weight": 1.0,  # Weight for size estimation (extraction is largest)
        },
        "afmentity": {
            "table": "core_afmentity",
            "trigger": "afmentity_search_vector_update",
            "index": "core_afmentity_search_vector_idx",
            "weight": 0.01,
        },
        "organization": {
            "table": "core_organization",
            "trigger": "organization_search_vector_update",
            "index": "core_organization_search_vector_idx",
            "weight": 0.05,
        },
        "unit": {
            "table": "core_unit",
            "trigger": "unit_search_vector_update",
            "index": "core_unit_search_vector_idx",
            "weight": 0.05,
        },
        "signer": {
            "table": "core_signer",
            "trigger": "signer_search_vector_update",
            "index": "core_signer_search_vector_idx",
            "weight": 0.05,
        },
        "company": {
            "table": "companies",
            "trigger": "companies_search_vector_update",
            "index": "companies_search_vector_idx",
            "weight": 0.1,
        },
        "companyperson": {
            "table": "company_persons",
            "trigger": "company_person_search_vector_update",
            "index": "company_persons_search_vector_idx",
            "weight": 0.05,
        },
    }

    # Aggregate counters
    total_count = 0
    indexed_count = 0
    null_count = 0
    total_index_size_bytes = 0
    estimated_vector_size_gb = 0

    # Track trigger and index status
    all_triggers_enabled = True
    all_triggers_disabled = True
    all_indexes_exist = True
    all_indexes_missing = True

    model_details = []

    with connection.cursor() as cursor:
        for model_name, config in MODELS.items():
            table = config["table"]
            trigger = config["trigger"]
            index = config["index"]
            weight = config["weight"]

            # Get record counts
            quoted_table = connection.ops.quote_name(table)
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE search_vector IS NULL) as null_count,
                    COUNT(*) FILTER (WHERE search_vector IS NOT NULL) as indexed_count,
                    COUNT(*) as total_count
                FROM {quoted_table}
            """,  # nosec: B608 - Using Django's quote_name() for identifier safety
            )
            counts = cursor.fetchone()

            total_count += counts[2]
            indexed_count += counts[1]
            null_count += counts[0]

            # Get trigger status
            cursor.execute(
                """
                SELECT
                    CASE tgenabled
                        WHEN 'O' THEN 'enabled'
                        WHEN 'D' THEN 'disabled'
                        ELSE 'unknown'
                    END as status
                FROM pg_trigger
                WHERE tgname = %s
            """,
                [trigger],
            )
            trigger_row = cursor.fetchone()
            trigger_status = trigger_row[0] if trigger_row else "not_found"

            if trigger_status != "enabled":
                all_triggers_enabled = False
            if trigger_status != "disabled":
                all_triggers_disabled = False

            # Get index status and size
            cursor.execute(
                """
                SELECT
                    pg_relation_size(pg_class.oid) as size_bytes,
                    pg_size_pretty(pg_relation_size(pg_class.oid)) as size_pretty
                FROM pg_indexes
                JOIN pg_class ON pg_class.relname = pg_indexes.indexname
                WHERE indexname = %s
            """,
                [index],
            )
            index_row = cursor.fetchone()

            if index_row:
                index_status = "exists"
                index_size_bytes = index_row[0]
                total_index_size_bytes += index_size_bytes
                all_indexes_missing = False
            else:
                index_status = "missing"
                index_size_bytes = 0
                all_indexes_exist = False

            # Estimate search_vector data size based on indexed records and weight
            # Base: ~7GB for 500k DocumentExtraction records, scaled by weight for other models
            model_vector_size_gb = (
                (counts[1] / 500000) * 7 * weight if counts[1] > 0 else 0
            )
            estimated_vector_size_gb += model_vector_size_gb

            model_details.append(
                {
                    "name": model_name,
                    "table": table,
                    "null_count": counts[0],
                    "indexed_count": counts[1],
                    "total_count": counts[2],
                    "trigger_status": trigger_status,
                    "index_status": index_status,
                    "index_size_bytes": index_size_bytes,
                }
            )

    # Determine overall trigger status
    if all_triggers_enabled:
        trigger_status = "enabled"
    elif all_triggers_disabled:
        trigger_status = "disabled"
    else:
        trigger_status = "mixed"

    # Determine overall index status
    if all_indexes_exist:
        index_status = "exists"
    elif all_indexes_missing:
        index_status = "missing"
    else:
        index_status = "partial"

    total_index_size_gb = total_index_size_bytes / (1024**3)

    return {
        "total_count": total_count,
        "indexed_count": indexed_count,
        "null_count": null_count,
        "indexing_percentage": round(
            (indexed_count / total_count * 100) if total_count > 0 else 0, 1
        ),
        "trigger_status": trigger_status,
        "index_status": index_status,
        "total_index_size_gb": total_index_size_gb,
        "estimated_vector_size_gb": estimated_vector_size_gb,
        "model_details": model_details,
        "model_count": len(MODELS),
    }


def _get_model_status(model_name):
    """Get detailed status for a specific model"""

    # Only extraction model supported
    table = "core_documentextraction"
    trigger = "document_extraction_search_vector_update"
    index = "core_docume_search__d7ddb0_gin"

    with connection.cursor() as cursor:
        # Get record counts
        quoted_table = connection.ops.quote_name(table)
        cursor.execute(
            f"""
            SELECT
                COUNT(*) FILTER (WHERE search_vector IS NULL) as null_count,
                COUNT(*) FILTER (WHERE search_vector IS NOT NULL) as indexed_count,
                COUNT(*) as total_count
            FROM {quoted_table}
        """,  # nosec: B608 - Using Django's quote_name() for identifier safety
        )
        counts = cursor.fetchone()

        # Get trigger status
        cursor.execute(
            """
            SELECT
                CASE tgenabled
                    WHEN 'O' THEN 'enabled'
                    WHEN 'D' THEN 'disabled'
                    ELSE 'unknown'
                END as status
            FROM pg_trigger
            WHERE tgname = %s
        """,
            [trigger],
        )
        trigger_row = cursor.fetchone()
        trigger_status = trigger_row[0] if trigger_row else "not_found"

        # Get index status and size
        cursor.execute(
            """
            SELECT
                pg_relation_size(pg_class.oid) as size_bytes,
                pg_size_pretty(pg_relation_size(pg_class.oid)) as size_pretty
            FROM pg_indexes
            JOIN pg_class ON pg_class.relname = pg_indexes.indexname
            WHERE indexname = %s
        """,
            [index],
        )
        index_row = cursor.fetchone()

        if index_row:
            index_status = "exists"
            index_size_bytes = index_row[0]
            index_size = index_row[1]
        else:
            index_status = "missing"
            index_size_bytes = 0
            index_size = "N/A"

        # Get table size
        cursor.execute(
            f"""
            SELECT
                pg_size_pretty(pg_total_relation_size(%s)) as total_size,
                pg_size_pretty(pg_relation_size(%s)) as table_size
        """,
            [table, table],
        )
        sizes = cursor.fetchone()

    return {
        "model": model_name,
        "table": table,
        "trigger_name": trigger,
        "index_name": index,
        "null_count": counts[0],
        "indexed_count": counts[1],
        "total_count": counts[2],
        "indexing_percentage": round(
            (counts[1] / counts[2] * 100) if counts[2] > 0 else 0, 1
        ),
        "trigger_status": trigger_status,
        "index_status": index_status,
        "index_size": index_size,
        "index_size_bytes": index_size_bytes,
        "total_table_size": sizes[0],
        "main_table_size": sizes[1],
    }


def _get_workflow_recommendations(
    opensearch_enabled, postgres_enabled, all_models_status
):
    """Generate workflow recommendations based on current state"""

    workflows = []

    # Check if both search methods are disabled
    if not opensearch_enabled and not postgres_enabled:
        workflows.append(
            {
                "title": "[WARN]️ No Search Available",
                "type": "warning",
                "description": "Both OpenSearch and PostgreSQL search are disabled. Document content search is unavailable.",
                "actions": [
                    {
                        "label": "Enable PostgreSQL Search",
                        "command": "enable_all",
                        "style": "primary",
                    }
                ],
            }
        )

    # Check if triggers are enabled but indexes are missing
    trigger_status = all_models_status["trigger_status"]
    index_status = all_models_status["index_status"]

    if trigger_status in ["enabled", "mixed"] and index_status in [
        "missing",
        "partial",
    ]:
        workflows.append(
            {
                "title": "[WARN]️ Triggers Without Indexes",
                "type": "warning",
                "description": "Some or all triggers are enabled but indexes are missing. Searches will be slow.",
                "actions": [
                    {
                        "label": "Create Indexes",
                        "command": "create_index",
                        "style": "primary",
                    }
                ],
            }
        )

    # Check if there are unindexed records
    total_null = all_models_status["null_count"]
    if total_null > 0 and postgres_enabled:
        workflows.append(
            {
                "title": "[RETRY] Backfill Needed",
                "type": "info",
                "description": f'{total_null:,} records across {all_models_status["model_count"]} models need search_vector backfill for full-text search.',
                "actions": [
                    {
                        "label": "Backfill Search Vectors",
                        "command": "backfill_search_vectors",
                        "style": "primary",
                    }
                ],
            }
        )

    # Suggest cleanup if PostgreSQL search is disabled and vectors exist
    total_indexed = all_models_status["indexed_count"]
    estimated_size = (
        all_models_status["total_index_size_gb"]
        + all_models_status["estimated_vector_size_gb"]
    )
    if not postgres_enabled and total_indexed > 0:
        workflows.append(
            {
                "title": "[SAVE] Reclaim Disk Space",
                "type": "info",
                "description": f"PostgreSQL search is disabled but {total_indexed:,} records still have search_vector data (~{estimated_size:.1f}GB).",
                "actions": [
                    {
                        "label": "Cleanup & Reclaim Space",
                        "command": "cleanup_search_vectors",
                        "style": "warning",
                    }
                ],
            }
        )

    # Recommend disabling if not being used
    if postgres_enabled and opensearch_enabled:
        workflows.append(
            {
                "title": "[INFO] Optimization Opportunity",
                "type": "suggestion",
                "description": f"Both search engines are enabled. If OpenSearch is your primary search, you can disable PostgreSQL search to save ~{estimated_size:.1f}GB.",
                "actions": [
                    {
                        "label": "Disable PostgreSQL Search",
                        "command": "disable_all",
                        "style": "secondary",
                    }
                ],
            }
        )

    return workflows


def _execute_command(command_type, model_scope, options):
    """Execute a management command (async for long-running ops, sync for quick ones)"""

    try:
        if command_type == "check_status":
            # Quick status check - synchronous
            all_models_status = _get_all_models_status()
            return {
                "success": True,
                "message": "Status refreshed",
                "data": {
                    "all_models": all_models_status,
                },
            }

        elif command_type == "backfill_search_vectors":
            # Long-running operation - launch async task
            task = backfill_search_vectors_task.delay(
                batch_size=options.get("batch_size", 1000),
                only_null=options.get("only_null", False),
                model_scope=model_scope,
            )

            # Determine description based on model_scope
            scope_desc = {
                "all": "all models",
                "extraction": "extraction model",
                "others": "other 6 models",
            }.get(model_scope, model_scope)

            return {
                "success": True,
                "async": True,
                "task_id": task.id,
                "message": f"Backfill task started for {scope_desc} (ID: {task.id})",
            }

        elif command_type == "cleanup_search_vectors":
            # Long-running operation - launch async task
            task = cleanup_search_vectors_task.delay(
                batch_size=options.get("batch_size", 5000),
                no_vacuum=options.get("no_vacuum", False),
                vacuum_full=options.get("vacuum_full", False),
                model_scope=model_scope,
            )

            scope_desc = {
                "all": "all models",
                "extraction": "extraction model",
                "others": "other 6 models",
            }.get(model_scope, model_scope)

            return {
                "success": True,
                "async": True,
                "task_id": task.id,
                "message": f"Cleanup task started for {scope_desc} (ID: {task.id})",
            }

        elif command_type in [
            "disable_trigger",
            "enable_trigger",
            "drop_index",
            "create_index",
        ]:
            # Individual trigger/index operations - can be async
            action = command_type.replace("_", "-")

            task = manage_postgres_search_task.delay(
                action=action, model_scope=model_scope
            )

            scope_desc = {
                "all": "all models",
                "extraction": "extraction model",
                "others": "other 6 models",
            }.get(model_scope, model_scope)

            return {
                "success": True,
                "async": True,
                "task_id": task.id,
                "message": f"{command_type} task started for {scope_desc} (ID: {task.id})",
            }

        elif command_type in ["disable_all", "enable_all"]:
            # Complete workflows - async
            action = command_type.replace("_", "-")

            task = manage_postgres_search_task.delay(
                action=action, model_scope=model_scope
            )

            scope_desc = {
                "all": "all models",
                "extraction": "extraction model",
                "others": "other 6 models",
            }.get(model_scope, model_scope)

            return {
                "success": True,
                "async": True,
                "task_id": task.id,
                "message": f"{command_type} task started for {scope_desc} (ID: {task.id})",
            }

        return {"success": False, "error": f"Unknown command: {command_type}"}

    except Exception as e:
        logger.error(f"Error executing {command_type}: {e}", exc_info=True)
        return {"success": False, "error": str(e)}
