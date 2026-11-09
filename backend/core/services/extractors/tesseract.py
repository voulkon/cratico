"""
Tesseract OCR extractor (Greek + English).

Used as the fallback when native PDF extraction yields no/too little text or
the document is image-only (a photograph of a signed decision).  It
deliberately avoids Docling/torch/CUDA: pages are rasterized with PyMuPDF and
read with the system ``tesseract`` binary through ``pytesseract``.

Failure policy: a missing binary, missing language data or an unreadable page
is reported as ``requires_vision=True`` (no usable text) rather than crashing
the worker.  A hard configuration error (tesseract/pytesseract not installed)
raises a clear ``RuntimeError`` so the deployment problem is visible.
"""

from __future__ import annotations

import hashlib
import io
import os

from core.protocols.extraction_protocol import ExtractionResult
from loguru import logger

# Rasterization DPI.  300 is the usual OCR sweet spot: enough detail for a
# photographed A4 page without producing multi-megapixel PNGs per page.
OCR_DPI = int(os.environ.get("OCR_DPI", "300"))

# Greek is the primary language; English appears in ISO/consulting documents.
OCR_LANG = os.environ.get("OCR_LANG", "ell+eng")

# PSM 3 = fully automatic page segmentation (no orientation detection).
OCR_PSM = os.environ.get("OCR_PSM", "3")


def _require_tesseract():
    try:
        import pytesseract
        from PIL import Image  # noqa: F401
    except ImportError as exc:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "pytesseract/Pillow are not installed. Install the OCR "
            "dependencies (pytesseract, Pillow) and the tesseract binary."
        ) from exc

    try:
        available = set(pytesseract.get_languages(config=""))
    except Exception as exc:  # pragma: no cover - deployment guard
        raise RuntimeError(
            "Tesseract binary is not available or cannot be executed. "
            "Install tesseract-ocr in the worker image."
        ) from exc

    wanted = {lang.strip() for lang in OCR_LANG.split("+") if lang.strip()}
    missing = wanted - available
    if missing:  # pragma: no cover - deployment guard
        raise RuntimeError(
            f"Tesseract language data missing: {sorted(missing)}. "
            f"Available: {sorted(available)}"
        )

    return pytesseract


class TesseractExtractor:
    """OCR extractor backed by PyMuPDF rasterization + Tesseract."""

    def extract_text(self, file_path: str) -> ExtractionResult:
        pytesseract = _require_tesseract()

        try:
            import pymupdf  # PyMuPDF
        except ImportError as exc:
            raise RuntimeError(
                "PyMuPDF is required for OCR rasterization."
            ) from exc

        try:
            from PIL import Image
        except ImportError as exc:  # pragma: no cover - guarded above
            raise RuntimeError("Pillow is required for OCR.") from exc

        doc = pymupdf.open(file_path)
        zoom = OCR_DPI / 72.0
        matrix = pymupdf.Matrix(zoom, zoom)

        pages_text: list[str] = []
        pages_data: list[dict] = []
        page_confidences: list[float] = []

        try:
            for page_num, page in enumerate(doc, 1):
                pix = page.get_pixmap(matrix=matrix, alpha=False)
                image = Image.open(io.BytesIO(pix.tobytes("png")))

                page_text = pytesseract.image_to_string(
                    image, lang=OCR_LANG, config=f"--psm {OCR_PSM}"
                )
                pages_text.append(page_text)

                confidence = self._page_confidence(pytesseract, image)
                page_confidences.append(confidence)

                pages_data.append(
                    {
                        "page_number": page_num,
                        "text": page_text,
                        "character_count": len(page_text),
                        "ocr_confidence": confidence,
                    }
                )
        finally:
            doc.close()

        text = "\n".join(pages_text)
        usable = bool(text.strip())
        # Character-weighted confidence: longer pages contribute more.
        weighted = [
            (len(t), c)
            for t, c in zip(pages_text, page_confidences)
            if c is not None and len(t) > 0
        ]
        total_chars = sum(length for length, _ in weighted)
        confidence = (
            round(
                sum(length * conf for length, conf in weighted) / total_chars, 4
            )
            if total_chars
            else None
        )

        metadata = {
            "provider": "TESSERACT",
            "dpi": OCR_DPI,
            "lang": OCR_LANG,
            "psm": OCR_PSM,
            "page_confidences": page_confidences,
            "text_hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "file_size_bytes": os.path.getsize(file_path),
        }

        if not usable:
            logger.warning(f"Tesseract produced no usable text for {file_path}")

        return ExtractionResult(
            text=text,
            page_count=len(pages_text),
            is_scanned=True,
            pages_data=pages_data,
            metadata=metadata,
            requires_vision=not usable,
            ocr_applied=usable,
            confidence=confidence,
        )

    @staticmethod
    def _page_confidence(pytesseract, image) -> float | None:
        """Weighted mean word confidence for one page (0–1), or None."""
        try:
            data = pytesseract.image_to_data(
                image, lang=OCR_LANG, config=f"--psm {OCR_PSM}",
                output_type=pytesseract.Output.DICT,
            )
        except Exception as exc:
            logger.debug(f"Tesseract image_to_data failed: {exc}")
            return None

        confidences = []
        weights = []
        for conf, word in zip(data.get("conf", []), data.get("text", [])):
            try:
                value = float(conf)
            except (TypeError, ValueError):
                continue
            if value < 0 or not (word or "").strip():
                continue
            confidences.append(value)
            weights.append(len(word))

        if not confidences:
            return None
        total = sum(weights) or len(weights)
        return round(
            sum(c * w for c, w in zip(confidences, weights)) / total / 100.0, 4
        )
