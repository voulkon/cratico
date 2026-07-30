"""
Decision AI API endpoints — user-triggered extraction and AI analysis.

- POST /api/ai/decisions/<id>/extract/       — request text extraction
- POST /api/ai/decisions/<id>/summarize/     — request AI summary
- GET  /api/ai/decisions/<id>/analysis/     — get analysis status + result
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models.decision_ai_analysis import AnalysisStatus, DecisionAIAnalysis
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_extraction(request, decision_id: int):
    """
    Request text extraction for a decision.

    Idempotent: returns immediately if text is already extracted.
    Dispatches a Celery task if extraction is needed.
    """
    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=status.HTTP_404_NOT_FOUND)

    # Check if already extracted
    extraction = DocumentExtraction.objects.filter(
        decision=decision,
        extraction_status=ProcessingStatus.COMPLETED,
    ).first()

    if extraction and extraction.raw_text:
        return Response({
            "decision_id": decision_id,
            "status": "already_extracted",
            "character_count": extraction.character_count,
            "page_count": extraction.page_count,
            "extraction_provider": extraction.extraction_provider,
        })

    if not decision.document_url:
        return Response(
            {"error": "Decision has no document URL"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Enqueue via the queue service for concurrency control
    from core.services.decision_processing_queue import DecisionProcessingQueue

    queue = DecisionProcessingQueue()
    result = queue.enqueue(decision_id, user_id=request.user.id)

    # Kick the consumer to pick up this (and any other pending) work
    from core.tasks.tasks_decision_ai import consume_decision_queue
    consume_decision_queue.delay()

    http_status = status.HTTP_202_ACCEPTED if result["status"] == "enqueued" else status.HTTP_200_OK
    return Response(result, status=http_status)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_summary(request, decision_id: int):
    """
    Request AI summarization for a decision.

    Idempotent: returns cached result if already completed.
    Pass ``{"force": true}`` in the body to regenerate (re-run the pipeline).
    Enqueues via the queue service for concurrency control.
    """
    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=status.HTTP_404_NOT_FOUND)

    force = bool(request.data.get("force", False))

    # Check if already completed
    existing = DecisionAIAnalysis.objects.filter(
        decision=decision,
        status=AnalysisStatus.COMPLETED,
    ).order_by("-created_at").first()

    if existing and existing.summary and not force:
        return Response({
            "decision_id": decision_id,
            "status": "already_completed",
            "summary": existing.summary,
            "cost_usd": str(existing.cost_usd or 0),
            "model_used": existing.model_used,
            "completed_at": existing.completed_at,
        })

    if force and existing:
        # With the FK model, force means "create a new analysis row" — the
        # task will do that.  We just skip the early-return below.
        pass

    # Check if currently running
    running = DecisionAIAnalysis.objects.filter(
        decision=decision,
        status=AnalysisStatus.RUNNING,
    ).first()

    if running:
        return Response({
            "decision_id": decision_id,
            "status": "already_running",
        }, status=status.HTTP_202_ACCEPTED)

    # Enqueue via the queue service
    from core.services.decision_processing_queue import DecisionProcessingQueue

    queue = DecisionProcessingQueue()
    result = queue.enqueue(decision_id, user_id=request.user.id, force=force)

    # Kick the consumer
    from core.tasks.tasks_decision_ai import consume_decision_queue
    consume_decision_queue.delay()

    http_status = status.HTTP_202_ACCEPTED if result["status"] == "enqueued" else status.HTTP_200_OK
    return Response(result, status=http_status)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_analysis(request, decision_id: int):
    """
    Get the AI analysis status and result for a decision.

    Returns the full analysis record including extraction status.
    """
    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=status.HTTP_404_NOT_FOUND)

    # Extraction info
    extraction = DocumentExtraction.objects.filter(decision=decision).first()
    extraction_data = None
    if extraction:
        extraction_data = {
            "status": extraction.extraction_status,
            "character_count": extraction.character_count,
            "page_count": extraction.page_count,
            "provider": extraction.extraction_provider,
            "extracted_at": extraction.extraction_date,
        }

    # AI analysis info (latest, regardless of status)
    analysis = (
        DecisionAIAnalysis.objects
        .filter(decision=decision)
        .order_by("-created_at")
        .first()
    )
    analysis_data = None
    if analysis:
        analysis_data = {
            "status": analysis.status,
            "summary": analysis.summary,
            "cost_usd": str(analysis.cost_usd) if analysis.cost_usd else None,
            "input_tokens": analysis.input_tokens,
            "output_tokens": analysis.output_tokens,
            "model_used": analysis.model_used,
            "error_message": analysis.error_message,
            "completed_at": analysis.completed_at,
            "pipeline_run_id": analysis.pipeline_run_id,
        }

    return Response({
        "decision_id": decision_id,
        "extraction": extraction_data,
        "analysis": analysis_data,
    })
