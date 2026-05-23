from core.services.organization_chart_service import OrganizationChartService
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render


@staff_member_required
def organization_org_chart(request):
    """View for traditional org chart visualization"""
    org_uid = request.GET.get("org_uid")

    # Use shared service for core business logic
    chart_service = OrganizationChartService()
    org_chart_data = chart_service.get_organization_chart_data(org_uid)

    # Admin-specific rendering
    return render(
        request,
        "admin/organization_chart.html",
        {
            "org_chart_data": org_chart_data,
        },
    )
