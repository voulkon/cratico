from core.models import LegalDocument
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def get_legal_documents(request):
    """
    Get the full legal page content as markdown.

    Query params:
        - language: 'en' or 'el' (default: 'en')
    """
    language = request.query_params.get("language", "en")
    if language not in ["en", "el"]:
        language = "en"

    doc = LegalDocument.get_or_create_default(language)

    return Response(
        {
            "language": doc.language,
            "content": doc.content,
            "updated_at": doc.updated_at,
        }
    )
