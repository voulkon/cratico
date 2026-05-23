"""
Logging configuration.

Contains LOGGING settings for both JSON and text-based logging.
"""

import os

# Import from base module for BASE_DIR and DEBUG
from .base import BASE_DIR, DEBUG

# Logging Configuration
# Control logging format via environment variable:
# USE_JSON_LOGGING=true  -> JSON structured logging (for Loki/Grafana)
# USE_JSON_LOGGING=false -> Regular text logging (default)
#
# Control log levels:
# DJANGO_LOG_LEVEL     -> Overall log level (default: INFO)
# CELERY_LOG_LEVEL     -> Celery-specific log level (default: INFO)
# DB_LOG_LEVEL         -> Django DB query logs (default: WARNING, set to DEBUG to see SQL)
USE_JSON_LOGGING = os.getenv("USE_JSON_LOGGING", "false").lower() in ("true", "1", "t")
DJANGO_LOG_LEVEL = os.getenv(
    "DJANGO_LOG_LEVEL", "INFO"
)  # Changed default from DEBUG to INFO
CELERY_LOG_LEVEL = os.getenv("CELERY_LOG_LEVEL", "INFO")
DB_LOG_LEVEL = os.getenv(
    "DB_LOG_LEVEL", "WARNING"
)  # Only show DB queries on WARNING+ unless explicitly enabled

# Backward compatibility: Keep JSON_LOGGING_LEVEL for now
JSON_LOGGING_LEVEL = os.getenv("JSON_LOGGING_LEVEL", DJANGO_LOG_LEVEL)

if USE_JSON_LOGGING:
    # JSON structured logging for Grafana/Loki
    from diavgeia_project.logging.logging_config_json import get_json_logging_config

    LOGGING = get_json_logging_config(
        debug_mode=DEBUG,
        logging_level=DJANGO_LOG_LEVEL,
        celery_level=CELERY_LOG_LEVEL,
        db_level=DB_LOG_LEVEL,
    )
else:
    # Traditional text logging (default)
    LOGGING = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "verbose": {
                "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
                "style": "{",
            },
            "json": {
                "()": "pythonjsonlogger.json.JsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(pathname)s %(lineno)d %(funcName)s %(process)d %(thread)d",
                "datefmt": "%Y-%m-%d %H:%M:%S",
            },
            "simple": {
                "format": "{levelname} {message}",
                "style": "{",
            },
        },
        "filters": {
            "require_debug_false": {
                "()": "django.utils.log.RequireDebugFalse",
            },
            "require_debug_true": {
                "()": "django.utils.log.RequireDebugTrue",
            },
        },
        "handlers": {
            "console": {
                "level": "INFO",
                "class": "logging.StreamHandler",
                "formatter": "json" if not DEBUG else "verbose",
            },
            "console_debug": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "filters": ["require_debug_true"],
            },
            "file": {
                "level": "INFO",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": os.path.join(BASE_DIR, "logs", "django.log"),
                "maxBytes": 1024 * 1024 * 15,  # 15MB
                "backupCount": 10,
                "formatter": "json",
            },
            "mail_admins": {
                "level": "ERROR",
                "class": "django.utils.log.AdminEmailHandler",
                "filters": ["require_debug_false"],
                "formatter": "verbose",
            },
        },
        "root": {
            "level": "INFO",
            "handlers": ["console"],
        },
        "loggers": {
            "django": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console", "file", "mail_admins"],
                "level": "ERROR",
                "propagate": False,
            },
            "django.security": {
                "handlers": ["console", "file", "mail_admins"],
                "level": "INFO",
                "propagate": False,
            },
            # Custom app loggers
            "api": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "core": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "users": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            # Celery logging
            "celery": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            "celery.task": {
                "handlers": ["console", "file"],
                "level": "INFO",
                "propagate": False,
            },
            # Third party
            "requests": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
            "urllib3": {
                "handlers": ["console"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }

# Create logs directory if it doesn't exist
LOGS_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOGS_DIR, exist_ok=True)
