"""
Decision-level AI processing Celery tasks.

Two separate, composable tasks:

1. ``extract_decision_text`` — download PDF → extract text → store in
   ``DocumentExtraction``.  Standalone, no AI involved.

2. ``process_decision_ai`` — runs the AI pipeline (EXTRACT → AI_CALL) on a
   single decision.  Depends on extraction being done first (triggers it if
   needed).

Both are idempotent: re-requesting an already-completed step is a no-op.
"""

from loguru import logger

from celery import shared_task


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_completed_analysis(decision_id: int, *, force: bool = False, model: str | None = None) -> bool:
    """
    Return True if *decision_id* already has a completed AI summary
    and we are not forcing regeneration.

    When *model* is provided, only considers analyses that used that model.
    """
    if force:
        return False
    from core.models.decision_ai_analysis import AnalysisStatus, DecisionAIAnalysis
    qs = DecisionAIAnalysis.objects.filter(
        decision_id=decision_id,
        status=AnalysisStatus.COMPLETED,
    ).exclude(summary="")
    if model:
        qs = qs.filter(model_used=model)
    return qs.exists()


def _needs_text_extraction(decision) -> bool:
    """
    Return True if *decision* has no usable extracted text yet.
    """
    from core.models.document_analysis import ProcessingStatus
    extraction = getattr(decision, "text_extraction", None)
    if extraction is None:
        return True
    if extraction.extraction_status != ProcessingStatus.COMPLETED:
        return True
    if not extraction.raw_text:
        return True
    return False


def _resolve_user(user_id: int):
    """Resolve a user by ID for billing attribution.  Raises if not found."""
    if not user_id:
        raise ValueError("user_id is required for billing attribution")
    from users.models import CustomUser

    user = CustomUser.objects.filter(id=user_id).first()
    if user is None:
        raise ValueError(f"User id={user_id} not found; cannot attribute billing")
    return user


def _extract_pipeline_output(context, run) -> str | None:
    """
    Extract the final output text from a *completed* pipeline run.

    Only returns output when the run succeeded — partial outputs from a
    failed run are never surfaced as the final result.
    """
    from core.models.pipeline import RunStatus
    if run.status != RunStatus.COMPLETED:
        return None
    if context.steps_output:
        return context.steps_output[max(context.steps_output.keys())]
    last_step = run.step_runs.order_by("-order").first()
    return last_step.output_text if last_step else None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

@shared_task(bind=True, max_retries=2)
def extract_decision_text(self, decision_id: int, provider: str = None):
    """
    Extract text from a decision's PDF document.

    Uses ``DocumentAnalysisService.process_decision()`` which handles
    downloading, extraction, and storing to ``DocumentExtraction``.

    Args:
        decision_id: Primary key of the Decision.
        provider: Optional extraction provider (e.g. ``"PYMUPDF"``, ``"DOCLING"``).
                  Defaults to the system-wide default (PyMuPDF).

    Returns:
        dict with keys: decision_id, status, extraction_id, character_count
    """
    from core.models.decisions import Decision
    from core.models.document_analysis import DocumentExtraction, ProcessingStatus
    from core.services.document_processor import DocumentAnalysisService

    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        logger.error(f"extract_decision_text: decision {decision_id} not found")
        return {"decision_id": decision_id, "status": "not_found"}

    # Check if already extracted (with matching provider if specified)
    qs = DocumentExtraction.objects.filter(
        decision=decision,
        extraction_status=ProcessingStatus.COMPLETED,
    )
    if provider:
        qs = qs.filter(extraction_provider=provider)
    existing = qs.first()

    if existing and existing.raw_text:
        logger.info(f"Decision {decision_id}: text already extracted ({existing.character_count} chars, provider={existing.extraction_provider})")
        return {
            "decision_id": decision_id,
            "status": "already_extracted",
            "extraction_id": existing.id,
            "character_count": existing.character_count,
            "extraction_provider": existing.extraction_provider,
        }

    if not decision.document_url:
        logger.warning(f"Decision {decision_id}: no document URL")
        return {"decision_id": decision_id, "status": "no_document_url"}

    # Run extraction
    doc_service = DocumentAnalysisService()
    result = doc_service.process_decision(decision, provider=provider)

    if not result.get("success"):
        error_msg = result.get("error", "extraction failed")
        logger.error(f"Decision {decision_id}: extraction failed: {error_msg}")
        return {"decision_id": decision_id, "status": "failed", "error": error_msg}

    # Get the extraction record
    extraction = DocumentExtraction.objects.filter(decision=decision).first()

    logger.info(
        f"Decision {decision_id}: text extracted "
        f"({extraction.character_count if extraction else 0} chars, provider={extraction.extraction_provider if extraction else 'unknown'})"
    )
    return {
        "decision_id": decision_id,
        "status": "extracted",
        "extraction_id": extraction.id if extraction else None,
        "character_count": extraction.character_count if extraction else 0,
        "extraction_provider": extraction.extraction_provider if extraction else None,
    }


@shared_task(bind=True, max_retries=2)
def process_decision_ai(self, decision_id: int, user_id: int, provider: str = None, force: bool = False, model: str | None = None):
    """
    Run AI summarization on a single decision.

    Pipeline: EXTRACT (read cached text) → AI_CALL (summarize).
    The result is stored on ``DecisionAIAnalysis`` and the run is recorded
    via ``PipelineRun`` / ``AIInteractionLog``.

    Args:
        decision_id: Primary key of the Decision to process.
        user_id: Optional user for billing attribution.
        provider: Optional extraction provider (e.g. ``"PYMUPDF"``).
        force: If True, re-run even if a completed analysis exists (regeneration).
        model: Optional model override (e.g. ``"openai/gpt-4o"``).  When set,
               overrides the user's preferred model and pipeline default.

    Returns:
        dict with keys: decision_id, status, analysis_id, cost_usd
    """
    from core.models.decision_ai_analysis import AnalysisStatus, DecisionAIAnalysis
    from core.models.decisions import Decision
    from core.models.pipeline import RunStatus
    from core.services.pipeline_engine import PipelineContext, PipelineEngine

    # Map PipelineRun RunStatus → AnalysisStatus (defensive: unknown → FAILED)
    _STATUS_MAP = {
        RunStatus.PENDING: AnalysisStatus.PENDING,
        RunStatus.RUNNING: AnalysisStatus.RUNNING,
        RunStatus.COMPLETED: AnalysisStatus.COMPLETED,
        RunStatus.FAILED: AnalysisStatus.FAILED,
    }

    def _finish(queue_status: str, error: str = ""):
        """Report completion/failure back to the Redis queue."""
        from core.services.decision_processing_queue import DecisionProcessingQueue
        queue = DecisionProcessingQueue()
        if queue_status == "completed":
            queue.on_completed(decision_id)
        else:
            queue.on_failed(decision_id, error)

    try:
        decision = Decision.objects.select_related("text_extraction").get(id=decision_id)
    except Decision.DoesNotExist:
        logger.error(f"process_decision_ai: decision {decision_id} not found")
        _finish("failed", "decision not found")
        return {"decision_id": decision_id, "status": "not_found"}

    # --- Early-exit: already analysed (unless forcing regeneration) ---
    if _has_completed_analysis(decision_id, force=force, model=model):
        logger.info(f"Decision {decision_id}: AI analysis already completed (model={model or 'default'})")
        _finish("completed")
        existing_qs = DecisionAIAnalysis.objects.filter(
            decision_id=decision_id, status=AnalysisStatus.COMPLETED
        )
        if model:
            existing_qs = existing_qs.filter(model_used=model)
        existing = existing_qs.only("cost_usd").order_by("-created_at").first()
        return {
            "decision_id": decision_id,
            "status": "already_completed",
            "analysis_id": existing.pk if existing else None,
            "cost_usd": str(existing.cost_usd or 0),
        }

    # --- Ensure text is extracted ---
    if _needs_text_extraction(decision):
        logger.info(f"Decision {decision_id}: text not extracted, triggering extraction first")
        extract_result = extract_decision_text(decision_id, provider=provider)
        if extract_result.get("status") not in ("extracted", "already_extracted"):
            error_msg = extract_result.get("error", "Could not extract text")
            _finish("failed", error_msg)
            return {
                "decision_id": decision_id,
                "status": "extraction_failed",
                "error": error_msg,
            }
        decision.refresh_from_db()

    # --- Create a new analysis record for this run ---
    analysis = DecisionAIAnalysis.objects.create(
        decision=decision,
        status=AnalysisStatus.RUNNING,
        model_used=model or "",  # Set early if explicitly chosen; pipeline resolves otherwise
    )

    # --- Resolve user for billing ---
    user = _resolve_user(user_id)

    try:
        pipeline_def = _get_or_create_simple_summary_pipeline()

        context = PipelineContext(
            decisions=[decision],
            user=user,
        )
        if model:
            context.metadata["model_override"] = model
        engine = PipelineEngine()
        run = engine.run(
            pipeline_def,
            context,
            trigger="decision_ai_summary",
            trigger_ref=f"decision:{decision_id}",
        )

        final_output = _extract_pipeline_output(context, run)

        # Store on analysis record
        analysis.pipeline_run = run
        analysis.status = _STATUS_MAP.get(run.status, AnalysisStatus.FAILED)
        analysis.summary = final_output
        analysis.completed_at = run.completed_at
        analysis.cost_usd = run.total_cost_usd
        analysis.input_tokens = run.total_input_tokens
        analysis.output_tokens = run.total_output_tokens
        analysis.model_used = context.metadata.get("model_used")
        analysis.error_message = run.error_message if analysis.status == AnalysisStatus.FAILED else None
        analysis.save()

        if analysis.status == AnalysisStatus.COMPLETED:
            _finish("completed")
        else:
            _finish("failed", run.error_message or f"pipeline status: {run.status}")

        logger.info(
            f"Decision {decision_id}: AI summary {analysis.status} "
            f"(cost: ${run.total_cost_usd}, tokens: {run.total_input_tokens}+{run.total_output_tokens})"
        )
        return {
            "decision_id": decision_id,
            "status": analysis.status,
            "analysis_id": analysis.decision_id,
            "pipeline_run_id": run.id,
            "cost_usd": str(run.total_cost_usd),
        }

    except Exception as exc:
        logger.error(f"process_decision_ai failed for decision {decision_id}: {exc}", exc_info=True)
        analysis.status = AnalysisStatus.FAILED
        analysis.error_message = str(exc)[:500]
        analysis.save(update_fields=["status", "error_message"])
        if self.request.retries >= self.max_retries:
            # Retries exhausted — release from queue permanently
            _finish("failed", str(exc)[:300])
            return {"decision_id": decision_id, "status": "failed", "error": str(exc)[:300]}
        raise self.retry(exc=exc, countdown=60)


def _get_or_create_simple_summary_pipeline():
    """
    Get or create the simple single-decision AI summary pipeline.

    Steps:
    1. EXTRACT — read cached DocumentExtraction.raw_text
    2. AI_CALL — summarize (single call, not map mode)
    """
    from core.models.pipeline import PipelineDefinition, PipelineStep

    pipeline, created = PipelineDefinition.objects.get_or_create(
        name="simple_summary_v1",
        defaults={
            "version": 1,
            "description": "Single-decision AI summary pipeline",
            "is_active": True,
            "trigger_type": "decision_ai_summary",
        },
    )

    if created:
        PipelineStep.objects.create(
            pipeline=pipeline,
            order=1,
            step_type="EXTRACT",
            name="Extract document text",
            config={
                "extractor": "PYMUPDF",
                "re_extract": False,
                "max_chars": 50000,
            },
        )
        PipelineStep.objects.create(
            pipeline=pipeline,
            order=2,
            step_type="AI_CALL",
            name="Summarize decision",
            config={
                "provider": "OPENROUTER",
                "model": "qwen/qwen3.7-flash",
                "map_over_items": False,
                "system_prompt": (
                    "You are a legal analyst specializing in Greek government decisions (Διαύγεια). "
                    "Summarize the decision concisely in the same language as the original text. "
                    "Include: (1) who issued it, (2) what was decided, (3) key financial amounts if any, "
                    "(4) the legal basis referenced. Keep the summary to 3-5 short paragraphs."
                ),
                "prompt_template": "Summarize this decision:\n{{ text }}",
                "temperature": 0.3,
                "max_tokens": 1000,
            },
        )
        logger.info("Created default simple_summary_v1 pipeline")

    return pipeline


@shared_task(bind=True, max_retries=1)
def consume_decision_queue(self):
    """
    Periodic consumer task — polls the Redis queue and processes the next
    batch of decisions.

    This is the "while true" loop equivalent: it processes one batch per
    invocation and re-schedules itself if there is more work pending.

    Schedule it via Celery Beat every ~30 seconds, or call ``.delay()``
    after enqueuing to kick off immediate processing.
    """
    from core.services.decision_processing_queue import DecisionProcessingQueue

    queue = DecisionProcessingQueue()
    result = queue.process_batch()

    # If there are still pending items and we dispatched nothing (locked),
    # schedule a retry shortly.  If we dispatched items, the next beat tick
    # will pick up the rest.
    if result.get("status") == "locked":
        logger.debug("Decision queue consumer: locked, retrying in 10s")
        raise self.retry(countdown=10)
    elif result.get("status") == "empty":
        logger.debug(f"Decision queue consumer: empty (pending={result.get('pending', 0)})")

    return result
