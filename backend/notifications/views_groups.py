"""Read-only API for presentation/email batch groups.

Groups own no AI summary fields.  The summary endpoint is a thin composition
over the batches' snapshots plus the shared one-liner cache; it never calls a
provider.
"""

from django.db.models import Count, Max, Min, Sum
from django.utils.dateparse import parse_date
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.services.decision_projections import (
    build_decision_card_context,
    build_shareable_one_liners_by_decision,
)
from notifications.models import NotificationBatchDecision, NotificationBatchGroup
from notifications.serializers import (
    NotificationBatchDecisionSerializer,
    NotificationBatchGroupDetailSerializer,
    NotificationBatchGroupListSerializer,
)


class NotificationBatchGroupViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        if not self.request.user or not self.request.user.is_authenticated:
            return NotificationBatchGroup.objects.none()

        queryset = (
            NotificationBatchGroup.objects.filter(user=self.request.user)
            .select_related(
                "subscription",
                "subscription__organization",
                "subscription__entity",
            )
            .prefetch_related("batches", "batches__subscription")
            .annotate(
                decision_publish_start=Min(
                    "batches__batch_decisions__decision__publish_timestamp"
                ),
                decision_publish_end=Max(
                    "batches__batch_decisions__decision__publish_timestamp"
                ),
            )
            .order_by("-period_end")
        )

        local_date = parse_date(
            self.request.query_params.get("local_date", "")
        )
        if local_date is not None:
            queryset = queryset.filter(local_date=local_date)
        return queryset

    @action(detail=False, methods=["get"], url_path="periods")
    def periods(self, request):
        """Distinct digest periods that have groups for the current user.

        The in-app notification page uses this to move to the previous/next
        period that actually has notifications instead of walking empty days.
        """
        rows = (
            NotificationBatchGroup.objects.filter(user=request.user)
            .values("period_start", "period_end", "local_date")
            .annotate(
                group_count=Count("id"),
                total_match_count=Sum("total_match_count"),
            )
            .order_by("-period_end")
        )
        return Response(list(rows))

    def get_serializer_class(self):
        if self.action == "list":
            return NotificationBatchGroupListSerializer
        return NotificationBatchGroupDetailSerializer

    @action(detail=True, methods=["get"], url_path="decisions")
    def decisions(self, request, pk=None):
        """Paginated decisions across every batch in the group."""
        from api.utils.sorting import apply_decision_sorting

        group = self.get_object()
        queryset = NotificationBatchDecision.objects.filter(
            batch__group=group
        ).select_related(
            "decision", "decision__organization", "decision__decision_type"
        ).prefetch_related(
            "decision__signers",
            "decision__kae_amounts",
            "decision__text_extraction",
            "decision__ai_analyses",
        )

        is_viewed = request.query_params.get("is_viewed")
        if is_viewed is not None:
            queryset = queryset.filter(is_viewed=is_viewed.lower() == "true")

        queryset = apply_decision_sorting(
            queryset,
            request.query_params.get("sort", "recent"),
            amount_field="decision__amount",
            date_field="decision__issue_date",
        )

        paginator = PageNumberPagination()
        paginator.page_size = min(
            int(request.query_params.get("page_size", 20)), 100
        )
        page = paginator.paginate_queryset(queryset, request)
        page_ids = [nbd.decision_id for nbd in page] if page is not None else []
        context = build_decision_card_context(page_ids)
        context["one_liners_by_decision"] = (
            build_shareable_one_liners_by_decision(page_ids)
        )

        if page is not None:
            serializer = NotificationBatchDecisionSerializer(
                page, many=True, context=context
            )
            return paginator.get_paginated_response(serializer.data)

        return Response(
            NotificationBatchDecisionSerializer(
                queryset, many=True, context=context
            ).data
        )

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        """Read-only composition of batch snapshots + shared one-liners."""
        group = self.get_object()
        batches = list(group.batches.all())

        statuses = [batch.ai_summary_status for batch in batches]
        if "RUNNING" in statuses:
            status = "RUNNING"
        elif "COMPLETED" in statuses:
            status = "COMPLETED"
        elif "PARTIAL" in statuses:
            status = "PARTIAL"
        elif "PENDING" in statuses:
            status = "PENDING"
        elif "FAILED" in statuses:
            status = "FAILED"
        else:
            status = "SKIPPED"

        summary = next(
            (batch.ai_summary for batch in batches if batch.ai_summary), None
        )
        skip_reason = next(
            (
                batch.ai_summary_skip_reason
                for batch in batches
                if batch.ai_summary_skip_reason
            ),
            None,
        )
        error = next(
            (batch.ai_summary_error for batch in batches if batch.ai_summary_error),
            None,
        )
        completed_at = max(
            (
                batch.ai_summary_completed_at
                for batch in batches
                if batch.ai_summary_completed_at
            ),
            default=None,
        )

        decision_rows = list(
            NotificationBatchDecision.objects.filter(batch__group=group).values(
                "decision_id", "decision__ada", "decision__subject"
            )
        )
        shared = build_shareable_one_liners_by_decision(
            {row["decision_id"] for row in decision_rows}
        )

        items_by_decision = {}
        for batch in sorted(batches, key=lambda b: b.created_at):
            for item in batch.ai_summary_items or []:
                if item.get("decision_id"):
                    items_by_decision.setdefault(item["decision_id"], item)
        for row in decision_rows:
            if row["decision_id"] in items_by_decision:
                continue
            entry = shared.get(row["decision_id"])
            if entry:
                items_by_decision[row["decision_id"]] = {
                    "decision_id": row["decision_id"],
                    "ada": row["decision__ada"],
                    "subject": row["decision__subject"],
                    "one_liner": entry["one_liner"],
                }

        return Response(
            {
                "status": status,
                "skip_reason": skip_reason,
                "summary": summary,
                "error": error,
                "items": list(items_by_decision.values()),
                "shared_items_available": len(shared),
                "completed_at": completed_at,
            }
        )

    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        group = self.get_object()
        group.mark_as_read()
        return Response({"status": "marked as read", "group_id": group.id})

    @action(detail=True, methods=["post"], url_path="dismiss")
    def dismiss(self, request, pk=None):
        group = self.get_object()
        group.dismiss()
        return Response({"status": "dismissed", "group_id": group.id})
