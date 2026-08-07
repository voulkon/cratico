"""
Celery tasks for asynchronous text process execution.

Sync methods (regex) run inline in the API process.  Async methods (AI/LLM)
are dispatched here so they don't block the web request.
"""

from celery import shared_task
from loguru import logger


@shared_task(
    bind=True,
    max_retries=1,
    default_retry_delay=30,
    name="text_process.execute",
)
def execute_text_process(
    self,
    run_id: int,
    process_slug: str,
    method: str = "ai",
    params: dict | None = None,
) -> dict:
    """
    Execute a text process asynchronously on a Celery worker.

    The ``TextProcessRun`` row already exists in RUNNING status (created by
    ``TextProcessService.run_process()``).  This task runs ``detect()``,
    persists spans, and marks the run COMPLETED or FAILED.
    """
    from core.models.document_analysis import TextProcessRun, TextProcessStatus
    from core.services.text_process_service import TextProcessService
    from core.services.text_processes import TEXT_PROCESSES

    try:
        run = TextProcessRun.objects.select_related("extraction").get(id=run_id)
    except TextProcessRun.DoesNotExist:
        logger.error(f"TextProcessRun {run_id} not found — cannot execute")
        return {"status": "error", "reason": "run_not_found"}

    process_cls = TEXT_PROCESSES.get(process_slug)
    if not process_cls:
        run.status = TextProcessStatus.FAILED
        run.error_message = f"Unknown process: {process_slug!r}"
        run.save()
        return {"status": "error", "reason": "unknown_process"}

    text = run.extraction.raw_text or ""
    process = process_cls()

    try:
        result = process.detect(text, method=method, **(params or {}))

        run.meta = {**(run.meta or {}), **result.meta}
        if result.success:
            TextProcessService()._save_spans(run, result.spans)
            run.status = TextProcessStatus.COMPLETED
            run.error_message = None
        else:
            run.status = TextProcessStatus.FAILED
            run.error_message = (result.error or "process failed")[:500]
    except Exception as exc:
        run.status = TextProcessStatus.FAILED
        run.error_message = str(exc)[:500]
        logger.error(
            f"Async {process_slug} run {run.id} failed: {exc}",
            exc_info=True,
        )

    run.save()
    return {
        "status": run.status.lower(),
        "run_id": run.id,
        "process": process_slug,
    }
