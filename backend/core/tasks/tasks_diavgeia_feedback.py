"""
Celery tasks for Diavgeia feedback reporting.

Single point of work:
  - ``report_single_decision_feedback`` — one decision through the shared
    ``DiavgeiaFeedbackService.report_decision()`` path.  Used by the admin
    (single or via batch fan-out).

  - ``run_feedback_job`` — batch: resolves the candidate pool for a persisted
    ``DiavgeiaFeedbackJob``, fans out one task per decision, and tracks
    progress on the job row.

  - ``finalize_feedback_job`` — marks a job completed once all its
    per-decision results are settled (called from a sweeper / beat).
"""

from typing import Any

from celery import shared_task
from loguru import logger


@shared_task(bind=True, max_retries=2, default_retry_delay=30,
           name="diavgeia_feedback.report_single")
def report_single_decision_feedback(
    self,
    decision_id: int,
    dry_run: bool = False,
    job_result_id: int | None = None,
    reporter_email: str | None = None,
    feedback_errors: list[str] | None = None,
) -> dict[str, Any]:
    """
    Report one decision to the Diavgeia feedback API on a worker.

    If ``job_result_id`` is given, update that
    ``DiavgeiaFeedbackJobResult`` row and bump the parent job's progress
    counters (batch fan-out mode).
    """
    from core.models.decisions import Decision
    from core.services.diavgeia_feedback_service import DiavgeiaFeedbackService

    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        logger.error(
            f"report_single_decision_feedback: decision {decision_id} not found"
        )
        return {"status": "error", "reason": "decision_not_found"}

    svc = DiavgeiaFeedbackService()
    try:
        result = svc.report_decision(
            decision,
            dry_run=dry_run,
            reporter_email=reporter_email,
            feedback_errors=feedback_errors,
        )
    except Exception as exc:
        logger.error(
            f"report_single_decision_feedback {decision_id} failed: {exc}",
            exc_info=True,
        )
        if job_result_id:
            _record_result(job_result_id, status="error", reason=str(exc)[:255])
        raise self.retry(exc=exc)

    if job_result_id:
        _record_result(
            job_result_id,
            status=result["status"],
            reason=result.get("reason", "")[:255],
            reference=result.get("reference", "")[:64],
            response=result.get("response", ""),
        )

    return result


def _record_result(
    job_result_id: int,
    *,
    status: str,
    reason: str = "",
    reference: str = "",
    response: str = "",
) -> None:
    """Persist a per-decision result and advance the parent job counters."""
    from django.db.models import F

    from core.models.diavgeia_feedback_job import (
        DiavgeiaFeedbackJob,
        DiavgeiaFeedbackJobResult,
    )

    try:
        res = DiavgeiaFeedbackJobResult.objects.select_related("job").get(
            id=job_result_id
        )
    except DiavgeiaFeedbackJobResult.DoesNotExist:
        return

    res.status = status
    res.reason = reason
    res.reference = reference
    res.response = response
    res.save(update_fields=["status", "reason", "reference", "response"])

    counter = {
        "reported": "reported",
        "would_report": "reported",
        "already_reported": "already_reported",
        "error": "errors",
    }.get(status, "skipped")

    DiavgeiaFeedbackJob.objects.filter(id=res.job_id).update(
        processed_count=F("processed_count") + 1,
        **{counter: F(counter) + 1},
    )


@shared_task(bind=True, name="diavgeia_feedback.run_job")
def run_feedback_job(self, job_id: str) -> dict[str, Any]:
    """
    Resolve the candidate pool for a job and fan out per-decision tasks.

    Creates a placeholder ``DiavgeiaFeedbackJobResult`` (status=pending) per
    candidate so progress is visible immediately, then enqueues one
    ``report_single_decision_feedback`` task each.
    """
    from django.db.models import Exists, OuterRef

    from core.models.diavgeia_feedback_job import (
        DiavgeiaFeedbackJob,
        DiavgeiaFeedbackJobResult,
        FeedbackJobStatus,
    )
    from core.models.diavgeia_feedback_report import DiavgeiaFeedbackReport
    from core.models.decisions import Decision
    from core.models.entities import DecisionAmountField

    try:
        job = DiavgeiaFeedbackJob.objects.get(job_id=job_id)
    except DiavgeiaFeedbackJob.DoesNotExist:
        logger.error(f"run_feedback_job: job {job_id} not found")
        return {"status": "error", "reason": "job_not_found"}

    job.mark_started(celery_task_id=self.request.id)

    try:
        has_corrected = Exists(
            DecisionAmountField.objects.filter(
                decision=OuterRef("pk"),
                verified_amount__isnull=False,
            )
        )
        already_reported = Exists(
            DiavgeiaFeedbackReport.objects.filter(
                decision=OuterRef("pk"), reported=True
            )
        )
        candidates = (
            Decision.objects
            .filter(has_corrected)
            .exclude(already_reported)
        )
        if job.start_date:
            candidates = candidates.filter(issue_date_day__gte=job.start_date)
        if job.end_date:
            candidates = candidates.filter(issue_date_day__lte=job.end_date)
        candidates = candidates.order_by("-issue_date")
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
            res = DiavgeiaFeedbackJobResult.objects.create(
                job=job, decision_id=d.id, status="pending"
            )
            report_single_decision_feedback.delay(
                decision_id=d.id,
                dry_run=job.dry_run,
                job_result_id=res.id,
                reporter_email=job.reporter_email or None,
                feedback_errors=job.feedback_errors or None,
            )

        job.status = FeedbackJobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        logger.info(
            f"DiavgeiaFeedbackJob {job_id}: fanned out {len(decisions)} decisions"
        )
        return {"status": "running", "total": len(decisions)}

    except Exception as exc:
        logger.exception(f"run_feedback_job {job_id} failed: {exc}")
        job.mark_failed(str(exc))
        return {"status": "error", "reason": str(exc)}


@shared_task(name="diavgeia_feedback.finalize_job")
def finalize_feedback_job(job_id: str) -> dict[str, Any]:
    """
    Mark a job completed once all its per-decision results are settled.

    Call from beat or a periodic sweeper; cheap no-op if still running.
    """
    from core.models.diavgeia_feedback_job import (
        DiavgeiaFeedbackJob,
        FeedbackJobStatus,
    )

    try:
        job = DiavgeiaFeedbackJob.objects.get(job_id=job_id)
    except DiavgeiaFeedbackJob.DoesNotExist:
        return {"status": "error", "reason": "job_not_found"}

    if job.status != FeedbackJobStatus.RUNNING:
        return {"status": job.status}

    if job.processed_count >= job.total_candidates:
        job.mark_completed()
        return {"status": "completed"}

    return {"status": "running", "processed": job.processed_count}
