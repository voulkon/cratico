"""
Celery tasks for classification batch processing.

These tasks handle large-scale classification jobs in a stable, resumable way.
"""

from typing import Any, Dict

from celery import shared_task
from core.models.classification_job import (
    ClassificationJob,
    ClassificationJobLog,
    JobStatus,
)
from core.models.decisions import Decision
from core.services.direct_assignment_detection_service import classification_service
from django.db.models import Q
from loguru import logger


@shared_task(name="classification.start_batch_job", bind=True)
def start_batch_classification_job(self, job_id: str) -> Dict[str, Any]:
    """
    Start a batch classification job.

    This is the main entry point for processing classification jobs.
    It handles:
    - Building the queryset based on job configuration
    - Processing in batches
    - Progress tracking
    - Pause/resume support
    - Error handling

    Args:
        job_id: UUID of the ClassificationJob to process

    Returns:
        Dict with final statistics
    """
    try:
        job = ClassificationJob.objects.get(job_id=job_id)
    except ClassificationJob.DoesNotExist:
        logger.error(f"ClassificationJob {job_id} not found")
        return {"success": False, "error": "Job not found"}

    # Mark job as started
    job.mark_started(celery_task_id=self.request.id)
    log_job_event(job, "INFO", f"Job started with batch_size={job.batch_size}")

    try:
        # Build queryset based on job configuration
        decisions_qs = build_queryset_for_job(job)
        total_count = decisions_qs.count()

        job.total_decisions = total_count
        job.save(update_fields=["total_decisions"])

        log_job_event(job, "INFO", f"Found {total_count:,} decisions to process")

        if total_count == 0:
            job.mark_completed()
            log_job_event(job, "INFO", "No decisions to process")
            return {"success": True, "processed": 0}

        # Process in batches
        stats = process_in_batches(job, decisions_qs)

        # Mark job as completed
        job.mark_completed()
        log_job_event(
            job,
            "INFO",
            f"Job completed: {stats['processed']:,} processed, "
            f"{stats['direct_assignments']:,} direct assignments found",
        )

        return {
            "success": True,
            "processed": stats["processed"],
            "direct_assignments": stats["direct_assignments"],
            "created": stats["created"],
            "updated": stats["updated"],
            "errors": stats["errors"],
        }

    except Exception as e:
        logger.exception(f"Job {job_id} failed: {e}")
        job.mark_failed(str(e))
        log_job_event(job, "ERROR", f"Job failed: {str(e)}")
        return {"success": False, "error": str(e)}


def build_queryset_for_job(job: ClassificationJob):
    """
    Build the queryset of decisions to classify based on job configuration.
    """
    decisions_qs = Decision.objects.all()

    # Apply mode-specific filters
    if job.processing_mode == "unclassified":
        decisions_qs = decisions_qs.filter(classification__isnull=True)

    elif job.processing_mode == "date_range":
        if job.start_date:
            decisions_qs = decisions_qs.filter(issue_date__gte=job.start_date)
        if job.end_date:
            decisions_qs = decisions_qs.filter(issue_date__lte=job.end_date)

    elif job.processing_mode == "reclassify":
        # Re-classify all decisions in date range
        if job.start_date:
            decisions_qs = decisions_qs.filter(issue_date__gte=job.start_date)
        if job.end_date:
            decisions_qs = decisions_qs.filter(issue_date__lte=job.end_date)

    elif job.processing_mode == "outdated":
        # Only decisions with outdated classifier version
        current_version = classification_service.CLASSIFIER_VERSION
        decisions_qs = decisions_qs.filter(
            ~Q(classification__classifier_version=current_version)
        )

    elif job.processing_mode == "all":
        # Process all decisions (use with caution)
        pass

    # Optimize queries by prefetching related data
    decisions_qs = (
        decisions_qs.select_related("decision_type")
        .prefetch_related("text_extraction")
        .order_by("id")
    )

    # Apply max_decisions limit if specified
    if job.max_decisions:
        decisions_qs = decisions_qs[: job.max_decisions]

    return decisions_qs


def process_in_batches(job: ClassificationJob, decisions_qs) -> Dict[str, int]:
    """
    Process decisions in batches with progress tracking.

    Supports:
    - Pause/resume (checks job status between batches)
    - Progress updates
    - Error handling per batch
    """
    batch_size = job.batch_size
    total_count = job.total_decisions

    # Initialize counters
    processed = job.processed_count
    direct_assignments = job.direct_assignments_found
    non_direct = job.non_direct_assignments
    created = job.created_count
    updated = job.updated_count
    errors = job.error_count

    batch_number = (processed // batch_size) + 1

    # Use manual batching with slicing to avoid PostgreSQL named cursor issues
    # iterator() creates named cursors that break with Celery's prefork concurrency
    offset = 0

    while offset < total_count:
        # Check if job was paused or cancelled
        job.refresh_from_db()
        if job.status == JobStatus.PAUSED.value:
            log_job_event(job, "INFO", f"Job paused at {processed:,} decisions")
            return {
                "processed": processed,
                "direct_assignments": direct_assignments,
                "non_direct_assignments": non_direct,
                "created": created,
                "updated": updated,
                "errors": errors,
            }

        if job.status == JobStatus.CANCELLED.value:
            log_job_event(job, "INFO", f"Job cancelled at {processed:,} decisions")
            return {
                "processed": processed,
                "direct_assignments": direct_assignments,
                "non_direct_assignments": non_direct,
                "created": created,
                "updated": updated,
                "errors": errors,
            }

        # Fetch batch using slicing (creates a new query each time, avoiding cursors)
        batch = list(decisions_qs[offset : offset + batch_size])

        if not batch:
            break

        offset += batch_size

        # Process batch
        try:
            batch_stats = classification_service.bulk_classify(
                decisions=batch, batch_size=batch_size, update_existing=job.reclassify
            )

            # Update counters
            processed += len(batch)
            direct_assignments += batch_stats["direct_assignments"]
            non_direct += batch_stats["non_direct_assignments"]
            created += batch_stats["created"]
            updated += batch_stats["updated"]
            errors += batch_stats["errors"]

            # Update job progress
            job.update_progress(
                processed=processed,
                direct_assignments=direct_assignments,
                non_direct=non_direct,
                created=created,
                updated=updated,
                errors=errors,
            )

            # Log progress every 10 batches
            if batch_number % 10 == 0:
                log_job_event(
                    job,
                    "INFO",
                    f"Progress: {processed:,}/{total_count:,} ({job.progress_percentage}%)",
                    batch_number=batch_number,
                    decisions_in_batch=len(batch),
                )

            batch_number += 1

        except Exception as e:
            logger.exception(f"Error processing batch {batch_number}: {e}")
            errors += len(batch)
            processed += len(batch)

            job.update_progress(
                processed=processed,
                direct_assignments=direct_assignments,
                non_direct=non_direct,
                created=created,
                updated=updated,
                errors=errors,
            )

            log_job_event(
                job,
                "ERROR",
                f"Batch {batch_number} failed: {str(e)}",
                batch_number=batch_number,
                decisions_in_batch=len(batch),
            )

            # Increment batch_number even on failure to continue processing
            batch_number += 1

    return {
        "processed": processed,
        "direct_assignments": direct_assignments,
        "non_direct_assignments": non_direct,
        "created": created,
        "updated": updated,
        "errors": errors,
    }


def log_job_event(job: ClassificationJob, level: str, message: str, **kwargs):
    """Create a log entry for a classification job"""
    ClassificationJobLog.objects.create(job=job, level=level, message=message, **kwargs)


@shared_task(name="classification.resume_paused_job")
def resume_paused_classification_job(job_id: str) -> Dict[str, Any]:
    """
    Resume a paused classification job.

    This re-queues the main processing task.
    """
    try:
        job = ClassificationJob.objects.get(job_id=job_id)
    except ClassificationJob.DoesNotExist:
        return {"success": False, "error": "Job not found"}

    if job.status != JobStatus.PAUSED.value:
        return {"success": False, "error": f"Job is {job.status}, not paused"}

    # Resume the job
    job.resume()
    log_job_event(job, "INFO", "Job resumed")

    # Re-queue the main task
    start_batch_classification_job.delay(job_id=job_id)

    return {"success": True, "message": "Job resumed"}


@shared_task(name="classification.get_job_progress")
def get_job_progress(job_id: str) -> Dict[str, Any]:
    """
    Get current progress for a classification job.

    Useful for polling from admin interface.
    """
    try:
        job = ClassificationJob.objects.get(job_id=job_id)
    except ClassificationJob.DoesNotExist:
        return {"success": False, "error": "Job not found"}

    return {
        "success": True,
        "job_id": str(job.job_id),
        "status": job.status,
        "progress_percentage": job.progress_percentage,
        "processed_count": job.processed_count,
        "total_decisions": job.total_decisions,
        "direct_assignments_found": job.direct_assignments_found,
        "error_count": job.error_count,
        "decisions_per_second": job.decisions_per_second,
        "estimated_completion": (
            job.estimated_completion.isoformat() if job.estimated_completion else None
        ),
        "duration_seconds": job.duration_seconds,
    }
