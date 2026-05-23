from core.models.decisions import Decision
from core.models.document_analysis import (
    DocumentAnalysis,
    DocumentExtraction,
    ProcessingProvider,
    ProcessingStatus,
)
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response


class DocumentAnalysisViewSet(viewsets.ViewSet):
    """API endpoints for document analysis"""

    @action(detail=True, methods=["post"])
    def process(self, request, pk=None):
        """Trigger document processing for a decision asynchronously"""
        decision = get_object_or_404(Decision, ada=pk)

        # Get provider from request data, if specified
        provider = request.data.get("provider", None)

        # Validate provider if specified
        if provider and provider not in ProcessingProvider:
            return Response(
                {
                    "status": "error",
                    "message": f"Invalid provider. Choose from: {', '.join(ProcessingProvider.values)}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if already being processed to avoid duplicate tasks
        extraction = DocumentExtraction.objects.filter(decision=decision).first()
        if extraction and extraction.extraction_status == ProcessingStatus.PROCESSING:
            return Response(
                {
                    "status": "already_processing",
                    "message": "Document is already being processed",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Queue the async task rather than processing immediately
        from core.tasks import process_document_task

        task = process_document_task.delay(decision.ada, provider)

        return Response(
            {
                "status": "queued",
                "task_id": task.id,
                "message": "Document has been queued for processing",
            }
        )

    @action(detail=True, methods=["get"])
    def extraction(self, request, pk=None):
        """Get text extraction for a decision"""
        decision = get_object_or_404(Decision, ada=pk)
        try:
            extraction = DocumentExtraction.objects.get(decision=decision)
            data = {
                "status": extraction.extraction_status,
                "provider": extraction.extraction_provider,
                "is_scanned": extraction.is_scanned_document,
                "page_count": extraction.page_count,
                "character_count": extraction.character_count,
                "text": extraction.raw_text,
                "extraction_date": extraction.extraction_date,
            }
            return Response(data)
        except DocumentExtraction.DoesNotExist:
            return Response(
                {"error": "No extraction found for this decision"},
                status=status.HTTP_404_NOT_FOUND,
            )

    @action(detail=True, methods=["get"])
    def analysis(self, request, pk=None):
        """Get all analysis results for a decision"""
        decision = get_object_or_404(Decision, ada=pk)
        analyses = DocumentAnalysis.objects.filter(decision=decision)

        data = {"ada": decision.ada, "analyses": []}

        for analysis in analyses:
            data["analyses"].append(
                {
                    "id": analysis.id,
                    "type": analysis.analysis_type,
                    "provider": analysis.provider,
                    "model": analysis.model_name,
                    "content": analysis.content,
                    "version": analysis.version,
                    "created_at": analysis.created_at,
                }
            )

        return Response(data)

    @action(detail=True, methods=["get"])
    def status(self, request, pk=None):
        """Get current processing status for a decision"""
        decision = get_object_or_404(Decision, ada=pk)

        try:
            extraction = DocumentExtraction.objects.get(decision=decision)
            data = {
                "ada": decision.ada,
                "status": extraction.extraction_status,
                "last_updated": extraction.updated_at,
                "error": (
                    extraction.error_message
                    if extraction.extraction_status == ProcessingStatus.FAILED
                    else None
                ),
                "has_text": bool(extraction.raw_text),
                "is_scanned": extraction.is_scanned_document,
            }

            # Include task info if available
            if hasattr(extraction, "task_id") and extraction.task_id:
                # If using Celery, you can check task status
                from core.tasks import process_document_task

                task = process_document_task.AsyncResult(extraction.task_id)
                data["task_status"] = task.status

            return Response(data)
        except DocumentExtraction.DoesNotExist:
            return Response(
                {
                    "ada": decision.ada,
                    "status": "not_started",
                    "message": "Document has not been processed yet",
                }
            )
