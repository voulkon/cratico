"""
Celery tasks for PostgreSQL search management operations.

These tasks handle long-running search management operations like:
- Backfilling search vectors
- Cleaning up search vectors
- Managing triggers and indexes
"""

import time
from io import StringIO

from celery import shared_task
from django.core.management import call_command
from loguru import logger


@shared_task(bind=True, name="search.backfill_search_vectors")
def backfill_search_vectors_task(
    self, batch_size: int = 1000, only_null: bool = False, model_scope: str = "all"
):
    """
    Backfill search_vector for specified models.

    Args:
        batch_size: Number of records to process per batch
        only_null: If True, only backfill NULL search_vector fields (default: False - backfill all)
        model_scope: Which models to process - 'all', 'extraction', or 'others'

    Returns:
        dict with status, duration, and output
    """
    logger.info(
        f"Starting backfill_search_vectors task: batch_size={batch_size}, model_scope={model_scope}"
    )

    # Update task state
    self.update_state(
        state="STARTED",
        meta={
            "batch_size": batch_size,
            "model_scope": model_scope,
            "status": "Running backfill...",
        },
    )

    start_time = time.time()
    output = StringIO()

    try:
        # Build command arguments based on model_scope
        kwargs = {
            "batch_size": batch_size,
            "only_null": only_null,
            "force": True,
            "stdout": output,
        }

        if model_scope == "extraction":
            kwargs["extraction_only"] = True
        elif model_scope == "others":
            kwargs["others_only"] = True
        # If 'all', no additional flag needed

        call_command("backfill_search_vectors", **kwargs)

        elapsed = time.time() - start_time
        output_text = output.getvalue()

        result = {
            "status": "success",
            "duration_seconds": round(elapsed, 2),
            "output": output_text,
            "message": f"Backfill completed successfully in {elapsed:.1f} seconds",
        }

        logger.info(f"Completed backfill_search_vectors in {elapsed:.1f}s")
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"Backfill failed: {error_msg}")

        return {
            "status": "error",
            "duration_seconds": round(elapsed, 2),
            "error": error_msg,
            "message": f"Backfill failed: {error_msg}",
        }
    finally:
        output.close()


@shared_task(bind=True, name="search.cleanup_search_vectors")
def cleanup_search_vectors_task(
    self,
    batch_size: int = 5000,
    no_vacuum: bool = False,
    vacuum_full: bool = False,
    model_scope: str = "all",
):
    """
    NULL out search_vector data and VACUUM to reclaim disk space.

    Args:
        batch_size: Number of records to process per batch
        no_vacuum: If True, skip VACUUM (faster, but no space reclaimed)
        vacuum_full: If True, use VACUUM FULL (max space reclamation, locks table)
        model_scope: Which models to process - 'all', 'extraction', or 'others'

    Returns:
        dict with status, duration, and output
    """
    logger.info(
        f"Starting cleanup_search_vectors task: vacuum_full={vacuum_full}, model_scope={model_scope}"
    )

    # Update task state
    self.update_state(
        state="STARTED",
        meta={
            "vacuum_full": vacuum_full,
            "model_scope": model_scope,
            "status": "Cleaning up search vectors...",
        },
    )

    start_time = time.time()
    output = StringIO()

    try:
        # Build command arguments based on model_scope
        kwargs = {
            "batch_size": batch_size,
            "no_vacuum": no_vacuum,
            "vacuum_full": vacuum_full,
            "force": True,
            "stdout": output,
        }

        if model_scope == "extraction":
            kwargs["extraction_only"] = True
        elif model_scope == "others":
            kwargs["others_only"] = True
        # If 'all', no additional flag needed

        call_command("cleanup_search_vectors", **kwargs)

        elapsed = time.time() - start_time
        output_text = output.getvalue()

        result = {
            "status": "success",
            "duration_seconds": round(elapsed, 2),
            "output": output_text,
            "message": f"Cleanup completed successfully in {elapsed:.1f} seconds",
        }

        logger.info(f"Completed cleanup_search_vectors in {elapsed:.1f}s")
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"Cleanup failed: {error_msg}")

        return {
            "status": "error",
            "duration_seconds": round(elapsed, 2),
            "error": error_msg,
            "message": f"Cleanup failed: {error_msg}",
        }
    finally:
        output.close()


@shared_task(bind=True, name="search.manage_postgres_search")
def manage_postgres_search_task(self, action: str, model_scope: str = "all"):
    """
    Manage PostgreSQL search infrastructure (triggers, indexes, etc.).

    Args:
        action: Action to perform (e.g., 'disable-trigger', 'enable-trigger',
                'drop-index', 'create-index', 'disable-all', 'enable-all')
        model_scope: Which models to process - 'all', 'extraction', or 'others'

    Returns:
        dict with status, duration, and output
    """
    logger.info(
        f"Starting manage_postgres_search task: action={action}, model_scope={model_scope}"
    )

    # Update task state
    self.update_state(
        state="STARTED",
        meta={
            "action": action,
            "model_scope": model_scope,
            "status": f"Running {action}...",
        },
    )

    start_time = time.time()
    output = StringIO()

    try:
        # Build command arguments based on model_scope
        kwargs = {"force": True, "stdout": output}

        # Add action flag
        action_arg = f"--{action}"

        # Add model scope flags
        if model_scope == "extraction":
            kwargs["extraction_only"] = True
        elif model_scope == "others":
            kwargs["others_only"] = True
        # If 'all', no additional flag needed

        call_command("manage_postgres_search", action_arg, **kwargs)

        elapsed = time.time() - start_time
        output_text = output.getvalue()

        result = {
            "status": "success",
            "action": action,
            "duration_seconds": round(elapsed, 2),
            "output": output_text,
            "message": f"{action} completed successfully in {elapsed:.1f} seconds",
        }

        logger.info(f"Completed {action} in {elapsed:.1f}s")
        return result

    except Exception as e:
        elapsed = time.time() - start_time
        error_msg = str(e)
        logger.error(f"{action} failed: {error_msg}")

        return {
            "status": "error",
            "action": action,
            "duration_seconds": round(elapsed, 2),
            "error": error_msg,
            "message": f"{action} failed: {error_msg}",
        }
    finally:
        output.close()
