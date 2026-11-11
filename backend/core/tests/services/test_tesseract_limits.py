"""
Bounded OCR behaviour (2026-11-10 OCR concurrency incident).

No tesseract binary, PyMuPDF or Pillow is required: the extractor's imports
are replaced with tiny fakes.  These tests pin the three budgets — page cap,
per-page timeout, document deadline — plus the pixel cap, the opt-in
confidence pass and the Redis admission guard.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager

import pytest
from loguru import logger

from core.services.extractors import tesseract as tess
from core.services.ocr_guard import OcrBusy


class _FakeImage:
    def __init__(self, size):
        self.size = size
        self.resized_to = None

    def resize(self, size, resample=None):
        self.resized_to = size
        return _FakeImage(size)


class _FakeImageModule(types.ModuleType):
    def __init__(self):
        super().__init__("PIL.Image")
        self.open_size = (100, 100)
        self.last_opened = None
        self.Resampling = types.SimpleNamespace(LANCZOS=1)

    def open(self, _fp):
        self.last_opened = _FakeImage(self.open_size)
        return self.last_opened


class _FakePage:
    def __init__(self):
        self.pixmap_calls = 0

    def get_pixmap(self, matrix=None, alpha=False):
        self.pixmap_calls += 1
        return types.SimpleNamespace(tobytes=lambda fmt: b"fake-png")


class _FakeDoc:
    def __init__(self, pages):
        self._pages = pages
        self.closed = False

    def __iter__(self):
        return iter(self._pages)

    def close(self):
        self.closed = True


class _FakePyMuPDF(types.ModuleType):
    def __init__(self, page_count):
        super().__init__("pymupdf")
        self.pages = [_FakePage() for _ in range(page_count)]
        self.last_doc = None

    class Matrix:
        def __init__(self, x, y):
            self.x = x
            self.y = y

    def open(self, _path):
        self.last_doc = _FakeDoc(self.pages)
        return self.last_doc


class _FakePyTesseract:
    Output = types.SimpleNamespace(DICT="dict")

    def __init__(self, responder=None):
        self.calls = []
        self.data_calls = 0
        self._responder = responder or (lambda _index: "page text")

    def image_to_string(self, image, lang=None, config=None, timeout=None):
        index = len(self.calls)
        self.calls.append({"lang": lang, "config": config, "timeout": timeout})
        return self._responder(index)

    def image_to_data(self, *args, **kwargs):
        self.data_calls += 1
        return {"conf": [], "text": []}


@contextmanager
def _open_slot():
    yield


class _FakeAdmission:
    def slot(self):
        return _open_slot()


@pytest.fixture
def ocr_env(monkeypatch, tmp_path):
    """Install fake imports and return a namespace with wiring helpers."""
    image_module = _FakeImageModule()
    pil_module = types.ModuleType("PIL")
    pil_module.Image = image_module
    monkeypatch.setitem(sys.modules, "PIL", pil_module)
    monkeypatch.setitem(sys.modules, "PIL.Image", image_module)

    state = types.SimpleNamespace(
        image=image_module,
        pdf=_FakePyMuPDF(1),
        pytesseract=_FakePyTesseract(),
        path=str(tmp_path / "doc.pdf"),
    )
    with open(state.path, "wb") as handle:
        handle.write(b"%PDF-fake")

    def configure(page_count=1, pytesseract=None, responder=None):
        state.pdf = _FakePyMuPDF(page_count)
        monkeypatch.setitem(sys.modules, "pymupdf", state.pdf)
        state.pytesseract = pytesseract or _FakePyTesseract(responder)
        monkeypatch.setattr(tess, "_require_tesseract", lambda: state.pytesseract)
        monkeypatch.setattr(tess, "OcrAdmission", lambda *a, **k: _FakeAdmission())

    def run():
        return tess.TesseractExtractor().extract_text(state.path)

    state.configure = configure
    state.run = run
    configure()
    return state


def test_page_timeout_passed(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_PAGE_TIMEOUT", 7.5)
    ocr_env.configure(page_count=1)

    ocr_env.run()

    assert ocr_env.pytesseract.calls[0]["timeout"] == 7.5


def test_page_timeout_skips_page(ocr_env, monkeypatch):
    def responder(index):
        if index == 0:
            raise RuntimeError("Tesseract timeout after 60 seconds")
        return "page two"

    ocr_env.configure(page_count=2, responder=responder)

    result = ocr_env.run()

    assert len(ocr_env.pytesseract.calls) == 2
    assert result.text == "page two"
    assert result.metadata["pages_ocrd"] == 1
    assert result.pages_data[0]["page_number"] == 2


def test_max_pages(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_MAX_PAGES", 5)
    monkeypatch.setattr(tess, "OCR_MAX_SECONDS", 10_000)
    ocr_env.configure(page_count=30)

    result = ocr_env.run()

    assert len(ocr_env.pytesseract.calls) == 5
    assert result.metadata["pages_truncated"] is True
    assert result.metadata["pages_ocrd"] == 5


def test_document_deadline(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_MAX_SECONDS", 50)
    monkeypatch.setattr(tess, "OCR_MAX_PAGES", 20)
    # First four readings are "inside" the window; from the page-2 deadline
    # check onward the clock is past the deadline.
    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 5 if ticks["n"] <= 4 else 100

    monkeypatch.setattr(tess.time, "monotonic", clock)
    ocr_env.configure(page_count=3)

    result = ocr_env.run()

    assert result.metadata["pages_truncated"] is True
    assert result.metadata["pages_ocrd"] == 1
    assert len(ocr_env.pytesseract.calls) == 1


def test_pixel_cap_downscales(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_MAX_PIXELS", 1_000_000)
    ocr_env.image.open_size = (20_000, 20_000)
    ocr_env.configure(page_count=1)

    ocr_env.run()

    assert ocr_env.image.last_opened.resized_to is not None
    width, height = ocr_env.image.last_opened.resized_to
    assert width * height <= 1_000_000
    assert width <= 20_000 and height <= 20_000


def test_confidence_second_pass_opt_in(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_COMPUTE_CONFIDENCE", False)
    ocr_env.configure(page_count=1)
    ocr_env.run()
    assert ocr_env.pytesseract.data_calls == 0

    monkeypatch.setattr(tess, "OCR_COMPUTE_CONFIDENCE", True)
    ocr_env.configure(page_count=1)
    ocr_env.run()
    assert ocr_env.pytesseract.data_calls == 1


def test_partial_text_returned(ocr_env, monkeypatch):
    monkeypatch.setattr(tess, "OCR_MAX_SECONDS", 50)

    ticks = {"n": 0}

    def clock():
        ticks["n"] += 1
        return 5 if ticks["n"] <= 4 else 100

    monkeypatch.setattr(tess.time, "monotonic", clock)
    ocr_env.configure(page_count=2, responder=lambda _index: "first page text")

    result = ocr_env.run()

    assert result.text == "first page text"
    assert result.requires_vision is False


def test_ocr_page_done_logged(ocr_env, monkeypatch):
    messages = []
    sink_id = logger.add(
        lambda message: messages.append(message.record["message"]),
        level="INFO",
    )
    try:
        ocr_env.configure(page_count=3)
        ocr_env.run()
    finally:
        logger.remove(sink_id)

    assert messages.count("ocr_page_done") == 3


def test_ocr_busy_returns_empty_result(ocr_env, monkeypatch):
    class _BusyAdmission:
        def slot(self):
            raise OcrBusy("all OCR slots busy")

    ocr_env.configure(page_count=1)
    monkeypatch.setattr(tess, "OcrAdmission", lambda *a, **k: _BusyAdmission())

    result = ocr_env.run()

    assert result.text == ""
    assert result.requires_vision is True
    assert result.metadata["ocr_skipped"] == "busy"
    assert ocr_env.pytesseract.calls == []
