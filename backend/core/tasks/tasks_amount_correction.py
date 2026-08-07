"""
Celery tasks for amount correction.

Single point of work:
  - ``correct_single_decision`` — one decision through the shared
    ``AmountCorrectionService.correct_decision()`` path (get extraction, fetch
    if missing, detect, correct).  Used by the frontend (single), the admin
    (single or via batch fan-out), and indirectly by the batch task.

  - ``run_amount_correction_job`` — batch: resolves the candidate pool for a
    persisted ``AmountCorrectionJob``, fans out one task per decision, and
    tracks progress on the job row.

  - ``daily_amount_correction`` — scheduled entry (beat) that creates a job
    with applying corrections enabled and runs it.
"""

from datetime import date
from decimal import Decimal
from typing import Any

from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=2, default_retry_delay=30,
           name="amount_correction.correct_single")
def correct_single_decision(
    self,
    decision_id: int,
    dry_run: bool = False,
    read_if_missing: bool = True,
    job_result_id: int | None = None,
) -> dict[str, Any]:
    """
    Run the shared per-decision correction path on a worker.

    If ``job_result_id`` is given, update that ``AmountCorrectionJobResult``
    row and bump the parent job's progress counters (batch fan-out mode).
    """
    from core.models.decisions import Decision
    from core.services.amount_correction_service import AmountCorrectionService

    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        logger.error(f"correct_single_decision: decision {decision_id} not found")
        return {"status": "error", "reason": "decision_not_found"}

    svc = AmountCorrectionService()
    try:
        result = svc.correct_decision(
            decision, dry_run=dry_run, read_if_missing=read_if_missing
        )
    except Exception as exc:
        logger.error(
            f"correct_single_decision {decision_id} failed: {exc}", exc_info=True
        )
        if job_result_id:
            _record_result(job_result_id, status="error", reason=str(exc)[:255])
        raise self.retry(exc=exc)

    if job_result_id:
        _record_result(
            job_result_id,
            status=result["status"],
            reason=result.get("reason", "")[:255],
            group_correction=result.get("group_correction", False),
            corrections=result.get("corrections", []),
        )

    return result


def _record_result(
    job_result_id: int,
    *,
    status: str,
    reason: str = "",
    group_correction: bool = False,
    corrections: list | None = None,
) -> None:
    """Persist a per-decision result and advance the parent job counters."""
    from django.db.models import F

    from core.models.amount_correction_job import (
        AmountCorrectionJob,
        AmountCorrectionJobResult,
    )

    try:
        res = AmountCorrectionJobResult.objects.select_related("job").get(
            id=job_result_id
        )
    except AmountCorrectionJobResult.DoesNotExist:
        return

    res.status = status
    res.reason = reason
    res.group_correction = group_correction
    res.corrections = corrections or []
    res.save(update_fields=["status", "reason", "group_correction", "corrections"])

    # Advance counters atomically
    counter = {
        "corrected": "corrected",
        "would_correct": "corrected",
        "consistent": "consistent",
        "no_text_amounts_found": "no_text",
        "error": "errors",
    }.get(status, "skipped")

    AmountCorrectionJob.objects.filter(id=res.job_id).update(
        processed_count=F("processed_count") + 1,
        **{counter: F(counter) + 1},
    )


@shared_task(bind=True, name="amount_correction.run_job")
def run_amount_correction_job(self, job_id: str) -> dict[str, Any]:
    """
    Resolve the candidate pool for a job and fan out per-decision tasks.

    Creates a placeholder ``AmountCorrectionJobResult`` (status=pending) per
    candidate so progress is visible immediately, then enqueues one
    ``correct_single_decision`` task each.
    """
    from django.db.models import Exists, OuterRef

    from core.models.amount_correction_job import (
        AmountCorrectionJob,
        AmountCorrectionJobResult,
        CorrectionJobStatus,
    )
    from core.models.decisions import Decision
    from core.models.entities import DecisionAmountField

    try:
        job = AmountCorrectionJob.objects.get(job_id=job_id)
    except AmountCorrectionJob.DoesNotExist:
        logger.error(f"run_amount_correction_job: job {job_id} not found")
        return {"status": "error", "reason": "job_not_found"}

    job.mark_started(celery_task_id=self.request.id)

    try:
        from core.services.decision_facets import amount_sum_excluding_kae

        has_uncorrected = Exists(
            DecisionAmountField.objects.filter(
                decision=OuterRef("pk"),
                amount__gt=0,
                verified_amount__isnull=True,
            )
        )
        candidates = (
            Decision.objects
            .annotate(calc_total=amount_sum_excluding_kae())
            .filter(calc_total__gte=job.threshold)
            .filter(has_uncorrected)
        )
        if job.start_date:
            candidates = candidates.filter(issue_date_day__gte=job.start_date)
        if job.end_date:
            candidates = candidates.filter(issue_date_day__lte=job.end_date)
        candidates = candidates.order_by("-calc_total")
        if job.limit:
            candidates = candidates[: job.limit]

        decisions = list(candidates.only("id"))
        job.total_candidates = len(decisions)
        job.save(update_fields=["total_candidates", "updated_at"])

        if not decisions:
            job.mark_completed()
            return {"status": "completed", "total": 0}

        # Placeholder results, then fan out
        for d in decisions:
            res = AmountCorrectionJobResult.objects.create(
                job=job, decision_id=d.id, status="pending"
            )
            correct_single_decision.delay(
                decision_id=d.id,
                dry_run=job.dry_run,
                read_if_missing=job.read_if_missing,
                job_result_id=res.id,
            )

        job.status = CorrectionJobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        logger.info(
            f"AmountCorrectionJob {job_id}: fanned out {len(decisions)} decisions"
        )
        return {"status": "running", "total": len(decisions)}

    except Exception as exc:
        logger.exception(f"run_amount_correction_job {job_id} failed: {exc}")
        job.mark_failed(str(exc))
        return {"status": "error", "reason": str(exc)}


@shared_task(name="amount_correction.finalize_job")
def finalize_amount_correction_job(job_id: str) -> dict[str, Any]:
    """
    Mark a job completed once all its per-decision results are settled.

    Call from beat or a periodic sweeper; cheap no-op if still running.
    """
    from core.models.amount_correction_job import (
        AmountCorrectionJob,
        CorrectionJobStatus,
    )

    try:
        job = AmountCorrectionJob.objects.get(job_id=job_id)
    except AmountCorrectionJob.DoesNotExist:
        return {"status": "error", "reason": "job_not_found"}

    if job.status != CorrectionJobStatus.RUNNING:
        return {"status": job.status}

    if job.processed_count >= job.total_candidates:
        job.mark_completed()
        # Invalidate analytics caches if anything was actually corrected
        if job.corrected and not job.dry_run:
            from core.services.response_cache_service import response_cache
            response_cache.invalidate_prefix("top_")
        return {"status": "completed"}

    return {"status": "running", "processed": job.processed_count}


@shared_task(name="amount_correction.daily")
def daily_amount_correction() -> dict[str, Any]:
    """
    Scheduled daily run — creates a job that APPLIES corrections
    (dry_run=False) over high-value decisions and runs it.
    """
    from core.models.amount_correction_job import AmountCorrectionJob
    from core.services.amount_correction_service import (
        DEFAULT_CORRECTION_THRESHOLD,
    )

    job = AmountCorrectionJob.objects.create(
        threshold=DEFAULT_CORRECTION_THRESHOLD,
        dry_run=False,          # apply corrections
        read_if_missing=True,
        limit=500,
    )
    run_amount_correction_job.delay(job_id=str(job.job_id))
    logger.info(f"Daily amount correction job {job.job_id} created")
    return {"job_id": str(job.job_id)}
