from core.services.version_service import VersionService
from django.http import JsonResponse


def version_check(request):
    """Health check endpoint that returns version and status information."""
    service = VersionService()
    return JsonResponse(service.get_health_info())
