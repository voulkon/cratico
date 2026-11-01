"""
Decision Import Tasks - Distributed Pipeline for Daily Decision Ingestion

[WARN]️ CRITICAL BUG FIX (2026-01-04):
   Removed apply_async(countdown=X) due to Celery 5.6.1 bug with RabbitMQ without
   delayed message exchange plugin. Tasks with countdown were silently lost.

   Solution: Moved delay inside tasks using time.sleep() to prevent race conditions.
   See: /docs/celery-countdown-bug-research.md for full investigation.

Architecture:
    1. fetch_daily_decisions_to_pickle: Fetches full day from API
    2. Splits into chunks, dispatches store_decisions_from_pickle for each
    3. Each storage task sleeps before processing (prevents DB deadlocks)
"""

import random
import time
import traceback
from datetime import timedelta
from typing import Any, Dict, Optional

from celery import shared_task
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.import_jobs import ImportFailure, ImportJob, ImportJobStatus
from core.services.redis_decision_cache import RedisDecisionCache
from diavgeia_api.models.decisions import Decision
from django.utils import timezone
from loguru import logger

PROGRESS_LOG_STEP = 10


def _log_import_progress(
    import_job: ImportJob, redis_client: Any, task_id: str
) -> None:
    """Log a job's progress once per 10% milestone (10%, 20%, ... 100%).

    Chunks are processed by parallel workers, so a Redis ``SET NX`` guard makes
    sure only one worker emits the line for a given milestone.
    """
    progress = import_job.progress_percentage
    milestone = int(progress // PROGRESS_LOG_STEP) * PROGRESS_LOG_STEP
    if milestone <= 0:
        return

    from api.redis_keys import IMPORT_CHUNKS_EXPIRE, get_import_progress_key

    try:
        claimed = redis_client.set(
            get_import_progress_key(import_job.id, milestone),
            "1",
            nx=True,
            ex=IMPORT_CHUNKS_EXPIRE,
        )
    except Exception as e:
        logger.warning(
            f"Task {task_id}: Could not record {milestone}% progress milestone "
            f"for job {import_job.id}: {e}"
        )
        return

    if not claimed:
        return

    logger.info(
        f"Task {task_id}: Import job {import_job.id} at {progress:.1f}% "
        f"({import_job.chunks_completed + import_job.chunks_failed}/"
        f"{import_job.total_chunks} chunks), "
        f"restored={import_job.decisions_restored_from_redis}/"
        f"{import_job.total_decisions}, "
        f"assigned={import_job.decisions_assigned_to_pipeline}"
    )


@shared_task(bind=True, max_retries=3)
def fetch_daily_decisions_to_redis(
    self,
    target_date_str: str,
    search_params: Optional[Dict[str, Any]] = None,
    chunk_size: int = 10,
    job_id: Optional[int] = None,
):
    """
    Phase 1: Fetch ALL decisions for a full day and save to Redis with batch tracking.

    NOW EXPECTS job_id from orchestrator - updates existing ImportJob instead of creating new one.
    This provides immediate visibility as soon as the import is queued.

    IMPROVEMENTS:
    - Uses Redis instead of filesystem pickles (no lost files on container restart)
    - Updates existing ImportJob created by orchestrator
    - Provides visibility into import status from the moment it's queued

    Args:
        target_date_str: Date in ISO format (e.g., "2025-03-09")
        search_params: Additional search parameters
        chunk_size: Number of decisions per chunk (default: 10)
        job_id: ImportJob ID created by orchestrator (required)

    Returns:
        Dict with job_id, Redis keys, and metadata
    """
    try:
        from datetime import datetime

        target_date = datetime.fromisoformat(target_date_str).date()

        # Get the ImportJob created by orchestrator
        if job_id:
            try:
                import_job = ImportJob.objects.get(id=job_id)
                logger.info(
                    f"Task {self.request.id}: Using existing ImportJob {import_job.id} for {target_date}"
                )
            except ImportJob.DoesNotExist:
                logger.error(
                    f"Task {self.request.id}: ImportJob {job_id} not found! Creating new one."
                )
                import_job = None
        else:
            logger.warning(
                f"Task {self.request.id}: No job_id provided (legacy call?), creating new ImportJob"
            )
            import_job = None

        # Fallback: Create ImportJob if not found (backward compatibility)
        if not import_job:
            import_job = ImportJob.objects.create(
                start_date=target_date,
                end_date=target_date,
                celery_task_id=self.request.id,
                status=ImportJobStatus.FETCHING,
                search_params=search_params,
            )
            logger.info(
                f"Task {self.request.id}: Created new ImportJob {import_job.id} for {target_date}"
            )

        # Update job status to FETCHING (if called via queue, already FETCHING - this is idempotent)
        # If called directly or as fallback, this transitions from PENDING
        import_job.status = ImportJobStatus.FETCHING
        import_job.celery_task_id = self.request.id
        if search_params:
            import_job.search_params = {
                **(import_job.search_params or {}),
                **search_params,
            }
        import_job.save(update_fields=["status", "celery_task_id", "search_params"])

        logger.info(
            f"Task {self.request.id}: ImportJob {import_job.id} in FETCHING status"
        )

        # Use centralized fetch service for consistency
        from core.services.decision_fetch_reconcile_service import (
            DecisionFetchReconcileService,
        )

        fetch_service = DecisionFetchReconcileService()

        # Fetch all decisions AND reconcile with official count
        # This handles: pagination, feature flags, entity filters, AND validates count accuracy
        all_decisions, reconciliation = fetch_service.fetch_and_reconcile(
            target_date=target_date,
            additional_params=search_params,
            include_feature_flags=True,
        )

        # Update job with total count
        import_job.total_decisions = len(all_decisions)
        import_job.status = ImportJobStatus.SPLITTING
        import_job.save(update_fields=["total_decisions", "status"])

        # Log reconciliation results
        logger.success(
            f"Task {self.request.id}: Fetched {len(all_decisions)} decisions for {target_date}"
        )
        
        # Build reconciliation log message
        filters_applied = reconciliation.get('filters_applied', False)
        
        if filters_applied:
            # Filtered query - only show pagination check
            recon_msg = (
                f"Reconciliation (filtered query): "
                f"API_reported={reconciliation.get('api_reported_total')}, "
                f"Ours={reconciliation.get('our_count')}"
            )
            
            our_vs_api = reconciliation.get('our_vs_api_diff')
            if our_vs_api is not None and our_vs_api != 0:
                recon_msg += f", Pagination_mismatch={our_vs_api}"
            else:
                recon_msg += f", Pagination=OK"
            
            recon_msg += f", Status={reconciliation.get('status')}"
        else:
            # Unfiltered query - show full three-way reconciliation
            recon_msg = (
                f"Reconciliation: Official={reconciliation.get('official_count')}, "
                f"API_reported={reconciliation.get('api_reported_total')}, "
                f"Ours={reconciliation.get('our_count')}"
            )
            
            diff = reconciliation.get('difference')
            pct = reconciliation.get('percentage_diff', 0)
            if diff is not None:
                recon_msg += f", Diff_vs_Official={diff} ({pct:.2f}%)"
            
            # Add pagination mismatch info if available
            our_vs_api = reconciliation.get('our_vs_api_diff')
            if our_vs_api is not None and our_vs_api != 0:
                recon_msg += f", Pagination_mismatch={our_vs_api}"
            
            recon_msg += f", Status={reconciliation.get('status')}"
        
        logger.info(recon_msg)

        # Handle case with zero decisions
        if len(all_decisions) == 0:
            import_job.status = ImportJobStatus.COMPLETED
            import_job.completed_at = timezone.now()
            import_job.save(update_fields=["status", "completed_at"])
            logger.info(
                f"Task {self.request.id}: No decisions found for {target_date}, marking job as completed"
            )

            # Notify the queue so the backfill chain continues.
            # Without this, zero-decision days silently break the
            # trigger_next_backfill → dispatch → on_job_completed loop.
            try:
                from core.services.import_job_queue import ImportJobQueue
                ImportJobQueue().on_job_completed(import_job.id)
            except Exception as e:
                logger.warning(
                    f"Task {self.request.id}: Failed to notify queue of "
                    f"zero-decision job completion: {e}"
                )

            return {
                "status": "success",
                "job_id": import_job.id,
                "decisions_count": 0,
                "chunks_created": 0,
                "target_date": target_date_str,
                "message": "No decisions found for this date",
                "task_id": self.request.id,
            }

        # Initialize Redis cache
        redis_cache = RedisDecisionCache()

        # Split into chunks and store in Redis
        storage_tasks = []
        total_chunks = (len(all_decisions) + chunk_size - 1) // chunk_size

        for i in range(0, len(all_decisions), chunk_size):
            chunk_decisions = all_decisions[i : i + chunk_size]
            chunk_index = i // chunk_size
            chunk_id = f"{import_job.id}_chunk_{chunk_index}"

            # Store chunk in Redis with metadata
            metadata = {
                "job_id": import_job.id,
                "target_date": target_date_str,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "parent_task": self.request.id,
            }

            redis_cache.store_chunk(
                chunk_id=chunk_id, decisions=chunk_decisions, metadata=metadata
            )

            # Dispatch storage task with internal delay to prevent race conditions
            delay_seconds = random.uniform(0.1, 2.0)

            storage_task = store_decisions_from_redis.apply_async(
                args=[chunk_id, import_job.id], kwargs={"delay_seconds": delay_seconds}
            )
            storage_tasks.append(storage_task.id)

            logger.debug(
                f"Dispatched storage task {storage_task.id} for chunk {chunk_index}/{total_chunks}"
            )

        # Update job record with chunk task IDs
        import_job.total_chunks = total_chunks
        import_job.chunk_task_ids = storage_tasks
        import_job.status = ImportJobStatus.PROCESSING
        import_job.save(update_fields=["total_chunks", "chunk_task_ids", "status"])

        logger.success(
            f"Task {self.request.id}: Split {len(all_decisions)} decisions into "
            f"{total_chunks} chunks, dispatched {len(storage_tasks)} storage tasks"
        )

        return {
            "status": "success",
            "job_id": import_job.id,
            "decisions_count": len(all_decisions),
            "chunks_created": total_chunks,
            "target_date": target_date_str,
            "storage_tasks": storage_tasks,
            "task_id": self.request.id,
        }

    except Exception as e:
        logger.error(f"Task {self.request.id}: Fetch failed: {str(e)}")

        # Update job status if it exists
        try:
            import_job = (
                ImportJob.objects.get(id=job_id)
                if job_id
                else ImportJob.objects.get(celery_task_id=self.request.id)
            )
            import_job.status = ImportJobStatus.FAILED
            import_job.error_details = str(e)
            import_job.save(update_fields=["status", "error_details"])

            # Record structured failure
            ImportFailure.objects.create(
                import_job=import_job,
                task_id=self.request.id,
                failure_type=ImportFailure.FailureType.FETCH,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
                data_snapshot={
                    "target_date": target_date_str,
                    "search_params": search_params,
                },
            )
        except ImportJob.DoesNotExist:
            pass

        # Celery retry with exponential backoff
        raise self.retry(countdown=60 * (2**self.request.retries), exc=e)


@shared_task(bind=True, max_retries=3)
def fetch_hourly_decisions_to_redis(self, job_id: int):
    """
    Phase 1 (hourly): Fetch decisions submitted in a rolling timestamp window
    and store them in Redis for distributed processing.

    Unlike the daily task, the window is recomputed **at execution time** from
    the live hourly watermark — enqueue-time estimates are never trusted. The
    window spans ``watermark − HOURLY_IMPORT_OVERLAP_MINUTES → now``, capped at
    ``HOURLY_IMPORT_MAX_WINDOW_HOURS`` so a long outage does not create one
    unbounded job that blocks the import queue.

    Hourly jobs are always queue-created, so ``job_id`` is required and no
    fallback job is ever created.

    The watermark is advanced ONLY after the fetched decisions are durable in
    Redis and their storage tasks have been dispatched. Zero-decision windows
    are a first-class success (nights/weekends hit them constantly).

    Args:
        job_id: ImportJob ID created by the queue (required)

    Returns:
        Dict with job_id, window bounds, Redis chunk metadata
    """
    from core.constants.decision_import_constants import (
        HOURLY_IMPORT_MAX_WINDOW_HOURS,
        HOURLY_IMPORT_OVERLAP_MINUTES,
    )
    from core.models.sync_status import SyncStatus

    chunk_size = 10
    window_from: Optional[str] = None
    window_to: Optional[str] = None

    try:
        # 1. job_id is required — hourly jobs are always queue-created.
        try:
            import_job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            logger.error(
                f"Task {self.request.id}: ImportJob {job_id} not found — "
                f"hourly jobs must be queue-created"
            )
            return {
                "status": "error",
                "reason": "job_not_found",
                "job_id": job_id,
                "task_id": self.request.id,
            }

        # 2. Record the verification window start (consumed by the post-import
        #    trigger in T08) and 3. recompute the window at execution time.
        fetch_started_at = timezone.now().isoformat()
        to_dt = timezone.now()
        from_dt = SyncStatus.get_last_hourly_sync() - timedelta(
            minutes=HOURLY_IMPORT_OVERLAP_MINUTES
        )

        # Bound a catch-up after an outage: one job never spans more than the
        # cap.  The watermark advances only to the capped end, so later jobs
        # continue from there in bounded steps.
        max_window = timedelta(hours=HOURLY_IMPORT_MAX_WINDOW_HOURS)
        if to_dt - from_dt > max_window:
            capped_to = from_dt + max_window
            logger.warning(
                f"Task {self.request.id}: Hourly window {from_dt} → {to_dt} "
                f"exceeds {HOURLY_IMPORT_MAX_WINDOW_HOURS}h; capping to "
                f"{capped_to} (remaining gap caught up by later runs)"
            )
            to_dt = capped_to

        window_from = from_dt.isoformat()
        window_to = to_dt.isoformat()

        import_job.status = ImportJobStatus.FETCHING
        import_job.celery_task_id = self.request.id
        import_job.search_params = {
            **(import_job.search_params or {}),
            "fetch_started_at": fetch_started_at,
            "window_from": window_from,
            "window_to": window_to,
        }
        import_job.save(update_fields=["status", "celery_task_id", "search_params"])

        logger.info(
            f"Task {self.request.id}: Hourly window recomputed at execution: "
            f"{window_from} → {window_to} (job {import_job.id})"
        )

        # 4. Fetch + reconcile the window via the centralized service.
        from core.services.decision_fetch_reconcile_service import (
            DecisionFetchReconcileService,
        )

        fetch_service = DecisionFetchReconcileService()
        decisions, api_total, types_filtered = fetch_service.fetch_decisions_for_window(
            from_dt, to_dt
        )
        reconciliation = fetch_service.reconcile_window(
            from_dt, to_dt, len(decisions), api_total, types_filtered
        )
        logger.info(f"Task {self.request.id}: Window reconciliation: {reconciliation}")

        # 5. Zero decisions — a first-class success (nights/weekends).
        if len(decisions) == 0:
            import_job.status = ImportJobStatus.COMPLETED
            import_job.completed_at = timezone.now()
            import_job.save(update_fields=["status", "completed_at"])

            SyncStatus.update_hourly_sync(to_dt, 0)

            try:
                from core.services.import_job_queue import ImportJobQueue

                ImportJobQueue().on_job_completed(import_job.id)
            except Exception as e:
                logger.warning(
                    f"Task {self.request.id}: Failed to notify queue of "
                    f"zero-decision hourly job completion: {e}"
                )

            logger.info(
                f"Task {self.request.id}: No decisions in hourly window "
                f"{window_from} → {window_to}, marking job {import_job.id} completed"
            )
            return {
                "status": "success",
                "job_id": import_job.id,
                "decisions_count": 0,
                "chunks_created": 0,
                "window_from": window_from,
                "window_to": window_to,
                "message": "No decisions found in this window",
                "task_id": self.request.id,
            }

        # 6. Non-zero — chunk to Redis identically to the daily pipeline.
        redis_cache = RedisDecisionCache()

        storage_tasks = []
        total_chunks = (len(decisions) + chunk_size - 1) // chunk_size

        for i in range(0, len(decisions), chunk_size):
            chunk_decisions = decisions[i : i + chunk_size]
            chunk_index = i // chunk_size
            chunk_id = f"{import_job.id}_chunk_{chunk_index}"

            metadata = {
                "job_id": import_job.id,
                "chunk_index": chunk_index,
                "total_chunks": total_chunks,
                "parent_task": self.request.id,
                "search_params": import_job.search_params,
            }

            redis_cache.store_chunk(
                chunk_id=chunk_id, decisions=chunk_decisions, metadata=metadata
            )

            delay_seconds = random.uniform(0.1, 2.0)

            storage_task = store_decisions_from_redis.apply_async(
                args=[chunk_id, import_job.id],
                kwargs={"delay_seconds": delay_seconds},
            )
            storage_tasks.append(storage_task.id)

            logger.debug(
                f"Task {self.request.id}: Dispatched storage task "
                f"{storage_task.id} for chunk {chunk_index}/{total_chunks}"
            )

        import_job.total_decisions = len(decisions)
        import_job.total_chunks = total_chunks
        import_job.chunk_task_ids = storage_tasks
        import_job.status = ImportJobStatus.PROCESSING
        import_job.save(
            update_fields=[
                "total_decisions",
                "total_chunks",
                "chunk_task_ids",
                "status",
            ]
        )

        # 7. Advance the watermark only now: decisions are durable in Redis and
        #    their storage tasks are dispatched. Chunk-level failures are handled
        #    by the existing retry/ImportFailure machinery (same as daily).
        SyncStatus.update_hourly_sync(to_dt, len(decisions))

        logger.success(
            f"Task {self.request.id}: Split {len(decisions)} hourly decisions into "
            f"{total_chunks} chunks, dispatched {len(storage_tasks)} storage tasks"
        )

        return {
            "status": "success",
            "job_id": import_job.id,
            "decisions_count": len(decisions),
            "chunks_created": total_chunks,
            "window_from": window_from,
            "window_to": window_to,
            "storage_tasks": storage_tasks,
            "task_id": self.request.id,
        }

    except Exception as e:
        logger.error(f"Task {self.request.id}: Hourly fetch failed: {str(e)}")

        # Update job status if it exists — do NOT advance the watermark.
        try:
            import_job = ImportJob.objects.get(id=job_id)
            import_job.status = ImportJobStatus.FAILED
            import_job.error_details = str(e)
            import_job.save(update_fields=["status", "error_details"])

            ImportFailure.objects.create(
                import_job=import_job,
                task_id=self.request.id,
                failure_type=ImportFailure.FailureType.FETCH,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
                data_snapshot={
                    "window_from": window_from,
                    "window_to": window_to,
                },
            )
        except ImportJob.DoesNotExist:
            pass

        # Celery retry with exponential backoff — watermark intentionally untouched.
        raise self.retry(countdown=60 * (2**self.request.retries), exc=e)


@shared_task(bind=True, max_retries=5)
def store_decisions_from_redis(
    self,
    chunk_id: str,
    job_id: int,
    skip_opensearch: bool = False,
    delay_seconds: float = 0,
):
    """
    Phase 2: Load decisions from Redis and run through full pipeline with job tracking.

    IMPROVEMENTS:
    - Reads from Redis instead of filesystem (reliable across container restarts)
    - Updates ImportJob progress atomically
    - Automatic cleanup of processed chunks
    - Better error handling and retry logic

    [WARN]️ CRITICAL: Implements internal delay via time.sleep() to prevent DB race conditions.
    This is safer than apply_async(countdown=X) which causes task loss in Celery 5.6.1.

    The orchestrator handles the complete lifecycle:
    - Stage 0: Import decision from DTO to database
    - Stage 1-7: Organizations, entities, amounts, companies, documents, opensearch, coverage

    Args:
        chunk_id: Redis key identifier for this chunk
        job_id: ImportJob ID for progress tracking
        skip_opensearch: Skip OpenSearch indexing to reduce infrastructure costs
        delay_seconds: Sleep this many seconds before processing (prevents race conditions)
    """
    # [WARN]️ BUG FIX (2026-01-04): Delay INSIDE task instead of countdown parameter
    if delay_seconds > 0:
        logger.debug(
            f"Task {self.request.id}: Sleeping {delay_seconds:.2f}s to prevent race conditions"
        )
        time.sleep(delay_seconds)

    try:
        logger.debug(
            f"Task {self.request.id}: Processing chunk {chunk_id} for job {job_id}"
        )

        # Initialize Redis cache
        redis_cache = RedisDecisionCache()

        # Load decisions from Redis (auto-deletes after read)
        chunk_data = redis_cache.get_chunk(chunk_id, delete_after_read=True)

        if not chunk_data:
            # Chunk expired from Redis - no point retrying, it's gone forever
            error_msg = (
                f"Chunk expired from Redis: {chunk_id}. "
                f"This typically happens when jobs are queued too long or processing is very slow. "
                f"Consider increasing IMPORT_CHUNKS_EXPIRE TTL or reducing queue backlog."
            )
            logger.error(f"Task {self.request.id}: {error_msg}")

            # Mark chunk as failed without retry
            try:
                import_job = ImportJob.objects.get(id=job_id)
                import_job.mark_chunk_failed(error_msg=error_msg)

                ImportFailure.objects.create(
                    import_job=import_job,
                    task_id=self.request.id,
                    failure_type=ImportFailure.FailureType.CHUNK,
                    error_message=error_msg,
                    error_traceback="Chunk not found in Redis (likely expired)",
                    data_snapshot={"chunk_id": chunk_id, "reason": "redis_expiration"},
                )
            except ImportJob.DoesNotExist:
                logger.warning(f"ImportJob {job_id} not found")

            # Don't retry - chunk is gone forever
            return {
                "status": "failed",
                "chunk_id": chunk_id,
                "job_id": job_id,
                "reason": "chunk_expired",
                "error": error_msg,
            }

        # Get decision dicts from Redis
        decision_dicts = chunk_data["decisions"]
        metadata = chunk_data.get("metadata", {})

        logger.debug(
            f"Task {self.request.id}: Loaded {len(decision_dicts)} decisions from Redis chunk {chunk_id}"
        )

        # Convert dicts back to Decision DTO objects
        decisions = []
        for decision_dict in decision_dicts:
            try:
                # Pydantic will handle datetime string conversion automatically
                decision_dto = Decision(**decision_dict)
                decisions.append(decision_dto)
            except Exception as parse_error:
                logger.error(
                    f"Task {self.request.id}: Failed to parse decision from dict: {parse_error}"
                )
                logger.debug(f"Problematic dict: {decision_dict}")
                # Skip this decision and continue with others
                continue

        # Get ImportJob for progress tracking
        try:
            import_job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            logger.error(f"Task {self.request.id}: ImportJob {job_id} not found!")
            import_job = None

        # Import decisions and dispatch pipeline tasks using orchestrator
        from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
        from core.tasks.tasks_documents import run_decision_pipeline_task
        from core.utils.discovery_tracking import (
            DiscoverySource,
            add_discovery_source_to_decision,
        )

        orchestrator = DecisionPipelineOrchestrator()
        dispatched_tasks = []
        failed_imports = []

        logger.debug(
            f"Task {self.request.id}: Processing {len(decisions)} decisions through orchestrator"
        )

        for i, decision_dto in enumerate(decisions, 1):
            try:
                # Import decision using orchestrator (Stage 0)
                decision = orchestrator._step_import_decision(decision_dto)

                if decision:
                    # Tag with discovery source
                    add_discovery_source_to_decision(
                        decision,
                        source_type=DiscoverySource.DEFAULT_SEARCH,
                        search_params=metadata.get("search_params", {}),
                        notes=f"Job {job_id}",
                        save=True,
                    )

                    # Check if decision needs processing
                    from core.models.decision_health import (
                        DecisionHealthCheck,
                        HealthStatus,
                    )

                    health_check = DecisionHealthCheck.objects.filter(
                        decision=decision
                    ).first()

                    needs_processing = True
                    if (
                        health_check
                        and health_check.overall_status == HealthStatus.HEALTHY
                    ):
                        needs_processing = False
                        logger.debug(
                            f"Task {self.request.id}: Skipping {decision.ada} - already healthy"
                        )

                    if needs_processing:
                        # Dispatch pipeline task for full processing
                        pipeline_task = run_decision_pipeline_task.delay(
                            ada=decision.ada,
                            force_reprocess=False,
                            skip_opensearch=skip_opensearch,
                        )
                        dispatched_tasks.append(
                            {"ada": decision.ada, "task_id": pipeline_task.id}
                        )
                else:
                    decision_ada = getattr(decision_dto, "ada", "unknown")
                    logger.error(
                        f"Task {self.request.id}: Failed to import {decision_ada}: "
                        f"orchestrator returned None"
                    )
                    failed_imports.append(
                        {"ada": decision_ada, "error": "Import returned None"}
                    )

            except Exception as decision_error:
                error_msg = str(decision_error).lower()
                decision_ada = getattr(decision_dto, "ada", "unknown")

                # Check if it's a critical database error
                is_critical_db_error = any(
                    keyword in error_msg
                    for keyword in [
                        "deadlock",
                        "lock",
                        "current transaction is aborted",
                    ]
                )

                if is_critical_db_error:
                    logger.error(
                        f"Task {self.request.id}: Critical DB error on {decision_ada}: {decision_error}"
                    )
                    raise decision_error  # Fail the whole chunk
                else:
                    logger.error(
                        f"Task {self.request.id}: Failed to process {decision_ada}: {decision_error}"
                    )
                    failed_imports.append(
                        {"ada": decision_ada, "error": str(decision_error)}
                    )

                    # Record specific decision failure
                    if import_job:
                        ImportFailure.objects.create(
                            import_job=import_job,
                            task_id=self.request.id,
                            ada=decision_ada,
                            failure_type=ImportFailure.FailureType.DECISION,
                            error_message=str(decision_error),
                            error_traceback=traceback.format_exc(),
                            data_snapshot=(
                                decision_dto.model_dump()
                                if hasattr(decision_dto, "model_dump")
                                else str(decision_dto)
                            ),
                        )

        # Update ImportJob progress
        if import_job:
            # Always track restored and assigned counts, even if some failed
            import_job.mark_chunk_completed(
                decisions_restored=len(decision_dicts),  # How many we got from Redis
                decisions_assigned=len(
                    dispatched_tasks
                ),  # How many we sent to pipeline
            )

            # Also track failures separately if any
            if failed_imports:
                from django.db.models import F

                ImportJob.objects.filter(pk=import_job.pk).update(
                    error_count=F("error_count") + len(failed_imports)
                )
                import_job.refresh_from_db()

            _log_import_progress(import_job, redis_cache.redis_client, self.request.id)

        logger.debug(
            f"Task {self.request.id}: Processed chunk {chunk_id}, "
            f"dispatched {len(dispatched_tasks)} pipeline tasks"
        )

        return {
            "status": "success",
            "chunk_id": chunk_id,
            "job_id": job_id,
            "decisions_loaded": len(decision_dicts),
            "decisions_parsed": len(decisions),
            "decisions_processed": len(dispatched_tasks),
            "decisions_failed": len(failed_imports),
            "failed_imports": failed_imports[:10],
            "pipeline_tasks_dispatched": len(dispatched_tasks),
            "task_id": self.request.id,
        }

    except Exception as e:
        error_msg = str(e).lower()
        logger.error(
            f"Task {self.request.id}: Storage failed for chunk {chunk_id}: {str(e)}"
        )

        # Update job with failure
        try:
            import_job = ImportJob.objects.get(id=job_id)
            import_job.mark_chunk_failed(error_msg=str(e))

            # Record structured failure for the chunk
            # Try to get decision ADAs from the chunk if available
            snapshot = {"chunk_id": chunk_id}
            if "decision_dicts" in locals():
                snapshot["decisions"] = decision_dicts

            ImportFailure.objects.create(
                import_job=import_job,
                task_id=self.request.id,
                failure_type=ImportFailure.FailureType.CHUNK,
                error_message=str(e),
                error_traceback=traceback.format_exc(),
                data_snapshot=snapshot,
            )
        except ImportJob.DoesNotExist:
            pass

        # Check for specific database errors
        is_deadlock = "deadlock detected" in error_msg
        is_aborted_transaction = "current transaction is aborted" in error_msg
        is_db_error = any(
            keyword in error_msg
            for keyword in ["deadlock", "lock", "transaction", "database", "connection"]
        )

        have_we_got_any_db_errors = is_deadlock or is_aborted_transaction or is_db_error
        have_we_reached_max_retries = self.request.retries < self.max_retries

        if have_we_got_any_db_errors and have_we_reached_max_retries:
            # For database errors, implement aggressive backoff with jitter
            base_delay = 20 * (3**self.request.retries)  # 20s, 60s, 180s, 540s, 1620s
            jitter = random.uniform(0, base_delay * 0.5)
            delay = int(base_delay + jitter)

            logger.warning(
                f"Task {self.request.id}: Database error (deadlock:{is_deadlock}, "
                f"aborted:{is_aborted_transaction}), retrying in {delay}s"
            )

            raise self.retry(countdown=delay, exc=e)

        elif self.request.retries < self.max_retries:
            # For non-database errors, standard retry
            logger.info(f"Task {self.request.id}: Retrying after non-DB error")
            raise self.retry(countdown=30 * (2**self.request.retries), exc=e)
        else:
            # Max retries reached - chunk will remain failed in batch
            logger.error(
                f"Task {self.request.id}: Max retries reached for chunk {chunk_id}"
            )
            raise


# Legacy compatibility wrapper (for existing code that calls the old function)
@shared_task(bind=True, max_retries=5)
def store_decisions_from_pickle(self, pickle_file: str, **kwargs):
    """
    DEPRECATED: Legacy compatibility wrapper for code using pickle files.

    This exists only to prevent breaking existing scheduled tasks.
    New code should use store_decisions_from_redis instead.
    """
    logger.warning(
        f"Task {self.request.id}: Using deprecated store_decisions_from_pickle. "
        f"Please migrate to store_decisions_from_redis."
    )
    raise NotImplementedError(
        "Pickle-based imports are deprecated. Use fetch_daily_decisions_to_redis instead."
    )


@shared_task(bind=True)
def fetch_daily_decisions_distributed(
    self,
    target_date_str: str,
    chunk_size: int = 10,
    force: bool = False,
    job_id: Optional[int] = None,
    search_params: Optional[Dict[str, Any]] = None,
):
    """
    Orchestrator task: Uses existing ImportJob or creates one, then dispatches fetch task.

    [WARN]️ DEPRECATED: Direct calls to this task are discouraged. Use ImportJobQueue.enqueue_job() instead.
    This task is kept for backward compatibility and is called internally by ImportJobQueue.

    Args:
        target_date_str: Date to fetch in ISO format (e.g., "2025-03-09")
        chunk_size: Number of decisions per chunk (default: 10)
        force: Force import even if already completed (default: False)
        job_id: Pre-created ImportJob ID from ImportJobQueue (optional)
        search_params: Additional search filters (e.g., org, signer, unit) (optional)

    Returns:
        Dict with orchestration results including job_id for tracking
    """
    try:
        from datetime import datetime

        target_date = datetime.fromisoformat(target_date_str).date()

        logger.info(
            f"Orchestrator {self.request.id}: Starting distributed import for {target_date} (force={force}, job_id={job_id})"
        )

        # Use provided ImportJob or create new one
        if job_id:
            try:
                import_job = ImportJob.objects.get(id=job_id)
                logger.info(
                    f"Orchestrator {self.request.id}: Using pre-created ImportJob {import_job.id}"
                )
            except ImportJob.DoesNotExist:
                logger.warning(
                    f"Orchestrator {self.request.id}: ImportJob {job_id} not found, creating new one"
                )
                import_job = None
        else:
            import_job = None

        # Create ImportJob if not provided (fallback for direct calls)
        if not import_job:
            # Check for existing job (unless force=True)
            existing_job = None
            if not force:
                existing_job = ImportJob.objects.filter(
                    start_date=target_date,
                    end_date=target_date,
                    status__in=[
                        ImportJobStatus.PENDING,
                        ImportJobStatus.FETCHING,
                        ImportJobStatus.SPLITTING,
                        ImportJobStatus.PROCESSING,
                    ],
                ).first()

                if existing_job:
                    logger.warning(
                        f"Orchestrator {self.request.id}: Import already in progress for {target_date} "
                        f"(job ID {existing_job.id}). Use --force to override."
                    )
                    return {
                        "status": "duplicate",
                        "message": f"Import already in progress for {target_date}",
                        "existing_job_id": existing_job.id,
                        "target_date": target_date_str,
                        "note": "Use force=True to create a new import job",
                    }

            # Create ImportJob for visibility
            # [WARN]️ Set status to FETCHING immediately to prevent race conditions
            import_job = ImportJob.objects.create(
                start_date=target_date,
                end_date=target_date,
                celery_task_id=self.request.id,
                status=ImportJobStatus.FETCHING,  # Immediate transition to prevent concurrency issues
                search_params={"chunk_size": chunk_size, "force": force},
            )

            logger.warning(
                f"Orchestrator {self.request.id}: Created ImportJob {import_job.id} for {target_date} "
                f"(DEPRECATED: Use ImportJobQueue.enqueue_job() instead of calling this task directly)"
            )

        # Dispatch the fetch task with job_id and search_params
        fetch_task = fetch_daily_decisions_to_redis.delay(
            target_date_str=target_date_str,
            search_params=search_params,
            chunk_size=chunk_size,
            job_id=import_job.id,
        )

        # Update job with fetch task ID
        import_job.celery_task_id = fetch_task.id
        import_job.save(update_fields=["celery_task_id"])

        logger.info(
            f"Orchestrator {self.request.id}: Dispatched fetch task {fetch_task.id} for {target_date}, "
            f"ImportJob {import_job.id} is now visible in monitoring"
        )

        return {
            "status": "dispatched",
            "target_date": target_date_str,
            "job_id": import_job.id,
            "fetch_task_id": fetch_task.id,
            "orchestrator_id": self.request.id,
            "note": f"ImportJob {import_job.id} created immediately for tracking. Check admin for progress.",
        }

    except Exception as e:
        logger.error(f"Orchestrator {self.request.id}: Failed to dispatch: {str(e)}")
        raise

    except Exception as e:
        logger.error(
            f"Orchestrator {self.request.id}: Failed to dispatch fetch task: {str(e)}"
        )
        raise
