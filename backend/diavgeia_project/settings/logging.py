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
# Separate level for noisy per-task "received/succeeded" messages.
# These fire once per task and flood Grafana during imports (hundreds/sec).
# Default WARNING hides them; set to INFO to bring them back for debugging.
CELERY_TASK_EVENT_LOG_LEVEL = os.getenv("CELERY_TASK_EVENT_LOG_LEVEL", "WARNING")
DB_LOG_LEVEL = os.getenv(
    "DB_LOG_LEVEL", "WARNING"
)  # Only show DB queries on WARNING+ unless explicitly enabled

# Search pipeline instrumentation (Track A measurement / E6 slow-query alerting).
# DEBUG_SEARCH_SERVICE=1 -> per-request search traces (search_id, tier decisions,
#   transliteration, per-type timing/counts) logged at INFO as SEARCH_TRACE lines.
# SEARCH_SLOW_QUERY_THRESHOLD (seconds, default 0=off) -> SLOW_SEARCH warnings for
#   any decorated search call exceeding the threshold. Safe to leave on in prod.
DEBUG_SEARCH_SERVICE = os.getenv("DEBUG_SEARCH_SERVICE", "False").lower() in (
    "true",
    "1",
    "t",
)
SEARCH_SLOW_QUERY_THRESHOLD = float(
    os.getenv("SEARCH_SLOW_QUERY_THRESHOLD", "0") or 0
)

# Backward compatibility: Keep JSON_LOGGING_LEVEL for now
JSON_LOGGING_LEVEL = os.getenv("JSON_LOGGING_LEVEL", DJANGO_LOG_LEVEL)

# Rolling file logging in addition to console/stdout. Keeps the app debuggable
# when Loki/Promtail/Grafana are absent (minimal stack). Opt out with
# LOG_TO_FILE=false.
LOG_TO_FILE = os.getenv("LOG_TO_FILE", "true").lower() in ("true", "1", "t")

if USE_JSON_LOGGING:
    # JSON structured logging for Grafana/Loki
    from diavgeia_project.logging.logging_config_json import get_json_logging_config

    LOGGING = get_json_logging_config(
        debug_mode=DEBUG,
        logging_level=DJANGO_LOG_LEVEL,
        celery_level=CELERY_LOG_LEVEL,
        celery_task_event_level=CELERY_TASK_EVENT_LOG_LEVEL,
        db_level=DB_LOG_LEVEL,
        log_to_file=LOG_TO_FILE,
        file_path=os.path.join(BASE_DIR, "logs", "django.log"),
    )
else:
    # Traditional text logging (default)
    # Handler lists, gated by LOG_TO_FILE
    _file_handlers = ["console", "file"] if LOG_TO_FILE else ["console"]
    _file_error_handlers = (
        ["console", "file", "mail_admins"] if LOG_TO_FILE else ["console", "mail_admins"]
    )

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
                "maxBytes": 5_000_000,  # 5MB — capped for minimal-stack deployments
                "backupCount": 3,  # at most ~20MB of django.log* total
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
            "handlers": _file_handlers,
        },
        "loggers": {
            "django": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "django.request": {
                "handlers": _file_error_handlers,
                "level": "ERROR",
                "propagate": False,
            },
            "django.security": {
                "handlers": _file_error_handlers,
                "level": "INFO",
                "propagate": False,
            },
            # Custom app loggers
            "api": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "core": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "users": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            # Celery logging
            "celery": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "celery.task": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "celery.worker": {
                "handlers": _file_handlers,
                "level": "INFO",
                "propagate": False,
            },
            "celery.worker.strategy": {
                "handlers": _file_handlers,
                "level": CELERY_TASK_EVENT_LOG_LEVEL,  # "Task X received" — noisy, default WARNING
                "propagate": False,
            },
            "celery.app.trace": {
                "handlers": _file_handlers,
                "level": CELERY_TASK_EVENT_LOG_LEVEL,  # "Task Y succeeded" — noisy, default WARNING
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
