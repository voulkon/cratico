"""
Tesseract OCR extractor test for the photographed final-boss decision.

Skipped unless the OCR runtime is present: ``pytesseract`` installed AND the
``ell`` language data available.  The extraction must produce text and expose
the real counterpart AFM ``899972873`` to the AFM text process.
"""

from pathlib import Path

import pytest

from core.services.extractors.tesseract import TesseractExtractor
from core.services.text_processes.afm import AfmProcess

PDF = (
    Path(__file__).parent.parent
    / "data"
    / "pdfs"
    / "6ΧΩΜ469ΗΣΥ-ΒΗ4.pdf"
)


def _skip_unless_ocr_ready():
    pytesseract = pytest.importorskip(
        "pytesseract", reason="pytesseract is not installed"
    )
    try:
        languages = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # tesseract binary missing/unusable
        pytest.skip(f"tesseract binary unavailable: {exc}")
    if "ell" not in languages:
        pytest.skip("tesseract Greek language data (ell) is not installed")


@pytest.mark.django_db
def test_extracts_final_boss_pdf():
    _skip_unless_ocr_ready()

    assert PDF.exists(), f"missing fixture PDF: {PDF}"
    result = TesseractExtractor().extract_text(str(PDF))

    assert result.ocr_applied is True
    assert result.requires_vision is False
    assert result.text.strip()
    assert result.page_count >= 1
    assert result.confidence is not None
    assert (result.metadata or {}).get("provider") == "TESSERACT"

    spans = AfmProcess().detect(result.text).spans
    detected = {s.value["afm"] for s in spans}
    assert "899972873" in detected
