"""
OCR fallback + extraction-status semantics.

Covers the parts of the OCR work that are easy to regress:

* native empty/short text → Tesseract result wins (flagged on)
* OCR called only when the feature flag is on
* a failing OCR runtime degrades to NEEDS_VISION instead of crashing
* ``force=True`` re-runs a COMPLETED extraction
* importer status: requires_vision vs scanned-with-text vs corrupted-OCR
* replacing text clears stale TextProcessRun / TextProcessResolution rows
"""

import os
import tempfile
from types import SimpleNamespace

import pytest
from conftest import DecisionFactory
from core.importers.document_extraction import DocumentExtractionImporter
from core.models.document_analysis import (
    DocumentExtraction,
    ProcessingProvider,
    ProcessingStatus,
    TextProcessResolution,
    TextProcessRun,
)
from core.protocols.extraction_protocol import ExtractionResult
from core.services.document_processor import TextExtractionProcessor
from core.services.feature_flag_service import feature_flags
from core.services.ocr_guard import OcrBusy
from loguru import logger

pytestmark = pytest.mark.django_db


class _StubExtractor:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def extract_text(self, file_path):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _ocr_result(text="ΑΦΜ 899972873 — ανάδοχος συμβουλευτικών υπηρεσιών ISO."):
    return ExtractionResult(
        text=text,
        page_count=1,
        is_scanned=True,
        pages_data=[{"page_number": 1, "text": text, "character_count": len(text)}],
        metadata={"provider": "TESSERACT", "dpi": 300, "lang": "ell+eng"},
        ocr_applied=True,
        confidence=0.91,
    )


def _native_result(text=""):
    return ExtractionResult(
        text=text,
        page_count=1,
        is_scanned=False,
        pages_data=[{"page_number": 1, "text": text, "character_count": len(text)}],
        metadata={"provider": "PYMUPDF"},
    )


def _make_processor(
    monkeypatch, *, native, ocr=None, ocr_error=None, ocr_enabled=True
):
    monkeypatch.setattr(
        feature_flags,
        "is_enabled",
        lambda key, default=None: (
            ocr_enabled if key == "DOCUMENT_OCR_ENABLED" else False
        ),
    )

    processor = TextExtractionProcessor()
    native_extractor = _StubExtractor(result=native)
    ocr_extractor = _StubExtractor(result=ocr, error=ocr_error)
    processor.extractors = {
        ProcessingProvider.PYMUPDF: native_extractor,
        ProcessingProvider.TESSERACT: ocr_extractor,
    }
    processor.default_extractor = ProcessingProvider.PYMUPDF

    def fake_download(url):
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        return path, True

    processor.download_pdf = fake_download
    # Keep the test focused on extraction; post-OCR processes/indexing have
    # their own coverage.
    processor._refresh_after_ocr = lambda *a, **k: None
    return processor, native_extractor, ocr_extractor


def _decision():
    return DecisionFactory(ada="OCR-TEST")


class TestOcrFallback:
    def test_empty_native_text_uses_ocr(self, monkeypatch):
        decision = _decision()
        processor, _, ocr_extractor = _make_processor(
            monkeypatch, native=_native_result(""), ocr=_ocr_result()
        )

        assert processor.process_document(decision) is True
        assert ocr_extractor.calls == 1

        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.extraction_provider == ProcessingProvider.TESSERACT.value
        assert extraction.extraction_status == ProcessingStatus.COMPLETED
        assert extraction.ocr_applied is True
        assert extraction.ocr_confidence == pytest.approx(0.91)
        assert extraction.ocr_metadata["lang"] == "ell+eng"
        assert extraction.is_scanned_document is True
        assert "899972873" in extraction.raw_text
        assert extraction.preprocessing_metadata["native_extraction"][
            "provider"
        ] == ProcessingProvider.PYMUPDF.value

    def test_corrupted_header_only_text_triggers_ocr(self, monkeypatch):
        """A photographed page can yield ~200 chars of signature header.

        That passes the length threshold but is flagged corrupted; OCR must
        still run (regression: the final-boss PDF produced 196 header chars).
        """
        decision = _decision()
        native_text = (
            "ΟΙΚ-ΙΦΕΤ ΜΑΕ - Αρ.Πρωτ.7511-05/11/2026 : 6ΧΩΜ469ΗΣΥ-ΒΗ4 "
            "Ministry of Digital Governance Digitally signed by Ministry "
            "of Digital Governance Date: 2026.11.05 12:24:51 EET Reason: "
            "Location: Athens"
        )
        assert len(native_text) > 100

        processor, _, ocr_extractor = _make_processor(
            monkeypatch,
            native=_native_result(native_text),
            ocr=_ocr_result(
                text="ΑΦΜ 899972873 " + ("πραγματικό κείμενο εγγράφου " * 30)
            ),
        )
        preprocessing_calls = []

        def fake_preprocess(text):
            preprocessing_calls.append(text)
            return SimpleNamespace(
                processed_text=text,
                is_corrupted=(text == native_text),
                corruption_indicators={},
                confidence_score=0.77,
                performance_stats={},
            )

        processor.text_preprocessor.preprocess = fake_preprocess

        assert processor.process_document(decision) is True
        assert ocr_extractor.calls == 1
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.extraction_status == ProcessingStatus.COMPLETED
        assert extraction.ocr_applied is True
        # Native quality check + OCR text preprocessing (not twice on native).
        assert len(preprocessing_calls) == 2

    def test_corrupted_text_without_flag_stays_corrupted(self, monkeypatch):
        decision = _decision()
        native_text = "ΟΙΚ-ΙΦΕΤ ΜΑΕ - Αρ.Πρωτ.7511-05/11/2026 : 6ΧΩΜ469ΗΣΥ-ΒΗ4 " * 2
        processor, _, ocr_extractor = _make_processor(
            monkeypatch,
            native=_native_result(native_text),
            ocr=_ocr_result(),
            ocr_enabled=False,
        )
        processor.text_preprocessor.preprocess = lambda text: SimpleNamespace(
            processed_text=text,
            is_corrupted=True,
            corruption_indicators={},
            confidence_score=0.7,
            performance_stats={},
        )

        processor.process_document(decision)
        assert ocr_extractor.calls == 0
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.extraction_status == ProcessingStatus.CORRUPTED_CONTENT
        assert extraction.ocr_applied is False

    def test_flag_off_never_calls_ocr(self, monkeypatch):
        decision = _decision()
        processor, _, ocr_extractor = _make_processor(
            monkeypatch,
            native=_native_result(""),
            ocr=_ocr_result(),
            ocr_enabled=False,
        )

        processor.process_document(decision)
        assert ocr_extractor.calls == 0
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.ocr_applied is False

    def test_missing_ocr_runtime_degrades_to_needs_vision(self, monkeypatch):
        decision = _decision()
        processor, _, _ = _make_processor(
            monkeypatch,
            native=_native_result(""),
            ocr_error=RuntimeError("tesseract binary missing"),
        )

        assert processor.process_document(decision) is True
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.extraction_status == ProcessingStatus.NEEDS_VISION
        assert extraction.is_scanned_document is True

    def test_force_reextracts_completed_document(self, monkeypatch):
        decision = _decision()
        DocumentExtraction.objects.create(
            decision=decision,
            extraction_status=ProcessingStatus.COMPLETED,
            raw_text="old text",
            page_count=1,
        )
        new_text = "A" * 250
        processor, native_extractor, _ = _make_processor(
            monkeypatch, native=_native_result(new_text), ocr_enabled=False
        )

        processor.process_document(decision, force=True, allow_ocr=False)

        assert native_extractor.calls == 1
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.raw_text == new_text
        assert extraction.extraction_status == ProcessingStatus.COMPLETED


class TestOcrBudgets:
    def test_large_native_text_skips_ocr(self, monkeypatch):
        decision = _decision()
        long_text = "ΑΦΜ 899972873 " + ("Α" * 60_000)
        processor, _, ocr_extractor = _make_processor(
            monkeypatch,
            native=_native_result(long_text),
            ocr=_ocr_result("x" * 100_000),
        )
        processor.text_preprocessor.preprocess = lambda text: SimpleNamespace(
            processed_text=text,
            is_corrupted=True,
            corruption_indicators={},
            confidence_score=0.7,
            performance_stats={},
        )

        assert processor.process_document(decision) is True

        assert ocr_extractor.calls == 0
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.raw_text == long_text
        assert extraction.preprocessing_metadata["ocr_skipped"] == "native_too_large"
        assert (
            extraction.preprocessing_metadata["ocr_fallback"]["reason"]
            == "native_too_large"
        )
        assert (
            extraction.preprocessing_metadata["ocr_decision"]["native_chars"]
            == len(long_text)
        )

    def test_ocr_busy_keeps_native_text(self, monkeypatch):
        decision = _decision()
        processor, _, ocr_extractor = _make_processor(
            monkeypatch,
            native=_native_result(""),
            ocr_error=OcrBusy("all OCR slots busy"),
        )

        assert processor.process_document(decision) is True

        assert ocr_extractor.calls == 1
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.extraction_status == ProcessingStatus.NEEDS_VISION
        assert extraction.preprocessing_metadata["ocr_skipped"] == "busy"
        assert extraction.preprocessing_metadata["ocr_fallback"]["reason"] == "busy"

    def test_extractor_busy_metadata_kept(self, monkeypatch):
        """The extractor swallows OcrBusy and returns an explicit skip result."""
        decision = _decision()
        busy = ExtractionResult(
            text="",
            page_count=0,
            is_scanned=True,
            metadata={"provider": "TESSERACT", "ocr_skipped": "busy"},
            requires_vision=True,
            ocr_applied=False,
        )
        processor, _, ocr_extractor = _make_processor(
            monkeypatch, native=_native_result(""), ocr=busy
        )

        assert processor.process_document(decision) is True

        assert ocr_extractor.calls == 1
        extraction = DocumentExtraction.objects.get(decision=decision)
        assert extraction.preprocessing_metadata["ocr_skipped"] == "busy"
        assert extraction.preprocessing_metadata["ocr_fallback"]["reason"] == "busy"

    def test_ocr_decision_logged(self, monkeypatch):
        decision = _decision()
        processor, _, _ = _make_processor(
            monkeypatch, native=_native_result(""), ocr=_ocr_result()
        )
        messages = []
        sink_id = logger.add(
            lambda message: messages.append(message.record["message"]),
            level="INFO",
        )
        try:
            processor.process_document(decision)
        finally:
            logger.remove(sink_id)

        assert "ocr_decision" in messages


class TestImportStatusSemantics:
    def _import(self, decision, result, **kwargs):
        extraction = DocumentExtraction.objects.create(
            decision=decision,
            extraction_status=ProcessingStatus.PENDING,
            raw_text=kwargs.pop("previous_text", None),
        )
        return DocumentExtractionImporter().import_extraction_result(
            decision=decision,
            result=result,
            provider_name="TESSERACT",
            processing_time_ms=10,
            extraction=extraction,
            **kwargs,
        )

    def test_requires_vision(self):
        decision = _decision()
        result = ExtractionResult(
            text="", page_count=1, is_scanned=True, requires_vision=True
        )
        extraction = self._import(decision, result)
        assert extraction.extraction_status == ProcessingStatus.NEEDS_VISION
        assert extraction.is_scanned_document is True

    def test_scanned_with_text_is_completed(self):
        decision = _decision()
        result = ExtractionResult(
            text="ΑΦΜ 899972873 " + "x" * 120,
            page_count=1,
            is_scanned=True,
            ocr_applied=True,
            confidence=0.8,
        )
        extraction = self._import(decision, result)
        assert extraction.extraction_status == ProcessingStatus.COMPLETED
        assert extraction.is_scanned_document is True
        assert extraction.ocr_applied is True

    def test_corrupted_ocr_text_is_kept(self):
        decision = _decision()
        result = ExtractionResult(
            text="ΑΦΜ 899972873 " + "x" * 120,
            page_count=1,
            is_scanned=True,
            ocr_applied=True,
            confidence=0.7,
        )
        preprocessing = SimpleNamespace(
            corruption_indicators={"strategy_used": "ocr_artifacts"},
            confidence_score=0.4,
            performance_stats={},
        )
        extraction = self._import(
            decision, result, is_corrupted=True, preprocessing_result=preprocessing
        )
        assert extraction.extraction_status == ProcessingStatus.COMPLETED
        assert extraction.preprocessing_metadata["confidence_score"] == 0.4

    def test_changed_text_clears_stale_offsets(self):
        decision = _decision()
        old_text = "old text with ΑΦΜ 167375970"
        extraction, _ = DocumentExtraction.objects.get_or_create(
            decision=decision,
            defaults={"extraction_status": ProcessingStatus.COMPLETED},
        )
        extraction.raw_text = old_text
        extraction.extraction_status = ProcessingStatus.COMPLETED
        extraction.save()

        run = TextProcessRun.objects.create(
            extraction=extraction, process="afm", method="regex", provider="REGEX"
        )
        TextProcessResolution.objects.create(decision=decision, process="afm")

        result = ExtractionResult(text="new text without the old AFM", page_count=1)
        DocumentExtractionImporter().import_extraction_result(
            decision=decision,
            result=result,
            provider_name="PYMUPDF",
            processing_time_ms=5,
            extraction=extraction,
        )

        assert not TextProcessRun.objects.filter(pk=run.pk).exists()
        assert not TextProcessResolution.objects.filter(decision=decision).exists()
