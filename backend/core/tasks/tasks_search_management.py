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
from django.apps import apps
from django.contrib.postgres.search import SearchVector
from django.core.management import call_command
from django.db import transaction
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


@shared_task(
    bind=True,
    name="search.backfill_search_vectors_batch",
    max_retries=0,  # self-chaining; retries handled by re-enqueue
    acks_late=False,
)
def backfill_search_vectors_batch_task(
    self,
    model_key: str,
    batch_size: int = 5000,
    last_id: int = 0,
    total_to_backfill: int | None = None,
    total_processed: int = 0,
    only_null: bool = False,
    dry_run: bool = False,
) -> dict:
    """
    Backfill search_vector for a single model using key-based pagination.

    Self-chains through batches so no single invocation holds a DB
    transaction open too long.  Survives worker restarts.

    Args:
        model_key: Which model to backfill (e.g. 'decision', 'extraction', 'afmentity').
        batch_size: Rows per batch (default 5 000).
        last_id: Internal – highest pk processed so far.
        total_to_backfill: Internal – cached count of rows to process.
        total_processed: Internal – running total of processed rows.
        only_null: If True, only backfill rows where search_vector IS NULL.
        dry_run: If True, count and return without writing.

    Returns:
        dict with status, progress, and timing.
    """
    from core.constants.search_service import POSTGRES_FTS_MODELS

    if model_key not in POSTGRES_FTS_MODELS:
        raise ValueError(
            f"Unknown model_key '{model_key}'. Choices: {list(POSTGRES_FTS_MODELS.keys())}"
        )

    config = POSTGRES_FTS_MODELS[model_key]
    model_class = apps.get_model(
        config["model_path"].rsplit(".", 1)[0].split(".")[0],
        config["model_path"].rsplit(".", 1)[1],
    )
    text_fields = config["text_fields"]
    search_config_name = config["search_config"]

    # --- first invocation: count affected rows ---
    if total_to_backfill is None:
        qs = model_class.objects.all().order_by("pk")
        if only_null:
            qs = qs.filter(search_vector__isnull=True)
        total_to_backfill = qs.count()
        logger.info(
            "backfill_search_vectors_batch | model=%s | %s rows to backfill (dry_run=%s, only_null=%s)",
            model_key,
            total_to_backfill,
            dry_run,
            only_null,
        )

    if dry_run:
        return {
            "status": "dry_run",
            "model": model_key,
            "total_to_backfill": total_to_backfill,
            "message": (
                f"Would backfill {total_to_backfill:,} rows "
                f"for model '{model_key}'. Re-run with dry_run=False."
            ),
        }

    if total_to_backfill == 0:
        return {
            "status": "done",
            "model": model_key,
            "total_processed": 0,
        }

    # --- update one batch (key-based pagination: pk > last_id) ---
    # Build SearchVector expression from the model's text fields
    search_vector_expr = SearchVector(
        text_fields[0], config=search_config_name
    )
    for field in text_fields[1:]:
        search_vector_expr = search_vector_expr + SearchVector(
            field, config=search_config_name
        )

    # Query for this batch
    qs = model_class.objects.filter(pk__gt=last_id).order_by("pk")
    if only_null:
        qs = qs.filter(search_vector__isnull=True)

    batch_ids = list(qs.values_list("pk", flat=True)[:batch_size])

    if not batch_ids:
        # --- finished ---
        # Clear prerequisite cache so admin sees updated status
        from core.services.prerequisite_check_service import prerequisite_check

        prerequisite_check.clear_cache()

        return {
            "status": "done",
            "model": model_key,
            "total_processed": total_processed,
            "total_to_backfill": total_to_backfill,
            "message": (
                f"Backfilled {total_processed:,} rows for model '{model_key}'."
            ),
        }

    # Update search_vector for this batch
    with transaction.atomic():
        model_class.objects.filter(pk__in=batch_ids).update(
            search_vector=search_vector_expr
        )

    rows_in_batch = len(batch_ids)
    new_last_id = batch_ids[-1]
    total_processed += rows_in_batch

    # --- progress report ---
    pct = (
        round(total_processed / total_to_backfill * 100, 2)
        if total_to_backfill
        else 100
    )
    self.update_state(
        state="PROGRESS",
        meta={
            "model": model_key,
            "total_processed": total_processed,
            "total_to_backfill": total_to_backfill,
            "pct": pct,
            "last_id": new_last_id,
        },
    )
    logger.info(
        "backfill_search_vectors_batch | model=%s | last_id=%s → +%s rows  "
        "(%s/%s, %s%%)",
        model_key,
        new_last_id,
        rows_in_batch,
        total_processed,
        total_to_backfill,
        pct,
    )

    # --- chain next batch ---
    backfill_search_vectors_batch_task.apply_async(
        kwargs={
            "model_key": model_key,
            "batch_size": batch_size,
            "last_id": new_last_id,
            "total_to_backfill": total_to_backfill,
            "total_processed": total_processed,
            "only_null": only_null,
            "dry_run": False,
        },
    )
    return {
        "status": "chained",
        "model": model_key,
        "total_processed": total_processed,
        "last_id": new_last_id,
    }


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
