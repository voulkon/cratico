"""
Celery tasks for amount correction and amount-related data-quality detection.

Single point of work:
  - ``correct_single_decision`` — one decision through every detector selected
    by ``mode`` (see ``core.services.data_quality``).  Used by the frontend
    (single), the admin (single or via batch fan-out), and the batch task.

  - ``run_amount_correction_job`` — batch: resolves the candidate pool for a
    persisted ``AmountCorrectionJob`` **via the detectors' candidate queries**,
    fans out one task per decision, and tracks progress on the job row.

  - ``daily_amount_correction`` — scheduled entry (beat) that creates a job
    with applying corrections enabled and runs it.

Detector selection
------------------
``AmountCorrectionJob.mode`` selects which detectors run:
``decimal_shift`` (default — the historical cents-based ×100/÷100 correction),
``non_monetary`` (DB-only AFM/KAE guard), or ``both``.  Adding a new detector
requires no change to this module: the mode→detector mapping and the candidate
queries both live in the registry.
"""

from datetime import date
from typing import Any

from celery import shared_task
from loguru import logger


def _resolve_candidate_ids(job) -> list[int]:
    """
    Union of the candidate ids of every detector selected by ``job.mode``.

    Each detector owns its own candidate query (see
    ``BaseDetector.candidate_ids``), so the batch job never duplicates a
    filter.  Order is preserved (the detector with the highest-value ordering
    first) and de-duplicated, then truncated to ``job.limit``.
    """
    from core.services.data_quality import resolve_detectors

    detectors = resolve_detectors(job.mode)
    ids: list[int] = []
    seen: set[int] = set()
    for detector in detectors:
        for decision_id in detector.candidate_ids(
            min_amount=job.threshold,
            max_amount=job.max_amount,
            imported_since=job.imported_since,
            issue_start=job.start_date,
            issue_end=job.end_date,
            limit=job.limit,
        ):
            if decision_id not in seen:
                seen.add(decision_id)
                ids.append(decision_id)
    if job.limit:
        ids = ids[: job.limit]
    logger.info(
        f"AmountCorrectionJob {job.job_id}: mode={job.mode} "
        f"detectors={[d.slug for d in detectors]} → {len(ids)} candidate(s)"
    )
    return ids


@shared_task(bind=True, max_retries=2, default_retry_delay=30,
           name="amount_correction.correct_single")
def correct_single_decision(
    self,
    decision_id: int,
    dry_run: bool = False,
    read_if_missing: bool = True,
    job_result_id: int | None = None,
    mode: str = "decimal_shift",
) -> dict[str, Any]:
    """
    Run every detector selected by ``mode`` on a worker.

    If ``job_result_id`` is given, update that ``AmountCorrectionJobResult``
    row and bump the parent job's progress counters (batch fan-out mode).
    """
    from core.models.decisions import Decision
    from core.services.data_quality import resolve_detectors, run_detectors, summarize

    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        logger.error(f"correct_single_decision: decision {decision_id} not found")
        return {"status": "error", "reason": "decision_not_found"}

    try:
        detectors = resolve_detectors(mode)
    except ValueError as exc:
        logger.error(f"correct_single_decision: {exc}")
        return {"status": "error", "reason": str(exc)}

    try:
        runs = run_detectors(
            decision,
            detectors,
            dry_run=dry_run,
            read_if_missing=read_if_missing,
        )
    except Exception as exc:
        # ``run_detectors`` already isolates per-detector failures; reaching
        # here means something systemic (e.g. the decision cannot be loaded).
        logger.error(
            f"correct_single_decision {decision_id} failed: {exc}", exc_info=True
        )
        if job_result_id:
            _record_result(job_result_id, status="error", reason=str(exc)[:255])
        raise self.retry(exc=exc)

    summary = summarize(runs)
    summary["decision_id"] = decision.id
    summary["ada"] = decision.ada

    if job_result_id:
        _record_result(job_result_id, **summary)

    return summary


def _record_result(
    job_result_id: int,
    *,
    status: str,
    reason: str = "",
    group_correction: bool = False,
    corrections: list | None = None,
    flagged: list | None = None,
    **_ignored: Any,
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
    res.flagged = flagged or []
    res.save(
        update_fields=[
            "status",
            "reason",
            "group_correction",
            "corrections",
            "flagged",
        ]
    )

    # Advance counters atomically
    counter = {
        "corrected": "corrected",
        "would_correct": "corrected",
        "consistent": "consistent",
        "no_text_amounts_found": "no_text",
        "afm_as_amount": "flagged",
        "kae_as_amount": "flagged",
        "non_monetary_value_as_amount": "flagged",
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
    ``correct_single_decision`` task each (carrying the job's ``mode``).
    """
    from core.models.amount_correction_job import (
        AmountCorrectionJob,
        AmountCorrectionJobResult,
        CorrectionJobStatus,
    )

    try:
        job = AmountCorrectionJob.objects.get(job_id=job_id)
    except AmountCorrectionJob.DoesNotExist:
        logger.error(f"run_amount_correction_job: job {job_id} not found")
        return {"status": "error", "reason": "job_not_found"}

    job.mark_started(celery_task_id=self.request.id)

    try:
        decision_ids = _resolve_candidate_ids(job)

        job.total_candidates = len(decision_ids)
        job.save(update_fields=["total_candidates", "updated_at"])

        if not decision_ids:
            job.mark_completed()
            return {"status": "completed", "total": 0}

        # Placeholder results, then fan out
        for decision_id in decision_ids:
            res = AmountCorrectionJobResult.objects.create(
                job=job, decision_id=decision_id, status="pending"
            )
            correct_single_decision.delay(
                decision_id=decision_id,
                dry_run=job.dry_run,
                read_if_missing=job.read_if_missing,
                job_result_id=res.id,
                mode=job.mode,
            )

        job.status = CorrectionJobStatus.RUNNING
        job.save(update_fields=["status", "updated_at"])
        logger.info(
            f"AmountCorrectionJob {job_id}: fanned out "
            f"{len(decision_ids)} decisions (mode={job.mode})"
        )
        return {"status": "running", "total": len(decision_ids), "mode": job.mode}

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
        # Invalidate analytics caches if anything was corrected OR flagged
        # (a flagged row drops out of every monetary aggregation, so cached
        # totals computed before the sweep are stale either way).
        if (job.corrected or job.flagged) and not job.dry_run:
            from core.services.response_cache_service import response_cache
            response_cache.invalidate_prefix("top_")
        return {"status": "completed"}

    return {"status": "running", "processed": job.processed_count}


@shared_task(name="amount_correction.daily")
def daily_amount_correction() -> dict[str, Any]:
    """
    Scheduled daily run — creates a job that APPLIES corrections
    (dry_run=False) over high-value decisions and runs it.

    Scoped to decisions imported in the last 2 days (created_at) so the
    daily job covers yesterday's + today's imports without re-scanning the
    entire historical backlog.

    NOTE: this duplicates post-import Phase 2
    (``tasks_post_import.verify_high_value_amounts``) — enabling both makes
    every decision be corrected twice, and the second pass re-downloads the
    PDF.  Keep exactly one of them enabled.
    """
    from datetime import timedelta

    from django.utils import timezone as dj_timezone

    from core.models.amount_correction_job import (
        AmountCorrectionJob,
        CorrectionJobMode,
    )
    from core.services.amount_correction_service import (
        DEFAULT_CORRECTION_THRESHOLD,
    )

    job = AmountCorrectionJob.objects.create(
        mode=CorrectionJobMode.DECIMAL_SHIFT,
        threshold=DEFAULT_CORRECTION_THRESHOLD,
        dry_run=False,          # apply corrections
        read_if_missing=True,
        limit=500,
        imported_since=dj_timezone.now() - timedelta(days=2),
    )
    run_amount_correction_job.delay(job_id=str(job.job_id))
    logger.info(f"Daily amount correction job {job.job_id} created")
    return {"job_id": str(job.job_id)}
