"""
API views for accessing performance monitoring data.
These endpoints help developers monitor query performance and identify bottlenecks.
"""

from core.utils.performance_monitoring import (
    export_performance_data,
    get_performance_api_data,
    get_performance_report,
)
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def performance_summary(request):
    """
    Get performance summary for all monitored functions.
    Only available in debug mode or for staff users.
    """
    if not (settings.DEBUG or request.user.is_staff):
        return Response({"error": "Access denied"}, status=403)

    try:
        summary_data = get_performance_api_data()
        return Response(summary_data)
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def performance_export(request):
    """
    Export detailed performance data as JSON.
    Useful for external analysis.
    """
    if not (settings.DEBUG or request.user.is_staff):
        return Response({"error": "Access denied"}, status=403)

    try:
        export_data = export_performance_data()
        return Response(
            {
                "exported_at": "2025-01-27T12:00:00Z",  # Current timestamp
                "data": export_data,
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def performance_health_check(request):
    """
    Quick health check to identify any performance issues.
    Returns warnings if any functions are consistently slow.
    """
    if not (settings.DEBUG or request.user.is_staff):
        return Response({"error": "Access denied"}, status=403)

    try:
        summary = get_performance_report()

        warnings = []
        critical_issues = []

        for func_name, metrics in summary.items():
            if metrics.get("slow_percentage", 0) > 50:
                critical_issues.append(
                    {
                        "function": func_name,
                        "issue": f"{metrics['slow_percentage']:.1f}% of calls are slow",
                        "avg_time": metrics.get("avg_time", 0),
                        "recommendation": "Investigate query optimization",
                    }
                )
            elif metrics.get("avg_time", 0) > 0.5:
                warnings.append(
                    {
                        "function": func_name,
                        "issue": f"Average time {metrics['avg_time']:.2f}s",
                        "recommendation": "Consider optimization",
                    }
                )

        health_status = (
            "critical" if critical_issues else "warning" if warnings else "healthy"
        )

        return Response(
            {
                "status": health_status,
                "summary": {
                    "total_functions": len(summary),
                    "critical_issues": len(critical_issues),
                    "warnings": len(warnings),
                },
                "critical_issues": critical_issues,
                "warnings": warnings,
                "recommendations": (
                    [
                        "Add database indexes for frequently queried fields",
                        "Use select_related() and prefetch_related() for foreign key access",
                        "Consider caching for expensive calculations",
                        "Paginate large result sets",
                    ]
                    if (critical_issues or warnings)
                    else []
                ),
            }
        )
    except Exception as e:
        return Response({"error": str(e)}, status=500)
