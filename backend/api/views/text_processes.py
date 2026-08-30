"""
Text process API — list available processes and trigger runs on demand.

- ``GET  /api/processes/``                     → list registered processes
- ``POST /api/decisions/<id>/processes/run/``  → run a process on a decision
"""

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.text_process_service import (
    TextProcessService,
    get_available_processes,
)
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from api.permissions import PublicReadOnly
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([PublicReadOnly])
def list_text_processes(request):
    """List all registered text processes (for the UI dropdown)."""
    return Response({"processes": get_available_processes()})


@api_view(["POST"])
@permission_classes([PublicReadOnly])
def run_text_process(request, decision_id):
    """
    Run a text process over a decision's extracted text.

    Body:
        process   (required) — process slug, e.g. "amount", "dates"
        method    (optional) — "regex" (default) or "ai"
        model     (optional) — model name for AI runs
        version   (optional) — version tag (default "1.0")
        params    (optional) — dict of process-specific params
        force     (optional) — re-run even if a completed run exists

    Returns the serialized run (with spans) once complete.  Regex processes
    run synchronously; AI processes may be queued (status PENDING/RUNNING)
    and the frontend polls ``/decisions/<id>/content/?include=spans``.
    """
    process_slug = request.data.get("process")
    if not process_slug:
        return Response({"error": "process is required"}, status=400)

    method = request.data.get("method", "regex")
    model = request.data.get("model")
    version = request.data.get("version", "1.0")
    params = request.data.get("params") or {}
    force = bool(request.data.get("force", False))

    try:
        decision = Decision.objects.get(id=decision_id)
    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)

    # Ensure we have an extraction to run against
    extraction = getattr(decision, "text_extraction", None)
    if (
        not extraction
        or extraction.extraction_status != ProcessingStatus.COMPLETED
        or not extraction.raw_text
    ):
        return Response(
            {
                "error": "no_text",
                "detail": (
                    "No extracted text available. Request text extraction first."
                ),
            },
            status=409,
        )

    svc = TextProcessService()
    try:
        run = svc.run_process(
            extraction,
            process_slug,
            method=method,
            model=model,
            version=version,
            params=params,
            user=request.user if request.user.is_authenticated else None,
            force=force,
        )
    except ValueError as exc:
        return Response({"error": str(exc)}, status=400)

    return Response(svc.serialize_run(run), status=200)
