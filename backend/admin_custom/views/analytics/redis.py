import csv
import time
from collections import Counter
from datetime import datetime

from api.models import APIAnalytics
from api.redis_keys import (
    DAILY_STATS,
    ENDPOINT_PREFIX,
    HOURLY_STATS,
    IP_RATELIMIT_PREFIX,
    METHOD_PREFIX,
    TOTAL_REQUESTS,
    UNIQUE_IPS,
)
from django.contrib.admin.views.decorators import staff_member_required
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render
from django_redis import get_redis_connection


@staff_member_required
def redis_analytics(request):
    """Admin view showing Redis analytics dashboard"""
    redis = get_redis_connection("default")

    # Get pagination offsets from query parameters
    daily_offset = int(request.GET.get("daily_offset", 0))  # Days back in time
    hourly_offset = int(request.GET.get("hourly_offset", 0))  # Hours back in time

    # Ensure offsets are non-negative
    daily_offset = max(0, daily_offset)
    hourly_offset = max(0, hourly_offset)

    # Get basic stats
    total_requests = cache.get(TOTAL_REQUESTS, 0)
    unique_ips = redis.scard(UNIQUE_IPS)

    # Get popular endpoints
    endpoints = []
    endpoint_keys = redis.keys(f"{ENDPOINT_PREFIX}*")
    for key in endpoint_keys:
        endpoint = key.decode("utf-8").replace(ENDPOINT_PREFIX, "")
        count = cache.get(key.decode("utf-8"))
        if count:
            endpoints.append((endpoint, int(count)))

    # Sort by popularity
    endpoints.sort(key=lambda x: x[1], reverse=True)

    # Get HTTP methods distribution
    methods = []
    method_keys = redis.keys(f"{METHOD_PREFIX}*")
    for key in method_keys:
        method = key.decode("utf-8").replace(METHOD_PREFIX, "")
        count = cache.get(key.decode("utf-8"))
        if count:
            methods.append((method, int(count)))

    # Get hourly traffic with pagination
    hourly_traffic = []
    hourly_data = redis.zrange(HOURLY_STATS, 0, -1, withscores=True)
    for hour_key, count in hourly_data:
        hour_timestamp = int(hour_key.decode("utf-8"))
        hour = datetime.fromtimestamp(hour_timestamp * 3600)
        hourly_traffic.append(
            (hour_timestamp, hour.strftime("%Y-%m-%d %H:00"), int(count))
        )

    # Sort by timestamp (chronologically) instead of by score
    hourly_traffic.sort(key=lambda x: x[0])

    # Apply pagination - show 24 hours
    if hourly_traffic:
        # Get the slice based on offset
        end_idx = len(hourly_traffic) - hourly_offset
        start_idx = max(0, end_idx - 24)
        hourly_traffic_paginated = hourly_traffic[start_idx:end_idx]

        # Calculate range display
        if hourly_traffic_paginated:
            hourly_range = (
                f"{hourly_traffic_paginated[0][1]} to {hourly_traffic_paginated[-1][1]}"
            )
        else:
            hourly_range = "No data"
    else:
        hourly_traffic_paginated = []
        hourly_range = "No data"

    # Remove timestamp from tuple for template
    hourly_traffic = [(label, count) for _, label, count in hourly_traffic_paginated]

    # Get daily traffic with pagination
    daily_traffic = []
    daily_data = redis.zrange(DAILY_STATS, 0, -1, withscores=True)
    for day_key, count in daily_data:
        day_timestamp = int(day_key.decode("utf-8"))
        day = datetime.fromtimestamp(day_timestamp * 86400)
        daily_traffic.append((day_timestamp, day.strftime("%Y-%m-%d"), int(count)))

    # Sort by timestamp (chronologically)
    daily_traffic.sort(key=lambda x: x[0])

    # Apply pagination - show 7 days
    if daily_traffic:
        # Get the slice based on offset
        end_idx = len(daily_traffic) - daily_offset
        start_idx = max(0, end_idx - 7)
        daily_traffic_paginated = daily_traffic[start_idx:end_idx]

        # Calculate range display
        if daily_traffic_paginated:
            daily_range = (
                f"{daily_traffic_paginated[0][1]} to {daily_traffic_paginated[-1][1]}"
            )
        else:
            daily_range = "No data"
    else:
        daily_traffic_paginated = []
        daily_range = "No data"

    # Remove timestamp from tuple for template
    daily_traffic = [(label, count) for _, label, count in daily_traffic_paginated]

    # Get IP journey data
    from api.redis_keys import get_ip_endpoints_key

    ip_journeys = []
    unique_ips_list = redis.smembers(UNIQUE_IPS)

    for ip_bytes in unique_ips_list:
        ip = ip_bytes.decode("utf-8")
        ip_endpoints_key = get_ip_endpoints_key(ip)
        ip_endpoints_set = redis.smembers(
            ip_endpoints_key
        )  # FIXED: renamed to avoid collision

        if ip_endpoints_set:
            endpoint_list = sorted([e.decode("utf-8") for e in ip_endpoints_set])
            ip_journeys.append((ip, endpoint_list, len(endpoint_list)))

    # Sort by journey length (most active IPs first)
    ip_journeys.sort(key=lambda x: x[2], reverse=True)

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
            "ip_journeys": ip_journeys[:10],  # Top 10 most active IPs
            "daily_offset": daily_offset,
            "hourly_offset": hourly_offset,
            "daily_range": daily_range,
            "hourly_range": hourly_range,
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
    keys = redis.keys(f"{IP_RATELIMIT_PREFIX}*")
    for key in keys:
        ip = key.decode("utf-8").replace(IP_RATELIMIT_PREFIX, "")
        if ":user:" in ip:  # Skip user keys
            continue

        data = cache.get(key.decode("utf-8"), {})
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


@staff_member_required
def trigger_analytics_warmup(request):
    """
    Admin view to trigger analytics cache warming ad hoc.

    GET  → shows a simple form with a date picker and trigger button.
    POST → dispatches warm_analytics_cache as a background Celery task.

    Accepts an optional 'date' POST param (ISO format, defaults to today).

    When the scheduled post-import warmup runs later, it will naturally
    overwrite any Redis keys set by this ad-hoc run (cache.set always
    overwrites, so the scheduled run is the final source of truth).
    """
    from datetime import date, datetime

    from core.tasks.tasks_post_import import warm_analytics_cache
    from django.http import JsonResponse

    if request.method == "POST":
        reference_date_str = request.POST.get("date") or None

        # Validate date if provided
        if reference_date_str:
            try:
                datetime.strptime(reference_date_str, "%Y-%m-%d")
            except ValueError:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Invalid date format. Use YYYY-MM-DD.",
                    },
                    status=400,
                )

        try:
            task = warm_analytics_cache.delay(
                reference_date_str=reference_date_str
            )
            return JsonResponse(
                {
                    "success": True,
                    "task_id": task.id,
                    "reference_date": reference_date_str or str(date.today()),
                    "message": (
                        f"Cache warmup dispatched (task {task.id}). "
                        f"The scheduled run will overwrite these Redis keys "
                        f"with fresh data at the normal time."
                    ),
                }
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )

    # GET: render the trigger form
    from django.shortcuts import render

    return render(
        request,
        "admin/analytics_warmup.html",
        {"today": date.today().isoformat()},
    )


@staff_member_required
def trigger_subscription_checks(request):
    """
    Admin view to trigger subscription notification checks ad hoc.

    GET  → shows a simple form with a date picker and trigger button.
    POST → dispatches trigger_check_all_subscriptions as a background
           Celery task.

    Accepts an optional 'date' POST param (ISO format, defaults to today).
    """
    from datetime import date, datetime

    from core.tasks.tasks_post_import import trigger_check_all_subscriptions
    from django.http import JsonResponse

    if request.method == "POST":
        reference_date_str = request.POST.get("date") or None

        # Validate date if provided
        if reference_date_str:
            try:
                datetime.strptime(reference_date_str, "%Y-%m-%d")
            except ValueError:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Invalid date format. Use YYYY-MM-DD.",
                    },
                    status=400,
                )

        try:
            task = trigger_check_all_subscriptions.delay(
                reference_date_str=reference_date_str
            )
            return JsonResponse(
                {
                    "success": True,
                    "task_id": task.id,
                    "reference_date": reference_date_str or str(date.today()),
                    "message": (
                        f"Subscription checks dispatched (task {task.id}). "
                        f"This fans out to check_all_active_subscriptions, "
                        f"which checks each active daily/weekly subscription "
                        f"against yesterday's new decisions."
                    ),
                }
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )

    # GET: render the trigger form
    from django.shortcuts import render

    return render(
        request,
        "admin/subscription_checks.html",
        {"today": date.today().isoformat()},
    )


@staff_member_required
def trigger_entity_rankings(request):
    """
    Admin view to trigger entity rankings computation ad hoc.

    GET  → shows a simple form with a date picker and trigger button.
    POST → dispatches compute_entity_rankings as a background Celery task.

    Accepts an optional 'date' POST param (ISO format, defaults to today).
    """
    from datetime import date, datetime

    from core.tasks.tasks_post_import import compute_entity_rankings
    from django.http import JsonResponse

    if request.method == "POST":
        reference_date_str = request.POST.get("date") or None

        if reference_date_str:
            try:
                datetime.strptime(reference_date_str, "%Y-%m-%d")
            except ValueError:
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Invalid date format. Use YYYY-MM-DD.",
                    },
                    status=400,
                )

        try:
            task = compute_entity_rankings.delay(
                reference_date_str=reference_date_str
            )
            return JsonResponse(
                {
                    "success": True,
                    "task_id": task.id,
                    "reference_date": reference_date_str or str(date.today()),
                    "message": (
                        f"Entity rankings dispatched (task {task.id}). "
                        f"Computes per-entity statistics across "
                        f"daily/weekly/monthly/yearly windows."
                    ),
                }
            )
        except Exception as e:
            return JsonResponse(
                {"success": False, "error": str(e)}, status=500
            )

    from django.shortcuts import render

    return render(
        request,
        "admin/entity_rankings.html",
        {"today": date.today().isoformat()},
    )
