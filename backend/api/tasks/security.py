"""Celery tasks for security monitoring — offloaded from the hot request path."""

from celery import shared_task
from loguru import logger


@shared_task(
    name="api.tasks.security.persist_endpoint_access_log",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def persist_endpoint_access_log(
    ip_address: str,
    endpoint: str,
    method: str,
    query_params: dict | None,
    user_agent: str | None,
    status_code: int | None,
    response_time_ms: int | None,
    user_id: int | None,
    is_flagged: bool,
    flag_reason: str,
):
    """
    Persist a single EndpointAccessLog row asynchronously.

    Offloaded from the response middleware so that forensic DB writes
    don't add latency to the request path or become a write-amplification
    DoS vector when a flagged IP is sending a burst of requests.
    """
    from api.models import EndpointAccessLog
    from django.contrib.auth import get_user_model

    User = get_user_model()

    user_obj = None
    if user_id is not None:
        try:
            user_obj = User.objects.only("id").get(pk=user_id)
        except User.DoesNotExist:
            pass

    try:
        EndpointAccessLog.objects.create(
            ip_address=ip_address,
            endpoint=endpoint,
            method=method,
            query_params=query_params,
            user_agent=user_agent,
            status_code=status_code,
            response_time_ms=response_time_ms,
            user=user_obj,
            is_flagged=is_flagged,
            # flag_reason is a non-nullable CharField (default=""). Coerce None
            # → "" so the row doesn't fail a NOT NULL constraint and get
            # silently swallowed by the except below (task would report
            # SUCCESS in Flower but no row would be written).
            flag_reason=flag_reason or "",
        )
    except Exception:
        logger.exception("Failed to persist EndpointAccessLog (async)")
