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

Every OCR run is bounded by three independent budgets (see the 2026-11-10
OCR concurrency incident):

* input size — page count and raster pixel count,
* time — per-page Tesseract timeout and a whole-document deadline,
* CPU — a global Redis admission lease (``OCR_MAX_CONCURRENT``) that is
  independent of the Celery worker count.
"""

from __future__ import annotations

import hashlib
import io
import os
import time

from core.protocols.extraction_protocol import ExtractionResult
from core.services.ocr_guard import OcrAdmission, OcrBusy
from loguru import logger

# Rasterization DPI.  300 is the usual OCR sweet spot: enough detail for a
# photographed A4 page without producing multi-megapixel PNGs per page.
OCR_DPI = int(os.environ.get("OCR_DPI", "300"))

# Greek is the primary language; English appears in ISO/consulting documents.
OCR_LANG = os.environ.get("OCR_LANG", "ell+eng")

# PSM 3 = fully automatic page segmentation (no orientation detection).
OCR_PSM = os.environ.get("OCR_PSM", "3")

# ── OCR budgets (all overridable at runtime) ───────────────────────────────
# A single document can never OCR more than OCR_MAX_PAGES pages, can never
# run longer than OCR_MAX_SECONDS, and every individual page is killed by
# Tesseract after OCR_PAGE_TIMEOUT seconds.  Large rasters are downscaled to
# OCR_MAX_PIXELS before they reach Tesseract.
OCR_MAX_PAGES = int(os.environ.get("OCR_MAX_PAGES", "20"))
OCR_PAGE_TIMEOUT = float(os.environ.get("OCR_PAGE_TIMEOUT_SECONDS", "60"))
OCR_MAX_SECONDS = float(os.environ.get("OCR_MAX_SECONDS_PER_DOCUMENT", "300"))
OCR_MAX_PIXELS = int(os.environ.get("OCR_MAX_PIXELS", "12000000"))

# Confidence requires a *second* full-page OCR pass (image_to_data), which
# doubles the CPU cost.  Opt-in only.
OCR_COMPUTE_CONFIDENCE = (
    os.environ.get("OCR_COMPUTE_CONFIDENCE", "false").lower()
    in ("true", "1", "t", "yes", "on")
)


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


def _fit_pixels(image, max_pixels: int):
    """Downscale *image* so width*height <= max_pixels (never upscale)."""
    if max_pixels <= 0:
        return image
    width, height = image.size
    pixels = width * height
    if pixels <= max_pixels:
        return image

    scale = (max_pixels / pixels) ** 0.5
    new_size = (max(1, int(width * scale)), max(1, int(height * scale)))

    from PIL import Image

    resample = getattr(Image, "Resampling", Image).LANCZOS
    return image.resize(new_size, resample)


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
        page_confidences: list[float | None] = []
        pages_truncated = False
        started = time.monotonic()
        deadline = started + OCR_MAX_SECONDS

        try:
            try:
                with OcrAdmission().slot():
                    for page_num, page in enumerate(doc, 1):
                        if page_num > OCR_MAX_PAGES:
                            pages_truncated = True
                            logger.bind(
                                page=page_num,
                                max_pages=OCR_MAX_PAGES,
                                file_path=file_path,
                            ).warning("ocr_page_cap_reached")
                            break

                        if time.monotonic() > deadline:
                            pages_truncated = True
                            logger.bind(
                                page=page_num,
                                max_seconds=OCR_MAX_SECONDS,
                                elapsed_s=round(time.monotonic() - started, 2),
                                file_path=file_path,
                            ).warning("ocr_document_deadline_reached")
                            break

                        pix = page.get_pixmap(matrix=matrix, alpha=False)
                        image = Image.open(io.BytesIO(pix.tobytes("png")))
                        image = _fit_pixels(image, OCR_MAX_PIXELS)

                        page_started = time.monotonic()
                        try:
                            page_text = pytesseract.image_to_string(
                                image,
                                lang=OCR_LANG,
                                config=f"--psm {OCR_PSM}",
                                timeout=OCR_PAGE_TIMEOUT,
                            )
                        except RuntimeError as exc:
                            # pytesseract raises RuntimeError on timeout and
                            # also when the subprocess cannot be started.  Skip
                            # the page rather than losing the whole document.
                            logger.bind(
                                page=page_num,
                                timeout_s=OCR_PAGE_TIMEOUT,
                                file_path=file_path,
                                error=str(exc)[:200],
                            ).warning("ocr_page_timeout")
                            continue

                        pages_text.append(page_text)

                        confidence = None
                        if OCR_COMPUTE_CONFIDENCE:
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
                        logger.bind(
                            page=page_num,
                            chars=len(page_text),
                            elapsed_s=round(
                                time.monotonic() - page_started, 3
                            ),
                            file_path=file_path,
                        ).info("ocr_page_done")
            except OcrBusy:
                logger.bind(
                    file_path=file_path,
                    max_concurrent=os.environ.get("OCR_MAX_CONCURRENT", "2"),
                ).warning("ocr_admission_busy")
                return self._empty_result("busy", file_path, started)
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

        ocr_seconds = round(time.monotonic() - started, 3)
        metadata = {
            "provider": "TESSERACT",
            "dpi": OCR_DPI,
            "lang": OCR_LANG,
            "psm": OCR_PSM,
            "page_confidences": page_confidences,
            "pages_ocrd": len(pages_text),
            "pages_truncated": pages_truncated,
            "max_pages": OCR_MAX_PAGES,
            "max_seconds": OCR_MAX_SECONDS,
            "ocr_seconds": ocr_seconds,
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
    def _empty_result(reason: str, file_path: str, started: float) -> ExtractionResult:
        """Return an explicit "no OCR happened" result (keeps native text)."""
        return ExtractionResult(
            text="",
            page_count=0,
            is_scanned=True,
            pages_data=[],
            metadata={
                "provider": "TESSERACT",
                "ocr_skipped": reason,
                "ocr_seconds": round(time.monotonic() - started, 3),
                "file_size_bytes": os.path.getsize(file_path),
            },
            requires_vision=True,
            ocr_applied=False,
            confidence=None,
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
