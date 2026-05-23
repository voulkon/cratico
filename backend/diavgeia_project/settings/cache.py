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

# Cache configuration
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/{DEFAULT_REDIS_DB}",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,  # Empty string if no password
        },
    },
    # Dedicated DB 2 for import decision chunks (separate from Django cache and Celery)
    IMPORT_CHUNKS_REDIS_DB_NAME: {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/2",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "PASSWORD": REDIS_PASSWORD,
        },
    },
}
