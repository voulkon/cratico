"""
Database Storage Dashboard

Comprehensive view of PostgreSQL database storage usage:
- Overall database size and stats
- Table sizes (with indexes, TOAST)
- Column storage analysis
- Index sizes
- Row counts
- Bloat estimates
"""

import json

from django.contrib.admin.views.decorators import staff_member_required
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST
from loguru import logger


@staff_member_required
def db_storage_dashboard(request):
    """Main dashboard for database storage analysis - loads minimal data initially"""

    # Only get basic database size - everything else loads on demand
    db_stats = _get_basic_database_stats()

    context = {
        "title": "Database Storage Dashboard",
        "db_stats": db_stats,
    }

    return render(request, "admin/db_storage_dashboard.html", context)


def _get_basic_database_stats():
    """Get only the fastest, most essential database stats (size only)"""
    with connection.cursor() as cursor:
        # Get database size - this is fast
        cursor.execute(
            """
            SELECT
                pg_database.datname,
                pg_size_pretty(pg_database_size(pg_database.datname)) as size_pretty,
                pg_database_size(pg_database.datname) as size_bytes,
                ROUND(pg_database_size(pg_database.datname) / (1024.0 * 1024.0 * 1024.0), 2) as size_gb
            FROM pg_database
            WHERE datname = current_database()
        """
        )
        db_row = cursor.fetchone()

        return {
            "database_name": db_row[0],
            "total_size": db_row[1],
            "total_size_bytes": db_row[2],
            "size_gb": db_row[3],
        }


@staff_member_required
def get_extended_database_stats(request):
    """API endpoint to get extended database statistics"""
    try:
        stats = _get_database_stats()
        return JsonResponse({"status": "success", "data": stats})
    except Exception as e:
        logger.error(f"Error getting extended database stats: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
def get_table_stats(request):
    """API endpoint to get table statistics"""
    try:
        stats = _get_table_stats()
        return JsonResponse({"status": "success", "data": stats})
    except Exception as e:
        logger.error(f"Error getting table stats: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
def get_index_stats(request):
    """API endpoint to get index statistics"""
    try:
        stats = _get_index_stats()
        return JsonResponse({"status": "success", "data": stats})
    except Exception as e:
        logger.error(f"Error getting index stats: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
def get_column_stats(request):
    """API endpoint to get column statistics"""
    try:
        stats = _get_column_stats()
        return JsonResponse({"status": "success", "data": stats})
    except Exception as e:
        logger.error(f"Error getting column stats: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
def get_bloat_stats(request):
    """API endpoint to get bloat estimates"""
    try:
        stats = _get_bloat_estimates()
        return JsonResponse({"status": "success", "data": stats})
    except Exception as e:
        logger.error(f"Error getting bloat stats: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


def _get_database_stats():
    """Get overall database statistics"""
    with connection.cursor() as cursor:
        # Get database size
        cursor.execute(
            """
            SELECT
                pg_database.datname,
                pg_size_pretty(pg_database_size(pg_database.datname)) as size_pretty,
                pg_database_size(pg_database.datname) as size_bytes
            FROM pg_database
            WHERE datname = current_database()
        """
        )
        db_row = cursor.fetchone()

        # Get table count
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'public'
            AND table_type = 'BASE TABLE'
        """
        )
        table_count = cursor.fetchone()[0]

        # Get index count
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM pg_indexes
            WHERE schemaname = 'public'
        """
        )
        index_count = cursor.fetchone()[0]

        # Get total rows across all tables
        cursor.execute(
            """
            SELECT
                SUM(n_live_tup) as total_rows,
                SUM(n_dead_tup) as dead_rows
            FROM pg_stat_user_tables
        """
        )
        row_stats = cursor.fetchone()

        # Get total index size
        cursor.execute(
            """
            SELECT pg_size_pretty(SUM(pg_relation_size(indexrelid))) as total_index_size
            FROM pg_index
            JOIN pg_class ON pg_class.oid = pg_index.indexrelid
            WHERE pg_class.relnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
        """
        )
        total_index_size = cursor.fetchone()[0]

        return {
            "database_name": db_row[0],
            "total_size": db_row[1],
            "total_size_bytes": db_row[2],
            "table_count": table_count,
            "index_count": index_count,
            "total_rows": row_stats[0] or 0,
            "dead_rows": row_stats[1] or 0,
            "total_index_size": total_index_size,
        }


def _get_table_stats():
    """Get detailed statistics for each table"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                schemaname,
                relname as tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as total_size,
                pg_size_pretty(pg_relation_size(schemaname||'.'||relname)) as table_size,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname) - pg_relation_size(schemaname||'.'||relname)) as external_size,
                pg_total_relation_size(schemaname||'.'||relname) as total_bytes,
                pg_relation_size(schemaname||'.'||relname) as table_bytes,
                n_live_tup as row_count,
                n_dead_tup as dead_rows,
                CASE
                    WHEN n_live_tup > 0
                    THEN round(100.0 * n_dead_tup / n_live_tup, 2)
                    ELSE 0
                END as dead_ratio
            FROM pg_stat_user_tables
            ORDER BY pg_total_relation_size(schemaname||'.'||relname) DESC
            LIMIT 50
        """
        )

        tables = []
        for row in cursor.fetchall():
            tables.append(
                {
                    "schema": row[0],
                    "name": row[1],
                    "total_size": row[2],
                    "table_size": row[3],
                    "external_size": row[4],  # TOAST + indexes
                    "total_bytes": row[5],
                    "table_bytes": row[6],
                    "row_count": row[7] or 0,
                    "dead_rows": row[8] or 0,
                    "dead_ratio": row[9] or 0,
                }
            )

        return tables


def _get_index_stats():
    """Get index statistics"""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                schemaname,
                relname as tablename,
                indexrelname as indexname,
                pg_size_pretty(pg_relation_size(pg_stat_user_indexes.indexrelid)) as index_size,
                pg_relation_size(pg_stat_user_indexes.indexrelid) as size_bytes,
                idx_scan as scans,
                idx_tup_read as tuples_read,
                idx_tup_fetch as tuples_fetched
            FROM pg_stat_user_indexes
            JOIN pg_index ON pg_stat_user_indexes.indexrelid = pg_index.indexrelid
            ORDER BY pg_relation_size(pg_stat_user_indexes.indexrelid) DESC
            LIMIT 50
        """
        )

        indexes = []
        for row in cursor.fetchall():
            indexes.append(
                {
                    "schema": row[0],
                    "table": row[1],
                    "name": row[2],
                    "size": row[3],
                    "size_bytes": row[4],
                    "scans": row[5] or 0,
                    "tuples_read": row[6] or 0,
                    "tuples_fetched": row[7] or 0,
                }
            )

        return indexes


def _get_column_stats():
    """Get column storage statistics for key tables"""

    # Focus on tables that are likely to have large columns
    key_tables = [
        "core_documentextraction",
        "core_documentpage",
        "core_document",
    ]

    column_data = {}

    with connection.cursor() as cursor:
        for table in key_tables:
            # Safely quote table name to prevent SQL injection
            quoted_table = connection.ops.quote_name(table)

            # Get column stats
            cursor.execute(
                f"""
                SELECT
                    attname as column_name,
                    format_type(atttypid, atttypmod) as data_type,
                    CASE
                        WHEN atttypid = ANY (ARRAY[25, 1043, 1042]::oid[]) THEN 'text'  -- text, varchar, char
                        WHEN atttypid = 3614 THEN 'tsvector'  -- tsvector
                        WHEN atttypid = 17 THEN 'bytea'  -- bytea
                        ELSE 'other'
                    END as type_category,
                    attnotnull as not_null,
                    attnum as position
                FROM pg_attribute
                JOIN pg_class ON pg_attribute.attrelid = pg_class.oid
                JOIN pg_namespace ON pg_class.relnamespace = pg_namespace.oid
                WHERE pg_namespace.nspname = 'public'
                AND pg_class.relname = %s
                AND attnum > 0
                AND NOT attisdropped
                ORDER BY attnum
            """,
                [
                    quoted_table
                ],  # nosec: B608 - Using Django's quote_name() for identifier safety
            )

            columns = []
            for row in cursor.fetchall():
                col_name = row[0]
                col_type = row[1]
                col_category = row[2]

                # Estimate size for TOAST-able columns
                size_estimate = None
                if col_category in ("text", "tsvector", "bytea"):
                    # Safely quote column name to prevent SQL injection
                    quoted_col = connection.ops.quote_name(col_name)
                    cursor.execute(
                        f"""
                        SELECT
                            COUNT(*) FILTER (WHERE {quoted_col} IS NOT NULL) as non_null_count,
                            AVG(LENGTH({quoted_col}::text)) as avg_length,
                            MAX(LENGTH({quoted_col}::text)) as max_length,
                            MIN(LENGTH({quoted_col}::text)) FILTER (WHERE {quoted_col} IS NOT NULL) as min_length
                        FROM {quoted_table}
                    """,  # nosec: B608 - Using Django's quote_name() for identifier safety
                    )
                    stats = cursor.fetchone()
                    if stats:
                        non_null = stats[0] or 0
                        avg_len = stats[1] or 0
                        max_len = stats[2] or 0
                        min_len = stats[3] or 0

                        # Estimate total size in MB
                        estimated_mb = (
                            (non_null * avg_len) / (1024 * 1024) if avg_len else 0
                        )

                        size_estimate = {
                            "non_null_count": non_null,
                            "avg_length": round(avg_len, 2) if avg_len else 0,
                            "max_length": max_len,
                            "min_length": min_len,
                            "estimated_mb": round(estimated_mb, 2),
                        }

                columns.append(
                    {
                        "name": col_name,
                        "type": col_type,
                        "category": col_category,
                        "not_null": row[3],
                        "position": row[4],
                        "size_estimate": size_estimate,
                    }
                )

            column_data[table] = columns

    return column_data


def _get_bloat_estimates():
    """Estimate table and index bloat"""
    with connection.cursor() as cursor:
        # Table bloat estimation
        cursor.execute(
            """
            SELECT
                schemaname,
                relname as tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as total_size,
                round(100.0 * n_dead_tup / GREATEST(n_live_tup, 1), 2) as bloat_pct,
                pg_size_pretty(CAST(
                    pg_total_relation_size(schemaname||'.'||relname) *
                    (n_dead_tup::numeric / GREATEST(n_live_tup + n_dead_tup, 1))
                    AS bigint
                )) as estimated_bloat_size,
                last_vacuum,
                last_autovacuum
            FROM pg_stat_user_tables
            WHERE n_live_tup > 0
            ORDER BY n_dead_tup DESC
            LIMIT 20
        """
        )

        bloat_tables = []
        for row in cursor.fetchall():
            bloat_tables.append(
                {
                    "schema": row[0],
                    "table": row[1],
                    "total_size": row[2],
                    "bloat_pct": row[3] or 0,
                    "estimated_bloat": row[4],
                    "last_vacuum": row[5],
                    "last_autovacuum": row[6],
                }
            )

        return {
            "tables": bloat_tables,
        }


@staff_member_required
@require_POST
def run_vacuum(request):
    """
    Handle VACUUM operations via AJAX.

    POST data:
        - table: Table name to vacuum
        - vacuum_type: 'standard' or 'full'
        - analyze: boolean, whether to include ANALYZE
    """
    try:
        data = json.loads(request.body)
        table_name = data.get("table")
        vacuum_type = data.get("vacuum_type", "standard")
        analyze = data.get("analyze", True)

        if not table_name:
            return JsonResponse(
                {"status": "error", "message": "Table name is required"}, status=400
            )

        # Validate table exists
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name = %s
            """,
                [table_name],
            )

            if cursor.fetchone()[0] == 0:
                return JsonResponse(
                    {"status": "error", "message": f"Table {table_name} not found"},
                    status=404,
                )

        # Import task
        from backend.core.tasks.tasks_db_vacuum import vacuum_table_task

        # Get table size for time estimate
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT pg_size_pretty(pg_total_relation_size(%s))
            """,
                [f"public.{table_name}"],
            )
            size = cursor.fetchone()[0]

        # Launch async task
        full = vacuum_type == "full"
        task = vacuum_table_task.delay(
            table_name=f"public.{table_name}", full=full, analyze=analyze
        )

        # Estimate time based on size and type
        estimate = _estimate_vacuum_time(size, full)

        return JsonResponse(
            {
                "status": "started",
                "task_id": task.id,
                "table": table_name,
                "vacuum_type": vacuum_type,
                "estimated_time": estimate,
                "message": f'VACUUM {"FULL " if full else ""}started on {table_name}',
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON data"}, status=400
        )
    except Exception as e:
        logger.error(f"Error starting VACUUM: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
@require_POST
def run_vacuum_bloated(request):
    """
    Run VACUUM on all tables with bloat > threshold.

    POST data:
        - threshold: Bloat percentage threshold (default: 10)
        - vacuum_type: 'standard' or 'full'
    """
    try:
        data = json.loads(request.body)
        threshold = float(data.get("threshold", 10))
        vacuum_type = data.get("vacuum_type", "standard")

        # Get bloated tables
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    relname as tablename,
                    round(100.0 * n_dead_tup / GREATEST(n_live_tup, 1), 2) as bloat_pct
                FROM pg_stat_user_tables
                WHERE n_live_tup > 0
                AND n_dead_tup::float / GREATEST(n_live_tup, 1) > %s / 100.0
                ORDER BY n_dead_tup DESC
            """,
                [threshold],
            )

            bloated_tables = [f"public.{row[0]}" for row in cursor.fetchall()]

        if not bloated_tables:
            return JsonResponse(
                {
                    "status": "success",
                    "message": f"No tables found with bloat > {threshold}%",
                    "count": 0,
                }
            )

        # Import task
        from backend.core.tasks.tasks_db_vacuum import vacuum_multiple_tables_task

        # Launch async task
        full = vacuum_type == "full"
        task = vacuum_multiple_tables_task.delay(
            tables=bloated_tables, full=full, analyze=True
        )

        return JsonResponse(
            {
                "status": "started",
                "task_id": task.id,
                "table_count": len(bloated_tables),
                "tables": bloated_tables,
                "vacuum_type": vacuum_type,
                "threshold": threshold,
                "message": f'Started VACUUM {"FULL " if full else ""}on {len(bloated_tables)} bloated tables',
            }
        )

    except json.JSONDecodeError:
        return JsonResponse(
            {"status": "error", "message": "Invalid JSON data"}, status=400
        )
    except Exception as e:
        logger.error(f"Error starting batch VACUUM: {e}")
        return JsonResponse({"status": "error", "message": str(e)}, status=500)


@staff_member_required
def vacuum_task_status(request, task_id):
    """
    Check the status of a VACUUM task.

    GET /admin/db-storage/vacuum/status/<task_id>/
    """
    from celery.result import AsyncResult

    try:
        task = AsyncResult(task_id)

        if task.state == "PENDING":
            response = {"state": task.state, "status": "Task is pending..."}
        elif task.state == "STARTED":
            response = {
                "state": task.state,
                "status": "Task has started...",
                **task.info,
            }
        elif task.state == "PROGRESS":
            response = {"state": task.state, **task.info}
        elif task.state == "SUCCESS":
            response = {"state": task.state, "result": task.result}
        elif task.state == "FAILURE":
            response = {
                "state": task.state,
                "status": str(task.info),
                "error": str(task.info),
            }
        else:
            response = {"state": task.state, "status": str(task.info)}

        return JsonResponse(response)

    except Exception as e:
        logger.error(f"Error checking task status: {e}")
        return JsonResponse({"state": "ERROR", "error": str(e)}, status=500)


def _estimate_vacuum_time(size_str: str, full: bool = False) -> str:
    """
    Estimate VACUUM duration based on table size.

    Args:
        size_str: Size string like "1234 MB" or "5 GB"
        full: If True, estimate for VACUUM FULL

    Returns:
        Human-readable time estimate
    """
    try:
        # Parse size
        parts = size_str.split()
        if len(parts) != 2:
            return "Unknown"

        value = float(parts[0])
        unit = parts[1].upper()

        # Convert to MB
        if unit == "KB":
            mb = value / 1024
        elif unit == "MB":
            mb = value
        elif unit == "GB":
            mb = value * 1024
        elif unit == "TB":
            mb = value * 1024 * 1024
        else:
            return "Unknown"

        # Estimate based on size
        if full:
            # VACUUM FULL is much slower
            if mb < 100:
                return "< 1 minute"
            elif mb < 1000:
                return "1-5 minutes"
            elif mb < 5000:
                return "5-15 minutes"
            elif mb < 10000:
                return "15-30 minutes"
            else:
                return "30+ minutes (may lock table)"
        else:
            # Regular VACUUM is faster
            if mb < 500:
                return "< 30 seconds"
            elif mb < 2000:
                return "30 seconds - 2 minutes"
            elif mb < 10000:
                return "2-10 minutes"
            else:
                return "10+ minutes"

    except Exception:
        return "Unknown"
