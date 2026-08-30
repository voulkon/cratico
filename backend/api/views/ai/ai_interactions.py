"""
AI Interactions API endpoints.

- GET  /api/ai/interactions/          — paginated list for current user
- GET  /api/ai/interactions/summary/  — aggregates (total cost, tokens, by-provider)
- GET  /api/ai/interactions/<id>/     — detail
- GET  /api/ai/interactions/system-report/?month=YYYY-MM — admin: re-invoicing CSV
"""

import csv
from datetime import date

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAdminUser, IsAuthenticated
from rest_framework.response import Response

from core.models.ai_interaction_log import AIInteractionLog
from core.services.cost_ledger_service import CostLedgerService


def _serialize_log(log: AIInteractionLog) -> dict:
    return {
        "id": log.id,
        "user": log.user_id,
        "billed_to": log.billed_to,
        "trigger": log.trigger,
        "trigger_ref": log.trigger_ref,
        "provider": log.provider,
        "model_name": log.model_name,
        "input_tokens": log.input_tokens,
        "output_tokens": log.output_tokens,
        "cost_usd": str(log.cost_usd),
        "latency_ms": log.latency_ms,
        "status": log.status,
        "error_message": log.error_message,
        "pipeline_run": log.pipeline_run_id,
        "pipeline_step_run": log.pipeline_step_run_id,
        "created_at": log.created_at,
    }


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def interactions_list(request):
    """Paginated list of AI interactions for the current user."""
    qs = AIInteractionLog.objects.filter(user=request.user)

    # Filters
    provider = request.GET.get("provider")
    if provider:
        qs = qs.filter(provider__iexact=provider)
    model_name = request.GET.get("model")
    if model_name:
        qs = qs.filter(model_name__icontains=model_name)
    trigger = request.GET.get("trigger")
    if trigger:
        qs = qs.filter(trigger__iexact=trigger)
    date_from = request.GET.get("date_from")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)
    date_to = request.GET.get("date_to")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    page_size = int(request.GET.get("page_size", 50))
    page = int(request.GET.get("page", 1))
    offset = (page - 1) * page_size
    total = qs.count()
    items = list(qs[offset : offset + page_size])

    return Response(
        {
            "count": total,
            "page": page,
            "page_size": page_size,
            "results": [_serialize_log(l) for l in items],
        }
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def interactions_summary(request):
    """Aggregates: total cost, tokens, count, by-provider breakdown."""
    month_str = request.GET.get("month")  # YYYY-MM
    month = None
    if month_str:
        try:
            parts = month_str.split("-")
            month = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            return Response(
                {"error": "Invalid month format. Use YYYY-MM."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    spend = CostLedgerService.get_user_spend(request.user, month=month)
    # Convert Decimal to str for JSON
    spend["total_cost_usd"] = str(spend["total_cost_usd"])
    for prov in spend["by_provider"].values():
        prov["cost"] = str(prov["cost"])
    return Response(spend)


def _serialize_log_detailed(log: AIInteractionLog) -> dict:
    """Serialize a log with input/output from the linked pipeline step run."""
    data = _serialize_log(log)

    # Pull prompt/response from the linked PipelineStepRun, if any
    step_run = log.pipeline_step_run
    if step_run is not None:
        data["input_preview"] = step_run.input_preview
        data["output_text"] = step_run.output_text
    else:
        data["input_preview"] = None
        data["output_text"] = None

    return data


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def interactions_detail(request, pk: int):
    """Detail of a single interaction (must belong to the user)."""
    try:
        log = AIInteractionLog.objects.select_related("pipeline_step_run").get(
            pk=pk, user=request.user
        )
    except AIInteractionLog.DoesNotExist:
        return Response({"error": "Not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(_serialize_log_detailed(log))


@api_view(["GET"])
@permission_classes([IsAdminUser])
def interactions_system_report(request):
    """Admin: CSV report of all SYSTEM-billed rows for re-invoicing."""
    month_str = request.GET.get("month")
    month = None
    if month_str:
        try:
            parts = month_str.split("-")
            month = date(int(parts[0]), int(parts[1]), 1)
        except (ValueError, IndexError):
            return Response(
                {"error": "Invalid month format. Use YYYY-MM."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    qs = AIInteractionLog.objects.filter(billed_to="SYSTEM").select_related("user")
    if month:
        qs = qs.filter(created_at__year=month.year, created_at__month=month.month)
    else:
        now = timezone.now()
        qs = qs.filter(created_at__year=now.year, created_at__month=now.month)

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="ai_system_spend.csv"'
    writer = csv.writer(response)
    writer.writerow(
        [
            "user_id",
            "email",
            "provider",
            "model",
            "tokens_in",
            "tokens_out",
            "cost_usd",
            "trigger",
            "date",
        ]
    )
    for log in qs:
        writer.writerow(
            [
                log.user_id,
                log.user.email if log.user else "",
                log.provider,
                log.model_name,
                log.input_tokens,
                log.output_tokens,
                log.cost_usd,
                log.trigger,
                log.created_at.isoformat(),
            ]
        )
    return response
