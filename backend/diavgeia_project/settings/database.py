"""
Database configuration.

Contains DATABASES settings for PostgreSQL.
"""

import os
from urllib.parse import urlparse

# Database configuration - use DATABASE_URL if available, otherwise individual vars
DATABASE_URL = os.environ.get("DATABASE_URL")
CONN_MAX_AGE = int(os.environ.get("DB_CONN_MAX_AGE", 60))  # Default to 60 seconds
if DATABASE_URL:
    # Parse DATABASE_URL
    parsed = urlparse(DATABASE_URL)

    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": parsed.path.lstrip("/"),
            "USER": parsed.username,
            "PASSWORD": parsed.password,
            "HOST": parsed.hostname,
            "PORT": parsed.port or 5432,
            "OPTIONS": {
                "connect_timeout": 60,
                # statement_timeout removed - PgBouncer doesn't support it in transaction mode
            },
            "CONN_MAX_AGE": CONN_MAX_AGE,  # Persist connections to reduce handshake overhead
            "CONN_HEALTH_CHECKS": True,  # Enable connection health checks
            "DISABLE_SERVER_SIDE_CURSORS": True,  # Required for PgBouncer transaction pooling
        }
    }
else:
    # Fallback to individual environment variables
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "local_diavgia"),
            "USER": os.environ.get("POSTGRES_USER", "local_user"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "local_pass"),
            "HOST": os.environ.get("DB_HOST", "db"),
            "PORT": os.environ.get("DB_PORT", "5432"),
            "OPTIONS": {
                "connect_timeout": 60,
                # statement_timeout removed - PgBouncer doesn't support it in transaction mode
            },
            "CONN_MAX_AGE": CONN_MAX_AGE,  # Persist connections to reduce handshake overhead
            "CONN_HEALTH_CHECKS": True,  # Enable connection health checks
            "DISABLE_SERVER_SIDE_CURSORS": True,  # Required for PgBouncer transaction pooling
        }
    }
