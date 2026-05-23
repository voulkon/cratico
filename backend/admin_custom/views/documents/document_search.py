from core.services.search_service import SearchService
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def document_search(request):
    """Advanced search interface for document content"""
    query = request.GET.get("q", "")
    provider = request.GET.get("provider", "")
    status = request.GET.get("status", "")
    is_scanned = request.GET.get("is_scanned", "")

    search_service = SearchService()

    # Convert is_scanned to boolean if provided
    is_scanned_bool = None
    if is_scanned:
        is_scanned_bool = is_scanned == "true"

    # Perform search
    search_results = search_service.search_documents(
        query=query, provider=provider, status=status, is_scanned=is_scanned_bool
    )

    results = search_results["results"]
    count = search_results["count"]

    # Get form options
    options = search_service.get_document_search_options()

    context = {
        "query": query,
        "results": results,
        "count": count,
        "providers": options["providers"],
        "statuses": options["statuses"],
        "provider_filter": provider,
        "status_filter": status,
        "is_scanned_filter": is_scanned,
    }

    return render(request, "admin/document_search.html", context)
