"""Redis-lease OCR admission control (global concurrency cap)."""

from __future__ import annotations

import pytest

from core.services.ocr_guard import OcrAdmission, OcrBusy


class _FakeRedis:
    """Minimal redis-py surface: SET NX PX + the release Lua CAS."""

    def __init__(self):
        self.store = {}
        self.last_px = None

    def set(self, key, value, nx=False, px=None):
        self.last_px = px
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def eval(self, script, numkeys, key, token):
        if self.store.get(key) == token:
            del self.store[key]
            return 1
        return 0


class _DownRedis:
    def set(self, *args, **kwargs):
        raise ConnectionError("redis is down")

    def eval(self, *args, **kwargs):  # pragma: no cover - never reached
        raise ConnectionError("redis is down")


def test_caps_concurrency():
    admission = OcrAdmission(slots=2, client=_FakeRedis())

    with admission.slot():
        with admission.slot():
            with pytest.raises(OcrBusy):
                with admission.slot():
                    pass


def test_release_on_exit():
    admission = OcrAdmission(slots=1, client=_FakeRedis())

    with admission.slot():
        pass
    with admission.slot():  # must succeed after release
        pass


def test_release_on_exception():
    admission = OcrAdmission(slots=1, client=_FakeRedis())

    with pytest.raises(ValueError):
        with admission.slot():
            raise ValueError("boom")

    with admission.slot():
        pass


def test_lease_ttl_passed_to_redis():
    client = _FakeRedis()
    admission = OcrAdmission(slots=1, ttl_seconds=30, client=client)

    with admission.slot():
        pass

    assert client.last_px == 30_000


def test_release_is_owner_checked():
    client = _FakeRedis()
    admission = OcrAdmission(slots=1, client=client)

    with admission.slot():
        key = f"{admission.prefix}:0"
        # Another process re-acquired the slot while we still held it.
        client.store[key] = "other-token"

    # The stale release must not delete the new owner's slot.
    assert client.store.get(key) == "other-token"


def test_redis_down_fails_closed():
    admission = OcrAdmission(slots=2, client=_DownRedis())

    with pytest.raises(OcrBusy):
        with admission.slot():
            pass
