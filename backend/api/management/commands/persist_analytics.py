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
    ENDPOINT_IPS_PREFIX,
    ENDPOINT_PREFIX,
    HOURLY_STATS,
    IP_ENDPOINTS_PREFIX,
    METHOD_PREFIX,
    TOTAL_REQUESTS,
    UNIQUE_IPS,
    USER_AGENTS,
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

        logger.info(
            f"Persisting analytics: {total_requests} requests, {unique_ips_count} unique IPs"
        )

        # Create a new analytics record
        analytics = APIAnalytics.objects.create(
            total_requests=total_requests,
            unique_ips=unique_ips_count,
            timestamp=datetime.now(),
        )

        # Persist endpoint stats using centralized key pattern.
        # NOTE: Endpoint counters are written via cache.incr() (safe_incr), which
        # means Django's cache version prefix (:1:) is prepended to the raw key.
        # We scan with a wildcard prefix to match versioned keys, then strip the
        # version prefix before reading via cache.get().
        endpoint_pattern = f"*{ENDPOINT_PREFIX}*"
        cursor = 0
        endpoint_count = 0
        endpoint_keys_to_delete = []  # Collect for cleanup after persist

        while True:
            cursor, keys = redis.scan(cursor=cursor, match=endpoint_pattern, count=100)

            for key in keys:
                raw_key = key.decode("utf-8")
                endpoint_keys_to_delete.append(raw_key)
                # Strip Django cache version prefix (e.g. ":1:stats:endpoint:..." → "stats:endpoint:...")
                if ":" + ENDPOINT_PREFIX in raw_key:
                    cache_key = raw_key.split(":" + ENDPOINT_PREFIX, 1)[1]
                    cache_key = ENDPOINT_PREFIX + cache_key
                else:
                    cache_key = raw_key
                endpoint = raw_key.split(ENDPOINT_PREFIX, 1)[-1]
                count = int(cache.get(cache_key, 0))
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

        # ── Reset Redis counters so next persist captures true deltas ──────────
        logger.info("Resetting Redis analytics counters after persist...")
        deleted_keys = 0

        # Reset total request counter (cache-versioned key)
        cache.delete(TOTAL_REQUESTS)

        # Delete unique IPs set
        deleted_keys += redis.delete(UNIQUE_IPS)

        # Delete hourly stats sorted set
        deleted_keys += redis.delete(HOURLY_STATS)

        # Delete daily stats sorted set
        deleted_keys += redis.delete(DAILY_STATS)

        # Delete user agents sorted set
        deleted_keys += redis.delete(USER_AGENTS)

        # Delete collected endpoint keys (already have raw keys from scan above)
        if endpoint_keys_to_delete:
            deleted_keys += redis.delete(*endpoint_keys_to_delete)

        # Delete method stats keys
        method_keys = redis.keys(f"*{METHOD_PREFIX}*")
        if method_keys:
            deleted_keys += redis.delete(*method_keys)

        # Delete IP→endpoints keys
        ip_keys = redis.keys(f"{IP_ENDPOINTS_PREFIX}*")
        if ip_keys:
            deleted_keys += redis.delete(*ip_keys)

        # Delete endpoint→IPs keys
        ep_ip_keys = redis.keys(f"{ENDPOINT_IPS_PREFIX}*")
        if ep_ip_keys:
            deleted_keys += redis.delete(*ep_ip_keys)

        logger.info(f"Cleaned up {deleted_keys} Redis keys after persist")

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Successfully persisted analytics data (ID: {analytics.id})\n"
                f"  - {endpoint_count} endpoints\n"
                f"  - {daily_count} days of traffic\n"
                f"  - {ip_count} IP journeys\n"
                f"  - {deleted_keys} Redis keys reset"
            )
        )

        logger.info(
            f"Persisted analytics ID {analytics.id}: "
            f"{endpoint_count} endpoints, {daily_count} days, {ip_count} IPs"
        )
