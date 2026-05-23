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
    """Get document content for a specific decision by ID"""
    try:
        from core.models.document_analysis import DocumentExtraction

        # Get the decision by integer ID - much simpler!
        decision = Decision.objects.get(id=decision_id)

        try:
            extraction = DocumentExtraction.objects.get(decision=decision)

            # Only return content if extraction was successful
            if extraction.extraction_status == "COMPLETED" and extraction.raw_text:
                return Response(
                    {
                        "decision_id": decision_id,
                        "ada": decision.ada,  # Still include ADA for reference
                        "raw_text": extraction.raw_text,
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
                        "status": extraction.extraction_status,
                    }
                )
            else:
                return Response(
                    {
                        "error": "Document content not available",
                        "status": extraction.extraction_status,
                        "reason": "Extraction not completed or no text extracted",
                    },
                    status=404,
                )

        except DocumentExtraction.DoesNotExist:
            return Response(
                {
                    "error": "Document extraction not found",
                    "reason": "No document has been processed for this decision",
                },
                status=404,
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
