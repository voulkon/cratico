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
    Return a LOGURU FORMAT STRING that produces flat JSON.

    IMPORTANT: loguru treats callable ``format`` as returning a *format string*
    (with {placeholders}), NOT the final output.  Double-braces {{ }} are
    literal braces in the final output; single braces {field} are loguru
    placeholders.
    """
    # Build extra-field placeholders dynamically from record["extra"].
    # We embed them as literal JSON key-value pairs inside the format string.
    extra_placeholders = ""
    if record["extra"]:
        parts = []
        for key, value in record["extra"].items():
            # Embed the JSON-escaped value directly as literal text in the
            # format string (not as a loguru placeholder).
            try:
                escaped_val = json.dumps(value, default=str)
            except (TypeError, ValueError):
                escaped_val = json.dumps(str(value))
            # Escape { and } so they are not interpreted as format-map
            # placeholders by str.format_map when the format string is
            # rendered.  Without this, a dict value like {"processed": 1}
            # causes KeyError: '"processed"' because format_map sees
            # {"processed" as a replacement field.
            escaped_val = escaped_val.replace("{", "{{").replace("}", "}}")
            parts.append(f'"{key}": {escaped_val}')
        if parts:
            extra_placeholders = ", " + ", ".join(parts)

    # Exception placeholder (only meaningful if exception is not None)
    exc_placeholder = ""
    if record["exception"] is not None:
        exc_placeholder = ', "exception": "{exception}"'

    return (
        '{{"timestamp": "{time:YYYY-MM-DD HH:mm:ss.SSS}",'
        ' "level": "{level}",'
        ' "logger": "{name}",'
        ' "message": "{message}",'
        ' "function": "{function}",'
        ' "file": "{file}",'
        ' "line": {line}'
        + extra_placeholders
        + exc_placeholder
        + "}}\n"
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
        # json_formatter returns a loguru *format string* that produces flat JSON.
        # loguru interpolates {time}, {level}, {name}, {message}, etc. and the
        # double-braces {{ }} become literal braces → valid flat JSON.
        logger.add(
            sys.stdout,
            format=json_formatter,  # Returns format string → flat JSON
            level=log_level,
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
