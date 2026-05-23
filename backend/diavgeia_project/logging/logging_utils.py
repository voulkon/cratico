"""
Centralized logging utility for consistent log formatting across all services.

This module provides:
- Structured logging with OpenTelemetry trace correlation
- Service-specific context (Django, Celery, etc.)
- Task and endpoint context
- Consistent JSON formatting for Loki ingestion
"""

import json
import logging
import os
import threading
from contextlib import contextmanager
from typing import Any, Dict, Optional

from api.utils.common import get_client_ip
from django.core.serializers.json import DjangoJSONEncoder
from opentelemetry import trace


class ContextLogger:
    """
    Enhanced logger that automatically includes context information
    like service name, trace IDs, task IDs, and endpoint information.
    """

    def __init__(self, name: str, service_name: Optional[str] = None):
        self.logger = logging.getLogger(name)
        self.service_name = service_name or self._detect_service_name()
        self._local = threading.local()

    def _detect_service_name(self) -> str:
        """Detect service name from environment or process context"""
        # Check if running in Celery
        if "celery" in os.environ.get("_", "").lower():
            return "diavgeia-worker"

        # Check environment variable
        service_name = os.environ.get("SERVICE_NAME")
        if service_name:
            return service_name

        # Default to Django
        return "diavgeia-backend"

    def _get_trace_context(self) -> Dict[str, str]:
        """Extract OpenTelemetry trace context"""
        span = trace.get_current_span()
        if span and span.is_recording():
            span_context = span.get_span_context()
            return {
                "trace_id": format(span_context.trace_id, "032x"),
                "span_id": format(span_context.span_id, "016x"),
            }
        return {}

    def _get_base_extra(self) -> Dict[str, Any]:
        """Get base extra context for all log messages"""
        extra = {
            "service_name": self.service_name,
            "timestamp": None,  # Will be set by formatter
        }

        # Add trace context
        extra.update(self._get_trace_context())

        # Add thread-local context if available
        if hasattr(self._local, "context"):
            extra.update(self._local.context)

        return extra

    @contextmanager
    def context(self, **kwargs):
        """Context manager to add temporary context to logs"""
        if not hasattr(self._local, "context"):
            self._local.context = {}

        old_context = self._local.context.copy()
        self._local.context.update(kwargs)

        try:
            yield
        finally:
            self._local.context = old_context

    def set_context(self, **kwargs):
        """Set persistent context for the current thread"""
        if not hasattr(self._local, "context"):
            self._local.context = {}
        self._local.context.update(kwargs)

    def clear_context(self):
        """Clear all context for the current thread"""
        if hasattr(self._local, "context"):
            self._local.context = {}

    def _log(self, level: int, msg: str, *args, **kwargs):
        """Internal logging method with automatic context"""
        extra = self._get_base_extra()

        # Merge with any extra provided
        if "extra" in kwargs:
            extra.update(kwargs["extra"])
        kwargs["extra"] = extra

        self.logger.log(level, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def critical(self, msg: str, *args, **kwargs):
        self._log(logging.CRITICAL, msg, *args, **kwargs)

    def exception(self, msg: str, *args, **kwargs):
        kwargs["exc_info"] = True
        self.error(msg, *args, **kwargs)


class APILogger(ContextLogger):
    """Logger specialized for Django API endpoints"""

    def __init__(self, name: str = "api"):
        super().__init__(name, "diavgeia-backend")

    def log_request(self, request, response=None, duration_ms=None):
        """Log API request with comprehensive context"""
        context = {
            "endpoint": request.path,
            "method": request.method,
            "user_id": (
                getattr(request.user, "id", None) if hasattr(request, "user") else None
            ),
            "ip_address": get_client_ip(request),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:200],  # Truncate
        }

        if response:
            context["status_code"] = response.status_code
            context["response_size"] = len(getattr(response, "content", b""))

        if duration_ms:
            context["duration_ms"] = duration_ms

        with self.context(**context):
            if response and response.status_code >= 400:
                self.warning(
                    f"{request.method} {request.path} - {response.status_code}"
                )
            else:
                self.info(f"{request.method} {request.path}")


# get_client_ip is now imported from api.utils.common


class TaskLogger(ContextLogger):
    """Logger specialized for Celery tasks"""

    def __init__(self, name: str = "celery.task"):
        super().__init__(name, "diavgeia-worker")

    def log_task_start(self, task_name: str, task_id: str, args=None, kwargs=None):
        """Log task start with context"""
        context = {
            "task_name": task_name,
            "task_id": task_id,
            "task_args": self._safe_serialize(args),
            "task_kwargs": self._safe_serialize(kwargs),
        }

        with self.context(**context):
            self.info(f"Task started: {task_name}")

    def log_task_success(
        self, task_name: str, task_id: str, duration_s: float, result=None
    ):
        """Log task success"""
        context = {
            "task_name": task_name,
            "task_id": task_id,
            "duration_s": duration_s,
            "result": self._safe_serialize(result),
        }

        with self.context(**context):
            self.info(f"Task completed successfully: {task_name}")

    def log_task_failure(
        self, task_name: str, task_id: str, duration_s: float, error: Exception
    ):
        """Log task failure"""
        context = {
            "task_name": task_name,
            "task_id": task_id,
            "duration_s": duration_s,
            "error_type": type(error).__name__,
            "error_message": str(error)[:500],  # Truncate long messages
        }

        with self.context(**context):
            self.error(f"Task failed: {task_name}", exc_info=True)

    def _safe_serialize(self, obj) -> str:
        """Safely serialize objects for logging"""
        if obj is None:
            return None

        try:
            return json.dumps(obj, cls=DjangoJSONEncoder, default=str)[
                :1000
            ]  # Truncate
        except (TypeError, ValueError):
            return str(obj)[:1000]  # Fallback to string representation


# Singleton instances for easy import
api_logger = APILogger()
task_logger = TaskLogger()


# Factory function for custom loggers
def get_logger(name: str, service_name: Optional[str] = None) -> ContextLogger:
    """Get a context logger instance"""
    return ContextLogger(name, service_name)


# Utility decorators
def log_api_calls(logger: APILogger = None):
    """Decorator to automatically log API calls"""
    if logger is None:
        logger = api_logger

    def decorator(view_func):
        def wrapper(request, *args, **kwargs):
            import time

            start_time = time.time()

            try:
                response = view_func(request, *args, **kwargs)
                duration_ms = (time.time() - start_time) * 1000
                logger.log_request(request, response, duration_ms)
                return response
            except Exception:
                duration_ms = (time.time() - start_time) * 1000
                logger.log_request(request, duration_ms=duration_ms)
                logger.exception(f"API call failed: {request.path}")
                raise

        return wrapper

    return decorator


def log_task_execution(logger: TaskLogger = None):
    """Decorator to automatically log task execution"""
    if logger is None:
        logger = task_logger

    def decorator(task_func):
        def wrapper(*args, **kwargs):
            import time

            from celery import current_task

            task = current_task
            task_name = task.name if task else task_func.__name__
            task_id = task.request.id if task else "unknown"

            start_time = time.time()
            logger.log_task_start(task_name, task_id, args, kwargs)

            try:
                result = task_func(*args, **kwargs)
                duration_s = time.time() - start_time
                logger.log_task_success(task_name, task_id, duration_s, result)
                return result
            except Exception as e:
                duration_s = time.time() - start_time
                logger.log_task_failure(task_name, task_id, duration_s, e)
                raise

        return wrapper

    return decorator
