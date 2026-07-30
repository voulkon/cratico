"""
AI Pipelines API endpoints.

- GET /api/ai/pipelines/         — list active pipeline definitions
- GET /api/ai/pipelines/<id>/   — detail (with steps)
"""

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models.pipeline import PipelineDefinition


def _serialize_step(step) -> dict:
    return {
        "id": step.id,
        "order": step.order,
        "step_type": step.step_type,
        "name": step.name,
        "config": step.config,
        "is_active": step.is_active,
    }


def _serialize_pipeline(p: PipelineDefinition, include_steps: bool = False) -> dict:
    data = {
        "id": p.id,
        "name": p.name,
        "version": p.version,
        "description": p.description,
        "is_active": p.is_active,
        "trigger_type": p.trigger_type,
        "created_at": p.created_at,
        "updated_at": p.updated_at,
    }
    if include_steps:
        data["steps"] = [_serialize_step(s) for s in p.steps.all()]
    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pipelines_list(request):
    """List active pipeline definitions, optionally filtered by trigger_type."""
    qs = PipelineDefinition.objects.filter(is_active=True)
    trigger_type = request.GET.get("trigger_type")
    if trigger_type:
        qs = qs.filter(trigger_type=trigger_type)
    return Response([_serialize_pipeline(p) for p in qs])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def pipelines_detail(request, pk: int):
    """Detail of a single pipeline definition, including its steps."""
    try:
        p = PipelineDefinition.objects.get(pk=pk)
    except PipelineDefinition.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(_serialize_pipeline(p, include_steps=True))
