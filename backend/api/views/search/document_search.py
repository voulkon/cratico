from datetime import datetime

from core.models.organizations import Organization, Signer, Unit
from core.services.feature_flag_service import feature_flags
from core.services.search_service import SearchService
from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


def get_entity_decisions_queryset(entity_type, entity_id):
    """Helper function to get decisions queryset for a specific entity"""
    from core.models.decisions import Decision

    if entity_type == "organization":
        return Decision.objects.filter(organization__uid=entity_id)
    elif entity_type == "signer":
        return Decision.objects.filter(signers__uid=entity_id)
    elif entity_type == "unit":
        return Decision.objects.filter(units__uid=entity_id)
    else:
        return Decision.objects.none()


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "q",
            openapi.IN_QUERY,
            description="Search query",
            type=openapi.TYPE_STRING,
            required=True,
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="Filter by extraction provider",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "status",
            openapi.IN_QUERY,
            description="Filter by decision status",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "is_scanned",
            openapi.IN_QUERY,
            description="Filter by scanned document status",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "organization",
            openapi.IN_QUERY,
            description="Filter by organization",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "decision_type",
            openapi.IN_QUERY,
            description="Filter by decision type",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "date_from",
            openapi.IN_QUERY,
            description="Filter from date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "date_to",
            openapi.IN_QUERY,
            description="Filter to date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_search_api(request):
    """Enhanced API endpoint for document search with OpenSearch"""
    query = request.GET.get("q", "")
    provider = request.GET.get("provider", "")
    status = request.GET.get("status", "")
    is_scanned = request.GET.get("is_scanned", "")
    organization = request.GET.get("organization", "")
    decision_type = request.GET.get("decision_type", "")
    date_from = request.GET.get("date_from", "")
    date_to = request.GET.get("date_to", "")
    limit = int(request.GET.get("limit", 100))

    # Convert is_scanned to boolean if provided
    is_scanned_bool = None
    if is_scanned:
        is_scanned_bool = is_scanned.lower() == "true"

    search_service = SearchService()
    search_results = search_service.search_documents(
        query=query,
        provider=provider if provider else None,
        status=status if status else None,
        is_scanned=is_scanned_bool,
        organization=organization if organization else None,
        decision_type=decision_type if decision_type else None,
        date_from=date_from if date_from else None,
        date_to=date_to if date_to else None,
        limit=limit,
    )

    # Convert results to serializable data
    serialized_results = []
    for result in search_results["results"]:
        doc = result["extraction"]  # The actual DocumentExtraction object
        highlights = result.get("highlights", {})
        search_score = result.get("search_score", 0)

        result_data = {
            "id": doc.id,
            "decision_id": (
                doc.decision.id if doc.decision else None
            ),  # Fixed: use .id instead of .uid
            "ada": doc.decision.ada if doc.decision else None,
            "decision_title": doc.decision.subject if doc.decision else None,
            "organization": (
                doc.decision.organization.label
                if doc.decision and doc.decision.organization
                else None
            ),
            "organization_id": (
                doc.decision.organization.uid
                if doc.decision and doc.decision.organization
                else None
            ),  # Organization has uid
            "decision_type": (
                str(doc.decision.decision_type)
                if doc.decision and doc.decision.decision_type
                else None
            ),
            "provider": doc.extraction_provider,
            "status": doc.decision.status if doc.decision else None,
            "is_scanned": doc.is_scanned_document,
            "processing_time_ms": doc.processing_time_ms,
            "extraction_date": (
                doc.extraction_date.isoformat() if doc.extraction_date else None
            ),
            "issue_date": (
                doc.decision.issue_date_day
                if doc.decision and doc.decision.issue_date_day
                else None
            ),
            "character_count": doc.character_count,
            "page_count": doc.page_count,
            "search_score": search_score,
            "type": "document",
        }

        # Add content preview - use OpenSearch preview if available, otherwise PostgreSQL
        if result.get("opensearch_source"):
            result_data["content_preview"] = result["opensearch_source"].get(
                "content_preview", ""
            )
        else:
            result_data["content_preview"] = (
                doc.raw_text[:200] + "..."
                if doc.raw_text and len(doc.raw_text) > 200
                else doc.raw_text
            )

        # Add highlights if available
        if highlights:
            result_data["highlights"] = highlights

        serialized_results.append(result_data)

    return Response(
        {
            "query": query,
            "results": serialized_results,
            "count": search_results["count"],
            "source": search_results.get(
                "source", "unknown"
            ),  # 'opensearch' or 'postgresql'
            "highlights": search_results.get("highlights", {}),
            "capabilities": {
                "opensearch_enabled": feature_flags.is_enabled("INDEX_THE_OPENSEARCH"),
                "postgres_search_enabled": feature_flags.is_enabled(
                    "INDEX_THE_POSTGRES"
                ),
                "content_search_available": (
                    feature_flags.is_enabled("INDEX_THE_OPENSEARCH")
                    or feature_flags.is_enabled("INDEX_THE_POSTGRES")
                ),
            },
            "filters": {
                "provider": provider,
                "status": status,
                "is_scanned": is_scanned,
                "organization": organization,
                "decision_type": decision_type,
                "date_from": date_from,
                "date_to": date_to,
            },
        }
    )


# Keep your existing APIs with minimal changes
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def document_search_api_dev(request):
    """Development version of document search API"""
    return document_search_api(request)  # Just delegate to the main API


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def document_search_options_api(request):
    """Get available filter options for document search"""
    search_service = SearchService()
    options = search_service.get_document_search_options()

    return Response(options)


@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def document_search_options_api_dev(request):
    """Development version - Get available filter options for document search"""
    search_service = SearchService()
    options = search_service.get_document_search_options()

    return Response(options)


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "start_date",
            openapi.IN_QUERY,
            description="Start date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "end_date",
            openapi.IN_QUERY,
            description="End date (YYYY-MM-DD)",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "q", openapi.IN_QUERY, description="Search query", type=openapi.TYPE_STRING
        ),
        openapi.Parameter(
            "provider",
            openapi.IN_QUERY,
            description="Filter by extraction provider",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "is_scanned",
            openapi.IN_QUERY,
            description="Filter by scanned document status",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def entity_search_documents_api_dev(request, entity_type, entity_id):
    """Search documents for a specific entity"""
    start_date_str = request.GET.get("start_date")
    end_date_str = request.GET.get("end_date")
    search_query = request.GET.get("q", "")
    provider = request.GET.get("provider", "")
    is_scanned = request.GET.get("is_scanned", "")
    limit = int(request.GET.get("limit", 100))

    # Convert is_scanned to boolean if provided
    is_scanned_bool = None
    if is_scanned:
        is_scanned_bool = is_scanned.lower() == "true"

    try:
        # Get decisions queryset for the entity
        decisions_qs = get_entity_decisions_queryset(entity_type, entity_id)

        # Apply date filters if provided
        if start_date_str:
            start_date_parsed = parse_date(start_date_str)
            if start_date_parsed:
                start_date = timezone.make_aware(
                    datetime.combine(start_date_parsed, datetime.min.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__gte=start_date)

        if end_date_str:
            end_date_parsed = parse_date(end_date_str)
            if end_date_parsed:
                end_date = timezone.make_aware(
                    datetime.combine(end_date_parsed, datetime.max.time())
                )
                decisions_qs = decisions_qs.filter(issue_date__lte=end_date)

        # Get document extractions for decisions from this entity
        from core.models.document_analysis import DocumentExtraction

        document_qs = DocumentExtraction.objects.filter(
            decision__in=decisions_qs
        ).select_related("decision", "decision__organization")

        # Apply search filter if provided
        if search_query:
            document_qs = document_qs.filter(
                models.Q(raw_text__icontains=search_query)
                | models.Q(decision__subject__icontains=search_query)
                | models.Q(decision__ada__icontains=search_query)
            )

        # Apply provider filter
        if provider:
            document_qs = document_qs.filter(extraction_provider=provider)

        # Apply is_scanned filter
        if is_scanned_bool is not None:
            document_qs = document_qs.filter(is_scanned_document=is_scanned_bool)

        # Limit results
        document_qs = document_qs[:limit]

        # Serialize results
        serialized_results = []
        for doc in document_qs:
            serialized_results.append(
                {
                    "id": doc.id,
                    "decision_id": (
                        doc.decision.ada if doc.decision else None
                    ),  # Use ADA instead of uid
                    "decision_subject": doc.decision.subject if doc.decision else None,
                    "organization": (
                        doc.decision.organization.label
                        if doc.decision and doc.decision.organization
                        else None
                    ),
                    "organization_id": (
                        doc.decision.organization.uid
                        if doc.decision and doc.decision.organization
                        else None
                    ),
                    "provider": doc.extraction_provider,
                    "status": doc.extraction_status,
                    "is_scanned": doc.is_scanned_document,
                    "processing_time_ms": doc.processing_time_ms,
                    "extraction_date": (
                        doc.extraction_date.isoformat() if doc.extraction_date else None
                    ),
                    "raw_text_preview": (
                        doc.raw_text[:200] + "..."
                        if doc.raw_text and len(doc.raw_text) > 200
                        else doc.raw_text
                    ),
                    "type": "document",
                }
            )

        return Response(
            {
                "entity": {"type": entity_type, "id": entity_id},
                "query": search_query,
                "results": serialized_results,
                "count": len(serialized_results),
                "filters": {
                    "provider": provider,
                    "is_scanned": is_scanned,
                    "start_date": start_date_str,
                    "end_date": end_date_str,
                },
            }
        )

    except (Organization.DoesNotExist, Signer.DoesNotExist, Unit.DoesNotExist):
        return Response({"error": "Entity not found"}, status=404)
    except Exception as e:
        import traceback

        return Response(
            {
                "error": f"Internal server error: {str(e)}",
                "traceback": traceback.format_exc() if settings.DEBUG else None,
            },
            status=500,
        )
