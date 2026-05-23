import csv
import time
from collections import Counter
from datetime import datetime

from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render
from django_redis import get_redis_connection

from .models import APIAnalytics


@staff_member_required
def redis_analytics(request):
    """Admin view showing Redis analytics dashboard"""
    redis = get_redis_connection("default")

    # Get basic stats
    total_requests = cache.get("stats:total_requests", 0)
    unique_ips = redis.scard("stats:unique_ips")

    # Get popular endpoints
    endpoints = []
    endpoint_keys = redis.keys("stats:endpoint:*")
    for key in endpoint_keys:
        endpoint = key.decode("utf-8").replace("stats:endpoint:", "")
        count = cache.get(f"stats:endpoint:{endpoint}")
        endpoints.append((endpoint, int(count)))

    # Sort by popularity
    endpoints.sort(key=lambda x: x[1], reverse=True)

    # Get HTTP methods distribution
    methods = []
    method_keys = redis.keys("stats:method:*")
    for key in method_keys:
        method = key.decode("utf-8").replace("stats:method:", "")
        count = cache.get(f"stats:method:{method}")
        methods.append((method, int(count)))

    # Get hourly traffic
    hourly_traffic = []
    hourly_data = redis.zrange("stats:hourly", 0, -1, withscores=True)
    for hour_key, count in hourly_data:
        hour = datetime.fromtimestamp(int(hour_key.decode("utf-8")) * 3600)
        hourly_traffic.append((hour.strftime("%Y-%m-%d %H:00"), int(count)))

    # Get daily traffic
    daily_traffic = []
    daily_data = redis.zrange("stats:daily", 0, -1, withscores=True)
    for day_key, count in daily_data:
        day = datetime.fromtimestamp(int(day_key.decode("utf-8")) * 86400)
        daily_traffic.append((day.strftime("%Y-%m-%d"), int(count)))

    return render(
        request,
        "admin/redis_analytics.html",
        {
            "total_requests": total_requests,
            "unique_ips": unique_ips,
            "popular_endpoints": endpoints[:10],  # Top 10
            "methods": methods,
            "hourly_traffic": hourly_traffic,
            "daily_traffic": daily_traffic,
        },
    )


@staff_member_required
def export_redis_analytics(request):
    """Export analytics data as CSV"""
    redis = get_redis_connection("default")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="redis_analytics.csv"'

    writer = csv.writer(response)
    writer.writerow(["IP Address", "Request Count", "Last Access"])

    # Get all rate limit keys
    keys = redis.keys("ratelimit:*")
    for key in keys:
        ip = key.decode("utf-8").replace("ratelimit:", "")
        if ":user:" in ip:  # Skip user keys
            continue

        data = cache.get(f"ratelimit:{ip}", {})
        count = data.get("count", 0)
        reset_time = data.get("reset_time", time.time())
        last_access = datetime.fromtimestamp(reset_time - 86400)  # Assuming 24h window
        writer.writerow([ip, count, last_access.strftime("%Y-%m-%d %H:%M:%S")])

    return response


@staff_member_required
def endpoint_deep_dive(request):
    """Deep dive into endpoint usage patterns"""

    # Get the pattern to analyze (default to 51:12)
    target_requests = int(request.GET.get("requests", 51))
    target_ips = int(request.GET.get("ips", 12))

    # Find all analytics records with this pattern
    pattern_analytics = (
        APIAnalytics.objects.filter(
            total_requests=target_requests, unique_ips=target_ips
        )
        .order_by("-timestamp")
        .prefetch_related("endpoints")[:10]
    )

    # Analyze endpoint patterns for this specific pattern
    endpoint_consistency = Counter()
    daily_breakdowns = []

    for analytics in pattern_analytics:
        endpoints = analytics.endpoints.all().order_by("-count")

        # Check endpoint consistency
        for endpoint_stat in endpoints:
            endpoint_consistency[endpoint_stat.endpoint] += 1

        daily_breakdowns.append(
            {
                "date": analytics.timestamp.date(),
                "endpoints": [(e.endpoint, e.count) for e in endpoints],
                "total_endpoints": len(endpoints),
            }
        )

    # Find most consistent endpoints (appear in most days with this pattern)
    consistent_endpoints = endpoint_consistency.most_common(15)

    context = {
        "target_pattern": f"{target_requests}:{target_ips}",
        "pattern_occurrences": len(daily_breakdowns),
        "daily_breakdowns": daily_breakdowns,
        "consistent_endpoints": consistent_endpoints,
        "analysis_date": datetime.now(),
    }

    return render(request, "admin/endpoint_deep_dive.html", context)
