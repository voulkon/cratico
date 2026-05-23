from core.services.organization_chart_service import OrganizationChartService
from django.conf import settings
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response


def get_organization_chart_data_for_api(org_uid, limit=100):
    """
    Helper function to get organization chart data for API endpoints.
    Extracts common logic used by multiple endpoints.
    """
    # Use service for core business logic
    chart_service = OrganizationChartService()
    org_chart_data = chart_service.get_organization_chart_data(org_uid)

    return {"org_chart_data": org_chart_data}


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def organization_chart_api(request):
    """API endpoint for organization chart data"""
    org_uid = request.GET.get("org_uid")
    return Response(get_organization_chart_data_for_api(org_uid))


@swagger_auto_schema(
    method="get",
    manual_parameters=[
        openapi.Parameter(
            "org_uid",
            openapi.IN_QUERY,
            description="Organization unique identifier",
            type=openapi.TYPE_STRING,
            required=False,
        )
    ],
)
@api_view(["GET"])
@permission_classes([AllowAny if settings.DEBUG else IsAuthenticated])
def organization_chart_api_dev(request):
    """Development version of the organization chart API"""
    org_uid = request.GET.get("org_uid")
    # Could customize behavior for dev if needed
    return Response(get_organization_chart_data_for_api(org_uid))
