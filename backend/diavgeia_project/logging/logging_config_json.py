"""
JSON Logging Configuration for Django + Loki

This module provides a production-ready logging configuration that:
1. Outputs structured JSON logs to stdout
2. Works with Promtail -> Loki -> Grafana pipeline
3. Supports contextual metadata (ingestion_id, ada, stage, etc.)
4. Compatible with both Django and Celery

Usage:
    In settings.py, replace the LOGGING dict with:

    from diavgeia_project.logging.logging_config_json import get_json_logging_config
    LOGGING = get_json_logging_config(DEBUG)
"""

from pythonjsonlogger import jsonlogger


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """
    Custom JSON formatter that properly handles timestamp with milliseconds.
    """

    def add_fields(self, log_record, record, message_dict):
        super(CustomJsonFormatter, self).add_fields(log_record, record, message_dict)

        # Format timestamp with milliseconds
        if "asctime" in log_record:
            # Convert to our desired format with milliseconds
            import datetime

            dt = datetime.datetime.fromtimestamp(record.created)
            log_record["timestamp"] = (
                dt.strftime("%Y-%m-%d %H:%M:%S.") + f"{int(record.msecs):03d}"
            )
            del log_record["asctime"]

        # Rename fields to match our desired structure
        if "levelname" in log_record:
            log_record["level"] = log_record.pop("levelname")
        if "name" in log_record:
            log_record["logger"] = log_record.pop("name")
        if "funcName" in log_record:
            log_record["function"] = log_record.pop("funcName")
        if "pathname" in log_record:
            log_record["file"] = log_record.pop("pathname")
        if "lineno" in log_record:
            log_record["line"] = log_record.pop("lineno")


def get_json_logging_config(
    debug_mode=False,
    logging_level="INFO",
    celery_level="INFO",
    celery_task_event_level="WARNING",
    db_level="WARNING",
):
    """
    Get logging configuration with JSON formatting.

    Args:
        debug_mode: If True, adds verbose console output for debugging
        logging_level: The logging level to use (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        celery_level: The Celery-specific log level
        celery_task_event_level: Level for noisy per-task logs (strategy/trace), default WARNING
        db_level: The Django DB log level (set to DEBUG to see SQL queries)

    Returns:
        dict: Django LOGGING configuration
    """

    config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": "diavgeia_project.logging.logging_config_json.CustomJsonFormatter",
                "format": "%(asctime)s %(name)s %(levelname)s %(message)s %(funcName)s %(pathname)s %(lineno)d",
            },
            "verbose": {
                "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
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
            "console_json": {
                "level": logging_level,
                "class": "logging.StreamHandler",
                "formatter": "json",
                "stream": "ext://sys.stdout",
            },
            "console_debug": {
                "level": "DEBUG",
                "class": "logging.StreamHandler",
                "formatter": "verbose",
                "filters": ["require_debug_true"],
                "stream": "ext://sys.stderr",
            },
        },
        "root": {
            "level": logging_level,
            "handlers": ["console_json"],
        },
        "loggers": {
            "django": {
                "handlers": ["console_json"],
                "level": logging_level,
                "propagate": False,
            },
            "django.request": {
                "handlers": ["console_json"],
                "level": "ERROR",
                "propagate": False,
            },
            "django.security": {
                "handlers": ["console_json"],
                "level": logging_level,
                "propagate": False,
            },
            # Suppress Django DB query logs unless explicitly enabled
            "django.db.backends": {
                "handlers": ["console_json"],
                "level": db_level,  # WARNING by default, set DB_LOG_LEVEL=DEBUG to see SQL
                "propagate": False,
            },
            "api": {
                "handlers": ["console_json"],
                "level": logging_level,
                "propagate": False,
            },
            "core": {
                "handlers": ["console_json"],
                "level": logging_level,
                "propagate": False,
            },
            "users": {
                "handlers": ["console_json"],
                "level": logging_level,
                "propagate": False,
            },
            # Celery loggers - use separate level
            "celery": {
                "handlers": ["console_json"],
                "level": celery_level,
                "propagate": False,
            },
            "celery.task": {
                "handlers": ["console_json"],
                "level": celery_level,
                "propagate": False,
            },
            "celery.worker": {
                "handlers": ["console_json"],
                "level": celery_level,  # Suppress DEBUG logs from worker.strategy
                "propagate": False,
            },
            "celery.worker.strategy": {
                "handlers": ["console_json"],
                "level": celery_task_event_level,  # "Task X received" — noisy, defaults to WARNING
                "propagate": False,
            },
            "celery.app.trace": {
                "handlers": ["console_json"],
                "level": celery_task_event_level,  # "Task Y succeeded" — noisy, defaults to WARNING
                "propagate": False,
            },
            # Suppress noisy third-party libraries
            "opentelemetry.instrumentation.celery": {
                "handlers": ["console_json"],
                "level": "WARNING",  # Suppress "prerun signal" logs
                "propagate": False,
            },
            "requests": {
                "handlers": ["console_json"],
                "level": "WARNING",
                "propagate": False,
            },
            "urllib3": {
                "handlers": ["console_json"],
                "level": "WARNING",
                "propagate": False,
            },
        },
    }

    # In debug mode, add verbose console output
    if debug_mode:
        config["handlers"]["console_debug"]["level"] = "DEBUG"
        for logger_name in ["django", "api", "core", "celery"]:
            if logger_name in config["loggers"]:
                config["loggers"][logger_name]["handlers"].append("console_debug")

    return config


# Context-aware logger helpers
class StructuredLogger:
    """
    Helper class for adding structured metadata to logs.

    Usage:
        logger = StructuredLogger('core.pipeline')
        logger.info("Processing started", ingestion_id="abc123", ada="TEST-ADA")
    """

    def __init__(self, name):
        import logging

        self.logger = logging.getLogger(name)

    def _log(self, level, message, **context):
        """Log with structured context as extra fields"""
        # Filter out None values to keep JSON clean
        extra = {k: v for k, v in context.items() if v is not None}
        getattr(self.logger, level)(message, extra=extra)

    def debug(self, message, **context):
        self._log("debug", message, **context)

    def info(self, message, **context):
        self._log("info", message, **context)

    def warning(self, message, **context):
        self._log("warning", message, **context)

    def error(self, message, **context):
        self._log("error", message, **context)

    def exception(self, message, **context):
        """Log exception with traceback"""
        extra = {k: v for k, v in context.items() if v is not None}
        self.logger.exception(message, extra=extra)


# Example usage in pipeline
"""
from diavgeia_project.logging.logging_config_json import StructuredLogger

class DecisionPipelineOrchestrator:
    def __init__(self):
        self.logger = StructuredLogger('core.pipeline')

    def run_pipeline(self, decision_ada: str, force_reprocess: bool = False):
        import uuid
        ingestion_id = str(uuid.uuid4())[:8]

        self.logger.info(
            "Pipeline started",
            ingestion_id=ingestion_id,
            ada=decision_ada,
            force_reprocess=force_reprocess
        )

        # All subsequent logs can include the same context
        self.logger.info(
            "Entity extraction started",
            ingestion_id=ingestion_id,
            ada=decision_ada,
            stage="entity_extraction"
        )

        try:
            # ... processing ...
            self.logger.info(
                "Pipeline completed",
                ingestion_id=ingestion_id,
                ada=decision_ada,
                duration_ms=1234
            )
        except Exception as e:
            self.logger.exception(
                "Pipeline failed",
                ingestion_id=ingestion_id,
                ada=decision_ada,
                error_type=type(e).__name__
            )

# Then in Grafana:
# {component="celery"} | json | ingestion_id="abc12345"
# {component="celery"} | json | ada="ΨΨ4746ΛΕΑΩ-ΩΞΨ"
# {component="celery"} | json | stage="entity_extraction"
"""
