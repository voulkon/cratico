from core.models.decisions import Decision
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "decision_id",
            openapi.IN_PATH,
            description="Decision ID (integer)",
            type=openapi.TYPE_INTEGER,
            required=True,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def get_document_content_api_dev(request, decision_id):
    """Get document content / extraction status for a specific decision by ID.

    Returns 200 with ``status`` field in all cases so the frontend can poll:
    - ``COMPLETED``: ``raw_text`` and metadata are present.
    - ``PENDING`` / ``PROCESSING`` / ``FAILED``: status-only response (poll).
    - ``NOT_FOUND``: no DocumentExtraction row exists yet (show CTA).
    """
    try:
        from core.models.document_analysis import DocumentExtraction

        decision = Decision.objects.get(id=decision_id)

        try:
            extraction = DocumentExtraction.objects.get(decision=decision)

            base = {
                "decision_id": decision_id,
                "ada": decision.ada,
                "status": extraction.extraction_status,
                "extraction_provider": extraction.extraction_provider,
                "extraction_date": (
                    extraction.extraction_date.isoformat()
                    if extraction.extraction_date
                    else None
                ),
                "character_count": extraction.character_count,
                "page_count": extraction.page_count,
                "is_scanned_document": extraction.is_scanned_document,
                "processing_time_ms": extraction.processing_time_ms,
                "error_message": extraction.error_message,
            }

            if extraction.extraction_status == "COMPLETED" and extraction.raw_text:
                base["raw_text"] = extraction.raw_text
                return Response(base)

            # PENDING, PROCESSING, FAILED, NEEDS_VISION, etc. —
            # return 200 so the frontend can poll without treating it as an error.
            return Response(base)

        except DocumentExtraction.DoesNotExist:
            return Response(
                {
                    "decision_id": decision_id,
                    "ada": decision.ada,
                    "status": "NOT_FOUND",
                }
            )

    except Decision.DoesNotExist:
        return Response({"error": "Decision not found"}, status=404)
    except Exception as e:
        return Response(
            {
                "error": "Internal server error",
                "details": str(e) if settings.DEBUG else "An error occurred",
            },
            status=500,
        )
