"""
Celery task for the admin request profiler.

The profiler runs real Django requests through ``django.test.Client`` and can
take much longer than a web request allows (cold aggregates, EXPLAIN ANALYZE,
multiple endpoints). Running it in a worker keeps the admin POST from hitting
the nginx/gunicorn 504 timeout; the admin page polls the task state instead.
"""

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from loguru import logger

from core.services.request_profiler import profile_requests


@shared_task(
    bind=True,
    name="admin.profile_request",
    soft_time_limit=600,
    time_limit=660,
)
def profile_request_task(self, paths, options):
    """Profile the given API paths and return the payload."""
    self.update_state(
        state="STARTED",
        meta={
            "status": f"Profiling {len(paths)} request(s)...",
            "targets": len(paths),
        },
    )
    try:
        return profile_requests(paths, **options)
    except SoftTimeLimitExceeded:
        logger.error(
            "[RequestProfiler] Task exceeded the soft time limit "
            f"({len(paths)} target(s))"
        )
        raise
    except Exception:
        logger.exception(f"[RequestProfiler] Task failed ({len(paths)} target(s))")
        raise
