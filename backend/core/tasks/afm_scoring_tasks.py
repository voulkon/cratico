"""
Celery tasks for AFM scoring batch processing.

These tasks handle large-scale scoring jobs in a stable, resumable way.
"""

from typing import Any, Dict

from celery import shared_task
from core.models.afm_scoring import AFMScoringConfig
from core.models.afm_scoring_job import (
    AFMScoringJob,
    AFMScoringJobLog,
    ScoringJobStatus,
)
from core.models.entities import AFMEntity
from loguru import logger


@shared_task(name="afm_scoring.start_batch_job", bind=True)
def start_afm_scoring_job(self, job_id: str) -> Dict[str, Any]:
    """
    Start a batch AFM scoring job.

    This is the main entry point for processing scoring jobs.
    It handles:
    - Building the queryset based on job configuration
    - Processing in batches
    - Progress tracking
    - Pause/resume support
    - Error handling

    Args:
        job_id: UUID of the AFMScoringJob to process

    Returns:
        Dict with final statistics
    """
    try:
        job = AFMScoringJob.objects.get(job_id=job_id)
    except AFMScoringJob.DoesNotExist:
        logger.error(f"AFMScoringJob {job_id} not found")
        return {"success": False, "error": "Job not found"}

    # Mark job as started
    job.mark_started(celery_task_id=self.request.id)
    log_job_event(job, "INFO", f"Job started with batch_size={job.batch_size}")

    try:
        # Get scoring configuration
        config = job.config or AFMScoringConfig.get_active()

        if not config:
            raise ValueError("No active scoring configuration found")

        log_job_event(job, "INFO", f"Using configuration: {config.name}")

        # Build queryset
        entities_qs = build_queryset_for_job(job)
        total_count = entities_qs.count()

        job.total_entities = total_count
        job.save(update_fields=["total_entities"])

        log_job_event(job, "INFO", f"Found {total_count:,} entities to process")

        if total_count == 0:
            job.mark_completed()
            log_job_event(job, "INFO", "No entities to process")
            return {"success": True, "processed": 0}

        # Process in batches
        stats = process_in_batches(job, entities_qs, config)

        # Mark job as completed
        job.mark_completed()
        log_job_event(
            job,
            "INFO",
            f"Job completed: {stats['processed']:,} processed, "
            f"{stats['eligible']:,} eligible for fetch",
        )

        return {
            "success": True,
            "processed": stats["processed"],
            "scored": stats["scored"],
            "eligible": stats["eligible"],
            "ineligible": stats["ineligible"],
            "errors": stats["errors"],
        }

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        job.mark_failed(str(e))
        log_job_event(job, "ERROR", f"Job failed: {str(e)}")
        return {"success": False, "error": str(e)}


def build_queryset_for_job(job: AFMScoringJob):
    """
    Build the queryset of entities to score based on job configuration.
    """
    entities_qs = AFMEntity.objects.all()

    # Exclude already fetched if requested
    if job.exclude_already_fetched:
        entities_qs = entities_qs.filter(gemi_lookup_success=False)

    # Optimize queries
    entities_qs = entities_qs.order_by("id")

    return entities_qs


def process_in_batches(
    job: AFMScoringJob, entities_qs, config: AFMScoringConfig
) -> Dict[str, int]:
    """
    Process entities in batches with progress tracking.

    Supports:
    - Pause/resume (checks job status between batches)
    - Progress updates
    - Error handling per batch
    """
    batch_size = job.batch_size
    total_count = job.total_entities

    # Initialize counters
    processed = job.processed_count
    scored = job.scored_count
    eligible = job.eligible_count
    ineligible = job.ineligible_count
    errors = job.error_count

    batch_number = (processed // batch_size) + 1

    # Use manual batching with slicing to avoid PostgreSQL named cursor issues
    offset = 0

    while offset < total_count:
        # Check if job was paused or cancelled
        job.refresh_from_db()
        if job.status == ScoringJobStatus.PAUSED.value:
            log_job_event(job, "INFO", f"Job paused at {processed:,} entities")
            return {
                "processed": processed,
                "scored": scored,
                "eligible": eligible,
                "ineligible": ineligible,
                "errors": errors,
            }

        if job.status == ScoringJobStatus.CANCELLED.value:
            log_job_event(job, "INFO", f"Job cancelled at {processed:,} entities")
            return {
                "processed": processed,
                "scored": scored,
                "eligible": eligible,
                "ineligible": ineligible,
                "errors": errors,
            }

        # Fetch batch using slicing
        batch = list(entities_qs[offset : offset + batch_size])

        if not batch:
            break

        offset += batch_size

        # Process batch
        try:
            batch_stats = score_batch(batch, config)

            # Update counters
            processed += len(batch)
            scored += batch_stats["scored"]
            eligible += batch_stats["eligible"]
            ineligible += batch_stats["ineligible"]
            errors += batch_stats["errors"]

            # Update job progress
            job.update_progress(
                processed=processed,
                scored=scored,
                eligible=eligible,
                ineligible=ineligible,
                errors=errors,
            )

            # Log progress every 10 batches
            if batch_number % 10 == 0:
                log_job_event(
                    job,
                    "INFO",
                    f"Progress: {processed:,}/{total_count:,} ({job.progress_percentage}%)",
                    batch_number=batch_number,
                    entities_in_batch=len(batch),
                )

            batch_number += 1

        except Exception as e:
            logger.exception(f"Error processing batch {batch_number}: {e}")
            errors += len(batch)
            processed += len(batch)

            job.update_progress(
                processed=processed,
                scored=scored,
                eligible=eligible,
                ineligible=ineligible,
                errors=errors,
            )

            log_job_event(
                job,
                "ERROR",
                f"Batch {batch_number} failed: {str(e)}",
                batch_number=batch_number,
                entities_in_batch=len(batch),
            )

            # Increment batch_number even on failure to continue processing
            batch_number += 1

    return {
        "processed": processed,
        "scored": scored,
        "eligible": eligible,
        "ineligible": ineligible,
        "errors": errors,
    }


def score_batch(entities_batch, config: AFMScoringConfig) -> Dict[str, int]:
    """
    Score a batch of entities using the AFMEntityScoringService.

    This ensures consistency with the scoring algorithm and uses all configured features:
    - Frequency (appearances in decisions)
    - Amount (total monetary value)
    - Organization diversity
    - Direct assignment count
    - Direct assignment percentage

    Returns:
        Dict with scored, eligible, ineligible, errors counts
    """
    from core.services.afm_scoring_service import AFMEntityScoringService

    scored = 0
    eligible = 0
    ineligible = 0
    errors = 0

    # Initialize scoring service
    service = AFMEntityScoringService(config=config)

    # Compute global statistics once for the batch
    # This is more efficient than recomputing for each entity
    global_stats = service._compute_global_statistics()

    for entity in entities_batch:
        try:
            # Use the service to score the entity
            score_data = service.score_entity(entity, global_stats)

            scored += 1
            if score_data["is_eligible"]:
                eligible += 1
            else:
                ineligible += 1

        except Exception as e:
            logger.error(f"Error scoring entity {entity.afm}: {e}")
            errors += 1

    return {
        "scored": scored,
        "eligible": eligible,
        "ineligible": ineligible,
        "errors": errors,
    }


def log_job_event(job: AFMScoringJob, level: str, message: str, **kwargs):
    """Create a log entry for a scoring job"""
    AFMScoringJobLog.objects.create(job=job, level=level, message=message, **kwargs)


@shared_task(name="afm_scoring.resume_paused_job")
def resume_paused_scoring_job(job_id: str) -> Dict[str, Any]:
    """
    Resume a paused scoring job.

    This re-queues the main processing task.
    """
    try:
        job = AFMScoringJob.objects.get(job_id=job_id)
    except AFMScoringJob.DoesNotExist:
        return {"success": False, "error": "Job not found"}

    if job.status != ScoringJobStatus.PAUSED.value:
        return {"success": False, "error": f"Job is {job.status}, not paused"}

    # Resume the job
    job.resume()
    log_job_event(job, "INFO", "Job resumed")

    # Re-queue the main task
    start_afm_scoring_job.delay(job_id=job_id)

    return {"success": True, "message": "Job resumed"}


@shared_task(name="afm_scoring.get_job_progress")
def get_job_progress(job_id: str) -> Dict[str, Any]:
    """
    Get current progress for a scoring job.

    Useful for polling from admin interface.
    """
    try:
        job = AFMScoringJob.objects.get(job_id=job_id)
    except AFMScoringJob.DoesNotExist:
        return {"success": False, "error": "Job not found"}

    return {
        "success": True,
        "job_id": str(job.job_id),
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "processed_count": job.processed_count,
        "total_entities": job.total_entities,
        "scored_count": job.scored_count,
        "eligible_count": job.eligible_count,
        "error_count": job.error_count,
        "entities_per_second": job.entities_per_second,
        "estimated_completion": (
            job.estimated_completion.isoformat() if job.estimated_completion else None
        ),
        "duration_seconds": job.duration_seconds,
    }
