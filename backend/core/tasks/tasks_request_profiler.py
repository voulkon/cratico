"""
Celery task for the admin request profiler.

The profiler runs real Django requests through ``django.test.Client`` and can
take much longer than a web request allows. The run is persisted in
``RequestProfileRun`` so the admin page can show status, partial results,
revoke the job, and compare runs across improvements.
"""

import traceback

from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from django.utils import timezone
from loguru import logger

from core.models.request_profile_run import RequestProfileRun
from core.services.request_profiler import profile_requests


@shared_task(
    name="admin.profile_request",
    soft_time_limit=600,
    time_limit=660,
    ignore_result=True,
)
def profile_request_task(run_id, paths, options):
    """Profile the given API paths and persist progress and the final result."""
    run = RequestProfileRun.objects.filter(pk=run_id).first()
    if run is None:
        logger.warning(f"[RequestProfiler] Run {run_id} no longer exists")
        return
    if run.status == RequestProfileRun.Status.REVOKED:
        logger.info(f"[RequestProfiler] Run {run_id} was revoked before start")
        return

    RequestProfileRun.objects.filter(
        pk=run_id,
        status__in=[RequestProfileRun.Status.PENDING, RequestProfileRun.Status.STARTED],
    ).update(status=RequestProfileRun.Status.STARTED, started_at=timezone.now())

    def save_progress(payload):
        RequestProfileRun.objects.filter(
            pk=run_id, status=RequestProfileRun.Status.STARTED
        ).update(result=payload)

    try:
        result = profile_requests(paths, progress=save_progress, **options)
    except SoftTimeLimitExceeded:
        RequestProfileRun.objects.filter(
            pk=run_id, status=RequestProfileRun.Status.STARTED
        ).update(
            status=RequestProfileRun.Status.FAILURE,
            error="Profiler exceeded the 10-minute soft time limit.",
            finished_at=timezone.now(),
        )
        logger.error(
            f"[RequestProfiler] Run {run_id} exceeded the soft time limit "
            f"({len(paths)} target(s))"
        )
        raise
    except Exception:
        RequestProfileRun.objects.filter(
            pk=run_id, status=RequestProfileRun.Status.STARTED
        ).update(
            status=RequestProfileRun.Status.FAILURE,
            error=traceback.format_exc(),
            finished_at=timezone.now(),
        )
        logger.exception(
            f"[RequestProfiler] Run {run_id} failed ({len(paths)} target(s))"
        )
        raise

    RequestProfileRun.objects.filter(
        pk=run_id, status=RequestProfileRun.Status.STARTED
    ).update(
        status=RequestProfileRun.Status.SUCCESS,
        result=result,
        finished_at=timezone.now(),
    )
