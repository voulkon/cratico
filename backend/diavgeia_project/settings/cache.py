"""
Cache configuration.

Contains CACHES settings for Redis.
"""

import os

from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME

# Redis settings for direct access (expose to Django)
REDIS_HOST = os.environ.get("REDIS_HOST", "redis")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "")
DEFAULT_REDIS_DB = int(os.environ.get("REDIS_DB", "1"))

# Bound every Redis socket operation.  Without these, redis-py blocks forever
# on a stalled/unresponsive Redis (it passes socket_timeout=None by default),
# inside a C-level socket read that masks Python signals — so the request hangs
# with NO log and NO traceback, and the proxy eventually reports 499/524.
# That is what made the admin feedback pool appear to "time out" even though
# the view itself finished in milliseconds (its response-phase security
# middleware does several synchronous Redis calls).  See
# docs/lessons_learnt/runaway_query_lock_pileup.md.
REDIS_SOCKET_TIMEOUT = float(os.environ.get("REDIS_SOCKET_TIMEOUT", "5"))
REDIS_SOCKET_CONNECT_TIMEOUT = float(
    os.environ.get("REDIS_SOCKET_CONNECT_TIMEOUT", "5")
)

# Cache configuration
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{DEFAULT_REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,  # Empty string if no password
            "SOCKET_TIMEOUT": REDIS_SOCKET_TIMEOUT,
            "SOCKET_CONNECT_TIMEOUT": REDIS_SOCKET_CONNECT_TIMEOUT,
        },
    },
    # Dedicated DB 2 for import decision chunks (separate from Django cache and Celery)
    IMPORT_CHUNKS_REDIS_DB_NAME: {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/2",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,
            "SOCKET_TIMEOUT": REDIS_SOCKET_TIMEOUT,
            "SOCKET_CONNECT_TIMEOUT": REDIS_SOCKET_CONNECT_TIMEOUT,
        },
    },
}
