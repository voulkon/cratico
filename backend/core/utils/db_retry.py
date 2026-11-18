"""Small retry helper for the first database access of a Celery task.

A worker child that starts after a long fetch may find its pooled connection
expired and the upstream transiently refusing new connections.  Retrying the
connect a few times with jitter converts that transient failure into a short
delay instead of a lost task.
"""

import random
import time

from django.db import InterfaceError, OperationalError, connections
from loguru import logger

RETRYABLE_DB_ERRORS = (OperationalError, InterfaceError)


def ensure_db_connection(max_attempts: int = 3, base_delay: float = 1.0) -> None:
    """Ensure the default DB connection answers a trivial query.

    Retries with jitter and reconnects when the existing connection is dead.
    Raises the last retryable error after ``max_attempts``.
    """
    connection = connections["default"]

    for attempt in range(max_attempts):
        try:
            if connection.connection is None:
                connection.ensure_connection()
            else:
                # Cheap liveness probe.  ``ensure_connection()`` alone returns
                # immediately when a connection object exists, even if the
                # server has closed it.
                with connection.cursor() as cursor:
                    cursor.execute("SELECT 1")
            return
        except RETRYABLE_DB_ERRORS as exc:
            try:
                connection.close()
            except Exception:
                pass

            if attempt >= max_attempts - 1:
                raise
            delay = base_delay * (3**attempt) + random.uniform(0, base_delay)
            logger.warning(
                f"DB connect attempt {attempt + 1}/{max_attempts} failed "
                f"({exc}); retrying in {delay:.1f}s"
            )
            time.sleep(delay)
