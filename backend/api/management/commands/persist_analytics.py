"""
Persist Redis analytics data to database.

This command reads analytics data from Redis (using centralized keys from api.redis_keys)
and persists it to the database for long-term storage and analysis.

Run via:
    python manage.py persist_analytics

Schedule via cron or Celery beat for periodic execution (e.g., daily).
"""

from datetime import datetime

from api.redis_keys import (
    DAILY_STATS,
    ENDPOINT_PREFIX,
    TOTAL_REQUESTS,
    UNIQUE_IPS,
    get_ip_endpoints_key,
)
from django.core.cache import cache
from django.core.management.base import BaseCommand
from django_redis import get_redis_connection
from loguru import logger


class Command(BaseCommand):
    help = "Persist Redis analytics data to database"

    def handle(self, *args, **options):
        from api.models import APIAnalytics, DailyTraffic, EndpointStats, IPJourney

        redis = get_redis_connection("default")

        # Get total requests and unique IPs using centralized keys
        total_requests = cache.get(TOTAL_REQUESTS, 0)
        unique_ips_count = redis.scard(UNIQUE_IPS)

        # Get total requests and unique IPs using centralized keys
        total_requests = cache.get(TOTAL_REQUESTS, 0)
        unique_ips_count = redis.scard(UNIQUE_IPS)

        logger.info(
            f"Persisting analytics: {total_requests} requests, {unique_ips_count} unique IPs"
        )

        # Create a new analytics record
        analytics = APIAnalytics.objects.create(
            total_requests=total_requests,
            unique_ips=unique_ips_count,
            timestamp=datetime.now(),
        )

        # Persist endpoint stats using centralized key pattern
        endpoint_pattern = f"{ENDPOINT_PREFIX}*"
        cursor = 0
        endpoint_count = 0

        while True:
            cursor, keys = redis.scan(cursor=cursor, match=endpoint_pattern, count=100)

            for key in keys:
                endpoint = key.decode("utf-8").replace(ENDPOINT_PREFIX, "")
                count = int(cache.get(key.decode("utf-8"), 0))
                if count > 0:
                    EndpointStats.objects.create(
                        analytics=analytics, endpoint=endpoint, count=count
                    )
                    endpoint_count += 1

            if cursor == 0:
                break

        # Persist daily traffic using centralized key
        daily_data = redis.zrange(DAILY_STATS, 0, -1, withscores=True)
        daily_count = 0
        for day_key, count in daily_data:
            try:
                day = datetime.fromtimestamp(int(day_key.decode("utf-8")) * 86400)
                DailyTraffic.objects.create(
                    analytics=analytics, date=day.date(), count=int(count)
                )
                daily_count += 1
            except (ValueError, OSError) as e:
                logger.warning(f"Failed to parse daily traffic data: {e}")
                continue

        # Persist IP journey data using centralized keys
        unique_ips = redis.smembers(UNIQUE_IPS)
        ip_count = 0
        for ip_bytes in unique_ips:
            ip = ip_bytes.decode("utf-8")
            ip_endpoints_key = get_ip_endpoints_key(ip)
            endpoints = redis.smembers(ip_endpoints_key)

            if endpoints:
                endpoint_list = sorted([e.decode("utf-8") for e in endpoints])
                IPJourney.objects.create(
                    analytics=analytics,
                    ip_address=ip,
                    endpoints_visited=endpoint_list,
                    journey_length=len(endpoint_list),
                )
                ip_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Successfully persisted analytics data (ID: {analytics.id})\n"
                f"  - {endpoint_count} endpoints\n"
                f"  - {daily_count} days of traffic\n"
                f"  - {ip_count} IP journeys"
            )
        )

        logger.info(
            f"Persisted analytics ID {analytics.id}: "
            f"{endpoint_count} endpoints, {daily_count} days, {ip_count} IPs"
        )
