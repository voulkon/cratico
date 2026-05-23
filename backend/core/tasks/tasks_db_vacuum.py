"""
Celery tasks for admin maintenance operations.
"""

import time

from celery import shared_task
from django.db import connection
from loguru import logger


@shared_task(bind=True, name="admin.vacuum_table")
def vacuum_table_task(self, table_name: str, full: bool = False, analyze: bool = True):
    """
    Run VACUUM on a specific table.

    Args:
        table_name: Name of the table to vacuum
        full: If True, run VACUUM FULL (locks table, reclaims space)
        analyze: If True, also run ANALYZE to update statistics

    Returns:
        dict with status, duration, and any errors
    """
    vacuum_type = "VACUUM FULL" if full else "VACUUM"
    command = vacuum_type

    if analyze:
        command += " ANALYZE"

    logger.info(f"Starting {command} on table: {table_name}")

    # Update task state
    self.update_state(
        state="STARTED",
        meta={"table": table_name, "vacuum_type": vacuum_type, "status": "Running..."},
    )

    start_time = time.time()

    try:
        # VACUUM cannot run inside a transaction block
        # Close any existing transaction and ensure we're in autocommit mode
        connection.close()
        connection.ensure_connection()
        connection.set_autocommit(True)

        with connection.cursor() as cursor:
            # Sanitize table name to prevent SQL injection
            # Only allow alphanumeric, underscore, and dot (for schema.table)
            if not all(c.isalnum() or c in ("_", ".") for c in table_name):
                raise ValueError(f"Invalid table name: {table_name}")

            # Execute VACUUM
            sql = f"{command} {table_name}"
            logger.info(f"Executing: {sql}")
            cursor.execute(sql)

            elapsed = time.time() - start_time

            result = {
                "status": "success",
                "table": table_name,
                "vacuum_type": vacuum_type,
                "duration_seconds": round(elapsed, 2),
                "message": f"{command} completed successfully in {elapsed:.1f} seconds",
            }

            logger.info(f"Completed {command} on {table_name} in {elapsed:.1f}s")
            return result

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"VACUUM failed on {table_name}: {error_msg}")

        return {
            "status": "error",
            "table": table_name,
            "vacuum_type": vacuum_type,
            "duration_seconds": round(elapsed, 2),
            "error": error_msg,
            "message": f"VACUUM failed: {error_msg}",
        }


@shared_task(bind=True, name="admin.vacuum_multiple_tables")
def vacuum_multiple_tables_task(
    self, tables: list, full: bool = False, analyze: bool = True
):
    """
    Run VACUUM on multiple tables.

    Args:
        tables: List of table names to vacuum
        full: If True, run VACUUM FULL (locks tables, reclaims space)
        analyze: If True, also run ANALYZE to update statistics

    Returns:
        dict with results for each table
    """
    vacuum_type = "VACUUM FULL" if full else "VACUUM"
    logger.info(f"Starting {vacuum_type} on {len(tables)} tables")

    results = {"total": len(tables), "successful": 0, "failed": 0, "tables": []}

    for idx, table_name in enumerate(tables, 1):
        # Update progress
        self.update_state(
            state="PROGRESS",
            meta={
                "current": idx,
                "total": len(tables),
                "table": table_name,
                "status": f"Processing {idx}/{len(tables)}: {table_name}",
            },
        )

        # Run VACUUM on this table
        result = vacuum_table_task(table_name, full=full, analyze=analyze)
        results["tables"].append(result)

        if result["status"] == "success":
            results["successful"] += 1
        else:
            results["failed"] += 1

    logger.info(
        f"Completed batch VACUUM: {results['successful']} successful, "
        f"{results['failed']} failed"
    )

    return results
