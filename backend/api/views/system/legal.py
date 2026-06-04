from core.models import LegalDocument
from core.utils.default_legal_content import get_available_types, get_default_legal_content
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


def _ensure_defaults_exist(language):
    """Create default legal documents for all known types if missing."""
    for doc_type in get_available_types():
        LegalDocument.get_or_create_default(doc_type, language)


@api_view(["GET"])
@permission_classes([AllowAny])
def get_legal_documents(request):
    """
    Get legal page content as markdown.

    Query params:
        - language: 'en' or 'el' (default: 'en')
        - type: filter to a specific document slug (e.g. 'tos', 'privacy')

    Without ``type``, returns a list of all available documents (summary only,
    no full content).  With ``type``, returns the full single document.
    """
    language = request.query_params.get("language", "en")
    if language not in ["en", "el"]:
        language = "en"

    # Ensure default documents exist for this language
    _ensure_defaults_exist(language)

    doc_type = request.query_params.get("type")

    if doc_type:
        # Return a single document with full content
        doc = LegalDocument.get_or_create_default(doc_type, language)
        return Response(
            {
                "type": doc.type,
                "title": doc.title,
                "language": doc.language,
                "content": doc.content,
                "updated_at": doc.updated_at,
            }
        )

    # Return list of all documents (summary only — no content).
    # Exclude legacy rows that have an empty type (from before the type/title migration).
    docs = LegalDocument.objects.filter(
        language=language
    ).exclude(type="").order_by("type")
    return Response(
        [
            {
                "type": doc.type,
                "title": doc.title,
                "updated_at": doc.updated_at,
            }
            for doc in docs
        ]
    )
