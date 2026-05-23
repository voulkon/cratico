from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Avg, Count, ExpressionWrapper, fields
from django.db.models.functions import TruncDate
from django.shortcuts import render


@staff_member_required
def document_processing_dashboard(request):
    """Dashboard for document extraction processing status"""

    # Status breakdown
    status_counts = (
        DocumentExtraction.objects.values("extraction_status")
        .annotate(count=Count("id"))
        .order_by("extraction_status")
    )

    # Provider breakdown
    provider_counts = (
        DocumentExtraction.objects.exclude(extraction_provider__isnull=True)
        .values("extraction_provider")
        .annotate(count=Count("id"))
        .order_by("-count")
    )

    # Processing time by provider
    provider_times = (
        DocumentExtraction.objects.exclude(processing_time_ms__isnull=True)
        .values("extraction_provider")
        .annotate(
            avg_time=ExpressionWrapper(
                Avg("processing_time_ms") / 1000, output_field=fields.FloatField()
            )
        )
        .order_by("extraction_provider")
    )

    # Daily processing volume
    daily_volume = (
        DocumentExtraction.objects.exclude(extraction_date__isnull=True)
        .annotate(date=TruncDate("extraction_date"))
        .values("date")
        .annotate(count=Count("id"))
        .order_by("-date")[:30]
    )

    # Success rate over time (last 30 days)
    success_rates = []
    for day_data in daily_volume:
        day = day_data["date"]
        total = day_data["count"]
        success = DocumentExtraction.objects.filter(
            extraction_date__date=day, extraction_status=ProcessingStatus.COMPLETED
        ).count()

        if total > 0:
            success_rates.append({"date": day, "rate": round(success / total * 100, 1)})

    # Recent failures
    recent_failures = DocumentExtraction.objects.filter(
        extraction_status=ProcessingStatus.FAILED
    ).order_by("-updated_at")[:10]

    context = {
        "status_counts": status_counts,
        "provider_counts": provider_counts,
        "provider_times": provider_times,
        "daily_volume": daily_volume,
        "success_rates": success_rates,
        "recent_failures": recent_failures,
        "total_extractions": DocumentExtraction.objects.count(),
        "total_completed": DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.COMPLETED
        ).count(),
        "total_failed": DocumentExtraction.objects.filter(
            extraction_status=ProcessingStatus.FAILED
        ).count(),
        "pending_count": DocumentExtraction.objects.filter(
            extraction_status__in=[
                ProcessingStatus.PENDING,
                ProcessingStatus.PROCESSING,
                ProcessingStatus.NEEDS_VISION,
            ]
        ).count(),
    }

    return render(request, "admin/document_processing_dashboard.html", context)
