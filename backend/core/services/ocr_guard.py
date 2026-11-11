"""
Global OCR admission control.

OCR is a heavy, CPU-bound operation that can be triggered from Celery tasks,
inline task calls and management commands.  Queue-level limits cannot bound it
because extraction is called synchronously from many different tasks.

This module provides a process-independent semaphore backed by Redis lease
keys: at most ``OCR_MAX_CONCURRENT`` OCR runs may exist on the box at once,
regardless of the Celery worker count.  A lease expires after
``OCR_SLOT_TTL_SECONDS`` so a killed process cannot hold a slot forever.

Failure policy: **fail closed**.  If Redis is unavailable OCR is skipped and
logged; failing open is what saturated the host during the 2026-11-10
incident.
"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager

from loguru import logger

# Delete the slot only if we still own it.  Without the CAS a stale release
# could delete a slot that another process has since re-acquired.
RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""


class OcrBusy(Exception):
    """Raised when no OCR slot is available (or Redis is unavailable)."""


def _get_client():
    """Return the Django Redis client (monkeypatchable in tests)."""
    from django_redis import get_redis_connection

    return get_redis_connection("default")


class OcrAdmission:
    """Global cap on simultaneous OCR, independent of worker count."""

    def __init__(
        self,
        *,
        slots: int | None = None,
        ttl_seconds: float | None = None,
        client=None,
        prefix: str = "ocr:slot",
    ):
        self.slots = int(
            slots if slots is not None else os.environ.get("OCR_MAX_CONCURRENT", "2")
        )
        self.ttl_seconds = float(
            ttl_seconds
            if ttl_seconds is not None
            else os.environ.get("OCR_SLOT_TTL_SECONDS", "1800")
        )
        self.prefix = prefix
        self._client = client

    def _redis(self):
        if self._client is not None:
            return self._client
        return _get_client()

    @contextmanager
    def slot(self):
        """Acquire one slot or raise :class:`OcrBusy` immediately."""
        token = uuid.uuid4().hex
        acquired_key: str | None = None

        try:
            client = self._redis()
            ttl_ms = max(1, int(self.ttl_seconds * 1000))
            for index in range(self.slots):
                key = f"{self.prefix}:{index}"
                if client.set(key, token, nx=True, px=ttl_ms):
                    acquired_key = key
                    break
        except OcrBusy:
            raise
        except Exception as exc:
            # Fail closed: no OCR when the admission backend is unavailable.
            logger.bind(error=str(exc)[:200]).warning("ocr_admission_unavailable")
            raise OcrBusy("OCR admission backend unavailable") from exc

        if acquired_key is None:
            logger.bind(max_concurrent=self.slots).warning("ocr_admission_saturated")
            raise OcrBusy("all OCR slots busy")

        try:
            yield
        finally:
            try:
                client.eval(RELEASE_LUA, 1, acquired_key, token)
            except Exception as exc:  # pragma: no cover - lease expires anyway
                logger.bind(slot=acquired_key, error=str(exc)[:200]).warning(
                    "ocr_slot_release_failed"
                )
