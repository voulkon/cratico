import json

from api.utils.common import get_client_ip
from api.views.search.entity_search_utils import (
    format_afmentity,
    format_company,
    format_company_person,
    format_organization,
    format_signer,
    format_unit,
    get_administrative_terms_autocomplete,
    get_documents_slow,
    get_entities_fast,
)
from core.services.search_history_service import SearchHistoryService
from core.services.search_service import SearchService
from django.conf import settings
from django.http import StreamingHttpResponse
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from api.permissions import AuthenticatedOrDebug
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

# Entity formatting functions - reusable across different search contexts


def get_search_data_for_api(query, **kwargs):
    """
    Helper function to get search data for API endpoints.
    Extracts common logic used by multiple endpoints.

    If 'request' is passed in kwargs, will track the search in history.
    """
    search_service = SearchService()

    # Extract parameters
    entity_types = kwargs.get("entity_types", ["organization", "signer", "unit"])
    organization_id = kwargs.get("organization_id")
    company_id = kwargs.get("company_id")
    limit = kwargs.get("limit", 20)
    include_documents = kwargs.get("include_documents", False)
    request = kwargs.get("request")  # Optional: for tracking search history

    results = {"query": query, "results": {}, "total_count": 0}

    if not query:
        return results

    # Search entities based on requested types
    if "organization" in entity_types:
        orgs = search_service.search_organizations(query, limit)
        results["results"]["organizations"] = [
            format_organization(org, query) for org in orgs
        ]
        results["total_count"] += len(orgs)

    if "signer" in entity_types:
        signers = search_service.search_signers(query, organization_id, limit)
        results["results"]["signers"] = [
            format_signer(signer, query) for signer in signers
        ]
        results["total_count"] += len(signers)

    if "unit" in entity_types:
        units = search_service.search_units(query, organization_id, limit)
        results["results"]["units"] = [format_unit(unit, query) for unit in units]
        results["total_count"] += len(units)

    if "company" in entity_types:
        companies = search_service.search_companies(query, limit)
        results["results"]["companies"] = [
            format_company(company, query) for company in companies
        ]
        results["total_count"] += len(companies)

    if "company_person" in entity_types:
        company_persons = search_service.search_company_persons(
            query, company_id, limit
        )
        results["results"]["company_persons"] = [
            format_company_person(person, query) for person in company_persons
        ]
        results["total_count"] += len(company_persons)

    if "afmentity" in entity_types:
        afm_entities = search_service.search_afm_entities(query, limit)
        results["results"]["afm_entities"] = [
            format_afmentity(entity, query) for entity in afm_entities
        ]
        results["total_count"] += len(afm_entities)

    if include_documents:
        doc_results = search_service.search_documents(query, limit=limit)
        serialized_docs = []
        for doc in doc_results["results"]:
            # Handle both OpenSearch results (dict with 'extraction' key) and PostgreSQL results (DocumentExtraction objects)
            if isinstance(doc, dict) and "extraction" in doc:
                # OpenSearch result format
                extraction = doc["extraction"]
                decision = extraction.decision

                # Build a rich document result
                doc_data = {
                    "id": extraction.id,
                    "type": "document",
                    "title": (
                        decision.subject[:100]
                        + ("..." if len(decision.subject) > 100 else "")
                        if decision
                        else "Untitled Document"
                    ),
                    "subtitle": f"By {decision.organization.label if decision and decision.organization else 'Unknown Organization'}",
                    "description": doc.get("text_excerpt", "No preview available"),
                    "details": {
                        "decision_id": decision.id if decision else None,
                        "ada": decision.ada if decision else None,
                        "organization": (
                            decision.organization.label
                            if decision and decision.organization
                            else None
                        ),
                        "organization_id": (
                            decision.organization.uid
                            if decision and decision.organization
                            else None
                        ),
                        "decision_type": (
                            decision.get_decision_type_label() if decision else None
                        ),
                        "issue_date": (
                            decision.issue_date_day.isoformat()
                            if decision and decision.issue_date_day
                            else None
                        ),
                        "amount": (
                            str(decision.amount)
                            if decision and decision.amount
                            else None
                        ),
                        "currency": decision.currency if decision else None,
                        "status": decision.status if decision else None,
                        "provider": extraction.extraction_provider,
                        "is_scanned": extraction.is_scanned_document,
                        "protocol_number": (
                            decision.protocol_number if decision else None
                        ),
                        "signers": [
                            f"{s.first_name} {s.last_name}"
                            for s in doc.get("signers", [])
                        ],
                    },
                    "search_score": doc.get("search_score", 0),
                    "highlights": doc.get("highlights", {}),
                    "source": "opensearch",
                    "matched_field": "content",
                    "icon": "document",
                }
                serialized_docs.append(doc_data)
            else:
                # PostgreSQL fallback result format (direct DocumentExtraction object)
                extraction = doc["extraction"] if isinstance(doc, dict) else doc
                decision = extraction.decision

                doc_data = {
                    "id": extraction.id,
                    "type": "document",
                    "title": (
                        decision.subject[:100]
                        + ("..." if len(decision.subject) > 100 else "")
                        if decision
                        else "Untitled Document"
                    ),
                    "subtitle": f"By {decision.organization.label if decision and decision.organization else 'Unknown Organization'}",
                    "description": (
                        extraction.raw_text[:300]
                        + ("..." if len(extraction.raw_text or "") > 300 else "")
                        if hasattr(extraction, "raw_text") and extraction.raw_text
                        else "No preview available"
                    ),
                    "details": {
                        "decision_id": decision.id if decision else None,
                        "ada": decision.ada if decision else None,
                        "organization": (
                            decision.organization.label
                            if decision and decision.organization
                            else None
                        ),
                        "organization_id": (
                            decision.organization.uid
                            if decision and decision.organization
                            else None
                        ),
                        "decision_type": (
                            decision.get_decision_type_label() if decision else None
                        ),
                        "issue_date": (
                            decision.issue_date_day.isoformat()
                            if decision and decision.issue_date_day
                            else None
                        ),
                        "amount": (
                            str(decision.amount)
                            if decision and decision.amount
                            else None
                        ),
                        "currency": decision.currency if decision else None,
                        "status": decision.status if decision else None,
                        "provider": extraction.extraction_provider,
                        "is_scanned": extraction.is_scanned_document,
                        "protocol_number": (
                            decision.protocol_number if decision else None
                        ),
                        "signers": (
                            [
                                f"{s.first_name} {s.last_name}"
                                for s in decision.signers.all()
                            ]
                            if decision
                            else []
                        ),
                    },
                    "search_score": (
                        doc.get("search_score", 1.0) if isinstance(doc, dict) else 1.0
                    ),
                    "highlights": (
                        doc.get("highlights", {}) if isinstance(doc, dict) else {}
                    ),
                    "source": "postgresql",
                    "matched_field": "content",
                    "icon": "document",
                }
                serialized_docs.append(doc_data)

        results["results"]["documents"] = serialized_docs
        results["total_count"] += doc_results["count"]

    # Track search in history (if request provided)
    if request and query:
        try:
            history_service = SearchHistoryService()
            user_id = request.user.id if request.user.is_authenticated else None
            ip_address = get_client_ip(request)

            history_service.track_search(
                query=query,
                user_id=user_id,
                ip_address=ip_address,
                results_count=results["total_count"],
                search_types=entity_types,
                entity_type=entity_types[0] if entity_types else None,
            )
        except Exception as e:
            # Don't fail the search if history tracking fails
            from loguru import logger

            logger.warning(f"Failed to track search in history: {e}")

    return results


def get_default_suggestions_for_api():
    """
    Get default search suggestions configured in admin.
    Returns data in the same format as search results.
    """
    from core.models import SearchSuggestion
    from core.models.companies import Company, CompanyPerson
    from core.models.entities import AFMEntity
    from core.models.organizations import Organization, Signer, Unit

    suggestions = SearchSuggestion.get_active_suggestions(limit=10)

    results = {
        "query": "",
        "results": {
            "organizations": [],
            "signers": [],
            "units": [],
            "companies": [],
            "company_persons": [],
            "afm_entities": [],
        },
        "total_count": 0,
        "is_default_suggestions": True,
    }

    # Map of suggestion types to (model, queryset factory, formatter, result key)
    entity_handlers = {
        "organization": (
            Organization,
            lambda id: Organization.objects.get(uid=id),
            format_organization,
            "organizations",
        ),
        "signer": (
            Signer,
            lambda id: Signer.objects.select_related("organization").get(uid=id),
            format_signer,
            "signers",
        ),
        "unit": (
            Unit,
            lambda id: Unit.objects.select_related("organization").get(uid=id),
            format_unit,
            "units",
        ),
        "company": (
            Company,
            lambda id: Company.objects.get(ar_gemi=id),
            format_company,
            "companies",
        ),
        "company_person": (
            CompanyPerson,
            lambda id: CompanyPerson.objects.select_related("company").get(id=id),
            format_company_person,
            "company_persons",
        ),
        "afmentity": (
            AFMEntity,
            lambda id: AFMEntity.objects.get(id=id),
            format_afmentity,
            "afm_entities",
        ),
    }

    for suggestion in suggestions:
        if suggestion.suggestion_type in entity_handlers:
            try:
                _, fetcher, formatter, result_key = entity_handlers[
                    suggestion.suggestion_type
                ]
                entity = fetcher(suggestion.entity_id)
                results["results"][result_key].append(formatter(entity))
                results["total_count"] += 1
            except Exception:
                # Skip if entity not found
                continue

    return results


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
            "types",
            openapi.IN_QUERY,
            description="Comma-separated entity types (organization,signer,unit,company,company_person)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit per type",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def entities_fast_search_api(request):
    """
    Fast entity-only search API
    Returns organizations, signers, units, companies, and company persons quickly
    without including slow document search

    Use this for real-time search-as-you-type functionality
    """
    query = request.GET.get("q", "")
    types_param = request.GET.get(
        "types", "organization,signer,unit,company,company_person,afmentity"
    )
    limit = int(request.GET.get("limit", 5))

    # Parse entity types
    entity_types = [t.strip() for t in types_param.split(",") if t.strip()]

    # Use the fast utility function
    results = get_entities_fast(query, entity_types=entity_types, limit=limit)

    # Track search in history (lightweight, non-blocking)
    if query and query.strip():
        try:
            service = SearchHistoryService()
            user_id = request.user.id if request.user.is_authenticated else None
            ip_address = get_client_ip(request)

            service.track_search(
                query=query,
                user_id=user_id,
                ip_address=ip_address,
                results_count=results.get("total_count", 0),
                search_types=entity_types,
                entity_type=entity_types[0] if entity_types else None,
            )
        except Exception as e:
            # Don't fail the search if history tracking fails
            from loguru import logger

            logger.warning(f"Failed to track fast search in history: {e}")

    return Response(results)


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
            "include_documents",
            openapi.IN_QUERY,
            description="Include document search",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit per type",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def search_stream_api(request):
    """
    SSE (Server-Sent Events) streaming search API
    Returns entities first (fast), then documents (slow) incrementally

    Usage:
        const eventSource = new EventSource('/api/search/stream/?q=ΔΗΜΟΣ&limit=5');
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            if (data.type === 'entities') { ... }
            if (data.type === 'documents') { ... }
            if (data.type === 'done') { eventSource.close(); }
        };
    """
    query = request.GET.get("q", "")
    include_documents = request.GET.get("include_documents", "true").lower() == "true"
    limit = int(request.GET.get("limit", 5))

    def event_stream():
        """Generator function that yields SSE-formatted data"""
        try:
            # Phase 1: Fast entity search (organizations, signers, units, companies, company_persons)
            entity_results = get_entities_fast(
                query,
                entity_types=[
                    "organization",
                    "signer",
                    "unit",
                    "company",
                    "company_person",
                ],
                limit=limit,
            )

            # Send entity results immediately
            yield f"data: {json.dumps(entity_results)}\n\n"

            # Phase 2: Slow document search (if requested)
            if include_documents:
                document_results = get_documents_slow(query, limit=limit)
                yield f"data: {json.dumps(document_results)}\n\n"

            # Send completion signal
            yield f"data: {json.dumps({'type': 'done', 'query': query})}\n\n"

        except Exception as e:
            # Send error event
            error_data = {"type": "error", "message": str(e), "query": query}
            yield f"data: {json.dumps(error_data)}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"  # Disable buffering in nginx

    return response


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "q",
            openapi.IN_QUERY,
            description="Search query prefix",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "category",
            openapi.IN_QUERY,
            description="Filter by category (organization, company)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def autocomplete_suggestions_api(request):
    """
    Autocomplete suggestions API
    Returns common Greek administrative terms that match the query

    This is designed to help users quickly find organizations by typing
    common prefixes like "ΔΗΜΟΣ", "ΠΕΡΙΦΕΡΕΙΑ", "ΥΠΟΥΡΓΕΙΟ", etc.

    Future enhancement: Use analytics to find most common terms in entity names
    """
    query = request.GET.get("q", "").strip()
    category = request.GET.get("category", "").lower()

    # Get autocomplete suggestions with automatic transliteration support
    common_administrative_terms = get_administrative_terms_autocomplete(
        query_prefix=query
    )

    # Filter terms based on category
    suggestions = []
    for term in common_administrative_terms:
        # Apply category filter if specified
        if category and term["category"] != category:
            continue

        suggestions.append(term)

    return Response(
        {"query": query, "suggestions": suggestions, "count": len(suggestions)}
    )


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
            "types",
            openapi.IN_QUERY,
            description="Comma-separated entity types (organization,signer,unit,company,company_person)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "organization_id",
            openapi.IN_QUERY,
            description="Filter by organization",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "company_id",
            openapi.IN_QUERY,
            description="Filter by company ID",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "include_documents",
            openapi.IN_QUERY,
            description="Include document search",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit per type",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def universal_search_api(request):
    """Universal search API that can handle multiple entity types"""
    query = request.GET.get("q", "")
    types_param = request.GET.get("types", "organization,signer,unit")
    organization_id = request.GET.get("organization_id")
    company_id = request.GET.get("company_id")
    include_documents = request.GET.get("include_documents", "false").lower() == "true"
    limit = int(request.GET.get("limit", 20))

    # Parse entity types
    entity_types = [t.strip() for t in types_param.split(",") if t.strip()]

    return Response(
        get_search_data_for_api(
            query,
            entity_types=entity_types,
            organization_id=organization_id,
            company_id=int(company_id) if company_id and company_id.isdigit() else None,
            include_documents=include_documents,
            limit=limit,
        )
    )


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
            "types",
            openapi.IN_QUERY,
            description="Comma-separated entity types (organization,signer,unit,company,company_person)",
            type=openapi.TYPE_STRING,
            required=False,
        ),
        openapi.Parameter(
            "organization_id",
            openapi.IN_QUERY,
            description="Filter by organization",
            type=openapi.TYPE_STRING,
        ),
        openapi.Parameter(
            "company_id",
            openapi.IN_QUERY,
            description="Filter by company ID",
            type=openapi.TYPE_INTEGER,
        ),
        openapi.Parameter(
            "include_documents",
            openapi.IN_QUERY,
            description="Include document search",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit per type",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def universal_search_api_dev(request):
    """
    Development version of universal search API
    ['organization', 'signer', 'unit', 'company', 'company_person']
    """
    query = request.GET.get("q", "")
    types_param = request.GET.get("types", "organization,signer,unit")
    organization_id = request.GET.get("organization_id")
    company_id = request.GET.get("company_id")
    include_documents = request.GET.get("include_documents", "false").lower() == "true"
    limit = int(request.GET.get("limit", 20))

    entity_types = [t.strip() for t in types_param.split(",") if t.strip()]

    return Response(
        get_search_data_for_api(
            query,
            entity_types=entity_types,
            organization_id=organization_id,
            company_id=int(company_id) if company_id and company_id.isdigit() else None,
            include_documents=include_documents,
            limit=limit,
            request=request,
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_signer_search_api(request):
    """Search organizations and signers only"""
    query = request.GET.get("q", "")
    organization_id = request.GET.get("organization_id")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=["organization", "signer"],
            organization_id=organization_id,
            limit=limit,
            request=request,
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def org_signer_unit_search_api(request):
    """Search organizations, signers, and units"""
    query = request.GET.get("q", "")
    organization_id = request.GET.get("organization_id")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=["organization", "signer", "unit"],
            organization_id=organization_id,
            limit=limit,
            request=request,
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_only_search_api(request):
    """Search organizations only"""
    query = request.GET.get("q", "")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query, entity_types=["organization"], limit=limit, request=request
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def signer_only_search_api(request):
    """Search signers only"""
    query = request.GET.get("q", "")
    organization_id = request.GET.get("organization_id")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=["signer"],
            organization_id=organization_id,
            limit=limit,
            request=request,
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def company_only_search_api(request):
    """Search companies only"""
    query = request.GET.get("q", "")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query, entity_types=["company"], limit=limit, request=request
        )
    )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def company_person_only_search_api(request):
    """Search company persons only"""
    query = request.GET.get("q", "")
    company_id = request.GET.get("company_id")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=["company_person"],
            company_id=int(company_id) if company_id and company_id.isdigit() else None,
            limit=limit,
            request=request,
        )
    )


@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def company_and_persons_search_api(request):
    """Search companies and company persons together"""
    query = request.GET.get("q", "")
    company_id = request.GET.get("company_id")
    limit = int(request.GET.get("limit", 20))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=["company", "company_person"],
            company_id=int(company_id) if company_id and company_id.isdigit() else None,
            limit=limit,
            request=request,
        )
    )


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def default_suggestions_api(request):
    """
    Get default search suggestions to show when user focuses on search box.
    Returns pre-configured popular entities from admin.
    """
    int(request.GET.get("limit", 10))
    return Response(get_default_suggestions_for_api())


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
            "include_documents",
            openapi.IN_QUERY,
            description="Include document search",
            type=openapi.TYPE_BOOLEAN,
        ),
        openapi.Parameter(
            "limit",
            openapi.IN_QUERY,
            description="Results limit per type",
            type=openapi.TYPE_INTEGER,
        ),
    ],
)
@api_view(["GET"])
@permission_classes([AuthenticatedOrDebug])
def super_search_api(request):
    """
    Super search API that searches across ALL entity types and documents:
    - Organizations, Units, Signers
    - Companies and Company Persons
    - Document content (via OpenSearch)
    """
    query = request.GET.get("q", "").strip()

    if not query:
        return Response(
            {
                "error": 'Query parameter "q" is required',
                "query": "",
                "results": {},
                "total_count": 0,
            },
            status=400,
        )

    include_documents = request.GET.get("include_documents", "true").lower() == "true"
    limit = int(request.GET.get("limit", 10))

    return Response(
        get_search_data_for_api(
            query,
            entity_types=[
                "organization",
                "signer",
                "unit",
                "company",
                "company_person",
                "afmentity",
            ],
            include_documents=include_documents,
            limit=limit,
            request=request,
        )
    )


# ============================================================================
# Search History Endpoints
# ============================================================================
# The following endpoints have been moved to search_history_api.py:
# - personal_search_history_api
# - recent_search_queries_api
# - clear_search_history_api
# - recently_visited_api
# - track_search_selection_api
#
# Import them from: api.views.search.search_history_api
# ============================================================================
