"""
Loguru Configuration for JSON Logging

This module configures Loguru to output JSON logs when USE_JSON_LOGGING=true.
It should be imported early in the application lifecycle (e.g., in celery.py, wsgi.py).

Usage:
    from diavgeia_project.logging.loguru_config import configure_loguru
    configure_loguru()  # Call once at app startup
"""

import json
import os
import sys

from loguru import logger


def json_formatter(record):
    """
    Format Loguru records as JSON, matching the structure of python-json-logger.

    This ensures Loguru logs are consistent with standard Python logging when
    USE_JSON_LOGGING is enabled.
    """
    try:
        # Extract exception info if present
        exception_info = None
        if record["exception"] is not None:
            exc = record["exception"]
            exception_info = {
                "type": exc.type.__name__ if exc.type else None,
                "value": str(exc.value) if exc.value else None,
            }

        # Format timestamp with milliseconds (matching Python logging format)
        timestamp = (
            record["time"].strftime("%Y-%m-%d %H:%M:%S.")
            + f"{record['time'].microsecond // 1000:03d}"
        )

        log_record = {
            "timestamp": timestamp,
            "logger": record["name"],
            "level": record["level"].name,
            "message": record["message"],
            "function": record["function"],
            "file": str(record["file"].path),
            "line": record["line"],
        }

        # Add extra context fields if present
        if record["extra"]:
            for key, value in record["extra"].items():
                # Convert non-serializable types to strings
                try:
                    json.dumps(value)
                    log_record[key] = value
                except (TypeError, ValueError):
                    log_record[key] = str(value)

        # Add exception info if present
        if exception_info:
            log_record["exception"] = exception_info

        return json.dumps(log_record, default=str) + "\n"
    except Exception as e:
        # Fallback to simple format if JSON serialization fails
        return (
            json.dumps(
                {
                    "timestamp": record["time"].isoformat(),
                    "level": record["level"].name,
                    "message": str(record["message"]),
                    "error": f"JSON formatting failed: {e}",
                }
            )
            + "\n"
        )


def text_formatter(record):
    """
    Default text formatter for development/debugging.
    Matches Loguru's default format.
    """
    return (
        "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}\n"
        "{exception}"
    )


def configure_loguru():
    """
    Configure Loguru based on USE_JSON_LOGGING environment variable.

    This should be called once at application startup (e.g., in celery.py or wsgi.py).

    When USE_JSON_LOGGING=true:
        - Outputs JSON formatted logs to stdout
        - Compatible with Loki/Grafana ingestion

    When USE_JSON_LOGGING=false or not set:
        - Uses default Loguru text format
        - Better for local development

    Log level controlled by DJANGO_LOG_LEVEL env var (default: INFO)
    """
    use_json_logging = os.getenv("USE_JSON_LOGGING", "false").lower() in (
        "true",
        "1",
        "t",
    )
    log_level = os.getenv("DJANGO_LOG_LEVEL", "INFO")  # Respect DJANGO_LOG_LEVEL

    # Remove default handler
    logger.remove()

    if use_json_logging:
        # Use Loguru's built-in serialize feature for JSON output
        # This avoids format string issues with curly braces
        logger.add(
            sys.stdout,
            serialize=True,  # Built-in JSON serialization
            level=log_level,  # Use env var instead of hardcoded DEBUG
            colorize=False,
            backtrace=True,
            diagnose=False,  # Don't include variable values in production
        )
    else:
        # Add text formatter for development
        logger.add(
            sys.stderr,
            format=text_formatter,
            level=log_level,  # Use env var instead of hardcoded DEBUG
            colorize=True,
            backtrace=True,
            diagnose=True,
        )

    # Log the configuration (this will use the newly configured format)
    logger.info(
        f"Loguru configured with {'JSON' if use_json_logging else 'TEXT'} format at {log_level} level"
    )


# Optional: Context manager for adding structured context to Loguru logs
class LoguruContext:
    """
    Context manager for adding structured metadata to Loguru logs.

    Usage:
        with LoguruContext(document_ada="ABC123", task_id="xyz"):
            logger.info("Processing document")
    """

    def __init__(self, **context):
        self.context = context
        self.token = None

    def __enter__(self):
        self.token = logger.contextualize(**self.context)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            self.token.__exit__(exc_type, exc_val, exc_tb)


# Convenience function for binding context
def bind_context(**context):
    """
    Bind context to logger for all subsequent logs in current scope.

    Usage:
        bind_context(document_ada="ABC123", task_id="xyz")
        logger.info("Processing document")  # Will include document_ada and task_id
    """
    return logger.bind(**context)
