import os
import tempfile
import time
from typing import Any, Dict, Optional, Tuple

import requests
import stamina
from core.importers.document_extraction import DocumentExtractionImporter
from core.models.decisions import Decision
from core.models.document_analysis import (
    DocumentExtraction,
    ProcessingProvider,
    ProcessingStatus,
)

# from core.services.extractors.pypdf import PyPdfExtractor
from core.protocols.extraction_protocol import ExtractionResult
from core.services.extractors.docling import DoclingExtractor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from core.services.extractors.tesseract import TesseractExtractor
from core.services.ocr_guard import OcrBusy
from core.services.text_preprocessor import TextPreprocessor
from loguru import logger
from requests.exceptions import ConnectionError, RequestException, Timeout


class BaseDocumentProcessor:
    """Base class for document processing operations"""

    @staticmethod
    def should_retry_request(exc: Exception) -> bool:
        """
        Predicate function to determine if we should retry a request
        """
        # Always retry on connection errors and timeouts
        if isinstance(exc, (ConnectionError, Timeout)):
            return True

        # For HTTP errors, only retry on 5xx server errors or 429 (rate limiting)
        if isinstance(exc, requests.HTTPError):
            if hasattr(exc, "response") and exc.response is not None:
                status_code = exc.response.status_code
                # Retry on server errors (5xx) or rate limiting (429)
                return status_code >= 500 or status_code == 429

        # Retry on general request exceptions (network issues)
        return isinstance(exc, RequestException)

    @stamina.retry(
        on=should_retry_request,  # Use our custom predicate
        attempts=4,  # Try up to 4 times (1 original + 3 retries)
        wait_initial=1.0,  # Start with 1 second wait
        wait_max=30.0,  # Maximum wait of 30 seconds
        wait_jitter=0.1,  # Add some randomness to prevent thundering herd
    )
    def download_pdf(self, document_url: str) -> Tuple[str, bool]:
        """
        Downloads PDF from URL and returns path to temporary file
        """
        try:
            logger.debug(f"[NET] Requesting PDF from: {document_url}")

            # Add headers to look more like a regular browser
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
            }

            response = requests.get(
                document_url, timeout=60, headers=headers  # Increased timeout
            )
            response.raise_for_status()

            content_length = len(response.content)
            logger.debug(f"[PKG] Downloaded {content_length} bytes")

            # Validate that we actually got a PDF
            if not response.content.startswith(b"%PDF"):
                logger.warning(
                    f"[WARN]️ Downloaded content doesn't appear to be a PDF: {document_url}"
                )
                # Don't raise an exception here, let the PDF parser handle it

            # Create temp file
            fd, temp_path = tempfile.mkstemp(suffix=".pdf")
            with os.fdopen(fd, "wb") as f:
                f.write(response.content)

            logger.debug(f"[SAVE] Saved to temporary file: {temp_path}")
            return temp_path, True

        except Exception as e:
            logger.error(
                f"[DENIED] Failed to download PDF from {document_url}: {str(e)}"
            )
            # Re-raise the exception so stamina can handle retries
            raise

    def cleanup_temp_file(self, temp_path: str) -> None:
        """Removes the temporary file"""
        try:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)
        except Exception as e:
            logger.error(f"Failed to delete temp file {temp_path}: {str(e)}")


# OCR fallback thresholds.  A COMPLETED extraction shorter than either bound is
# treated as "not really extracted" and re-run through Tesseract.
OCR_MIN_CHARS = int(os.environ.get("OCR_MIN_CHARS", "100"))
OCR_MIN_CHARS_PER_PAGE = int(os.environ.get("OCR_MIN_CHARS_PER_PAGE", "100"))

# Above this much native text, a full-document OCR pass is uneconomical and
# can never improve the result enough to justify the CPU cost.
OCR_MAX_NATIVE_CHARS = int(os.environ.get("OCR_MAX_NATIVE_CHARS", "50000"))


class TextExtractionProcessor(BaseDocumentProcessor):
    """Handles text extraction from PDFs using various providers"""

    # Define extractors as class variables (shared across all instances)
    # NOTE: PyMuPDF is lightweight and fast (0.5s), Docling is heavy but more accurate (12s+ init)
    # Use DOCUMENT_EXTRACTOR env var to override: PYMUPDF (default) or DOCLING
    extractors = {
        ProcessingProvider.PYMUPDF: PyMuPDFExtractor(),
        # Tesseract imports its binary lazily inside extract_text(), so an
        # image without the OCR runtime installed still constructs here.
        ProcessingProvider.TESSERACT: TesseractExtractor(),
        # Docling loaded lazily only when needed (see _get_docling_extractor)
        # ProcessingProvider.PLAINTEXT: PlainTextExtractor(),
    }
    default_extractor = ProcessingProvider.PYMUPDF  # Fast, lightweight default
    # default_extractor = ProcessingProvider.DOCLING  # Heavy, accurate alternative

    # Track instance creation for performance monitoring
    _instance_count = 0

    def __init__(self):
        super().__init__()
        self.text_preprocessor = TextPreprocessor()
        TextExtractionProcessor._instance_count += 1
        logger.debug(
            f"TextExtractionProcessor instance #{TextExtractionProcessor._instance_count} created "
            f"(PID: {os.getpid()})"
        )

        # Check LIGHT_WORKER mode first (takes precedence)
        from core.services.feature_flag_service import feature_flags

        if feature_flags.is_enabled("LIGHT_WORKER"):
            # Light mode: force PyMuPDF
            self.default_extractor = ProcessingProvider.PYMUPDF
            logger.debug(
                "LIGHT_WORKER mode: Using PyMuPDF extractor (Docling disabled)"
            )
        else:
            # Full mode: check DOCUMENT_EXTRACTOR env var for override
            env_extractor = os.getenv("DOCUMENT_EXTRACTOR", "").upper()
            if env_extractor == "DOCLING":
                self.default_extractor = ProcessingProvider.DOCLING
                logger.debug(
                    "FULL_WORKER mode: Using DOCLING extractor (from DOCUMENT_EXTRACTOR env var)"
                )
            elif env_extractor == "PYMUPDF":
                self.default_extractor = ProcessingProvider.PYMUPDF
                logger.debug(
                    "FULL_WORKER mode: Using PyMuPDF extractor (from DOCUMENT_EXTRACTOR env var)"
                )
            elif env_extractor:
                logger.warning(
                    f"[WARN]️  Unknown DOCUMENT_EXTRACTOR value: {env_extractor}, using default (PyMuPDF)"
                )
            else:
                # Default in full mode is still PyMuPDF unless explicitly set
                logger.debug("FULL_WORKER mode: Using PyMuPDF extractor (default)")

    @staticmethod
    def _refresh_after_ocr(decision: Decision, extraction) -> None:
        """
        Re-run offset-bearing text processes and refresh OpenSearch.

        Best-effort: a failure here must not turn a successful OCR extraction
        into a failed document.
        """
        try:
            from core.services.text_process_service import TextProcessService

            service = TextProcessService()
            for slug in ("afm", "amount"):
                try:
                    service.run_process(extraction, slug, force=True)
                except Exception as exc:
                    logger.warning(
                        f"Post-OCR text process {slug!r} failed for "
                        f"{decision.ada}: {exc}"
                    )
        except Exception as exc:
            logger.warning(
                f"Post-OCR text process refresh failed for {decision.ada}: {exc}"
            )

        try:
            from core.services.opensearch_service import OpenSearchService

            OpenSearchService().index_document(
                {
                    "decision_id": decision.id,
                    "ada": decision.ada,
                    "title": decision.subject or "",
                    "content": extraction.raw_text or "",
                    "organization": (
                        str(decision.organization) if decision.organization else ""
                    ),
                    "decision_type": (
                        str(decision.decision_type) if decision.decision_type else ""
                    ),
                    "issue_date": (
                        decision.issue_date.isoformat()
                        if decision.issue_date
                        else None
                    ),
                    "extraction_date": (
                        extraction.extraction_date.isoformat()
                        if extraction.extraction_date
                        else None
                    ),
                    "character_count": extraction.character_count,
                    "page_count": extraction.page_count,
                }
            )
        except Exception as exc:
            logger.warning(
                f"Post-OCR OpenSearch re-index failed for {decision.ada}: {exc}"
            )

    @staticmethod
    def _text_too_short(text: str | None, page_count: int | None) -> bool:
        """
        Whether extracted text is too short to be useful.

        Empty text always qualifies.  Otherwise require at least
        ``OCR_MIN_CHARS`` overall and ``OCR_MIN_CHARS_PER_PAGE`` per page, so a
        single stray line from a photographed page triggers the OCR fallback.
        """
        chars = len((text or "").strip())
        if chars == 0:
            return True
        pages = max(1, int(page_count or 1))
        return chars < OCR_MIN_CHARS or chars < OCR_MIN_CHARS_PER_PAGE * pages

    def _get_docling_extractor(self):
        """Lazy-load Docling extractor only when needed to avoid heavy initialization"""
        if ProcessingProvider.DOCLING not in self.extractors:
            try:
                logger.info("Lazy-loading Docling extractor (first use)...")
                self.extractors[ProcessingProvider.DOCLING] = DoclingExtractor()
                logger.success("Docling extractor loaded successfully")
            except ImportError as e:
                logger.error(f"Docling not available: {e}")
                logger.error(
                    "Install worker dependencies: poetry install --with worker"
                )
                raise RuntimeError(
                    "Docling not installed. Use PyMuPDF or install worker group."
                ) from e
        return self.extractors[ProcessingProvider.DOCLING]

    def process_document(
        self,
        decision: Decision,
        provider: str = None,
        force: bool = False,
        allow_ocr: bool = True,
    ) -> bool:
        """
        Main entry point for text extraction

        Args:
            decision: The decision to process
            provider: Optional provider name to use (defaults to PYPDF)
            force: Re-run even when a COMPLETED extraction already exists.
            allow_ocr: Allow the Tesseract fallback when native text is
                empty/too short (still gated by DOCUMENT_OCR_ENABLED).

        Returns:
            bool: Success status
        """

        if not decision.document_url_or_fallback:
            logger.warning(f"Decision {decision.ada} has no document URL and no ADA")
            return False

        # Log which file we're starting to process
        logger.debug(f"Starting processing for decision {decision.ada}")
        logger.debug(f"Document URL: {decision.document_url_or_fallback}")

        # Use the specified provider or default
        provider = provider or self.default_extractor

        provider_name: str = (
            provider.value
            if isinstance(provider, ProcessingProvider)
            else str(provider)
        )

        logger.debug(f"Using extraction provider: {provider_name}")

        # Lazy-load Docling if needed
        if provider == ProcessingProvider.DOCLING:
            try:
                extractor = self._get_docling_extractor()
            except RuntimeError:
                logger.warning("Falling back to PyMuPDF extractor")
                provider = ProcessingProvider.PYMUPDF
                extractor = self.extractors[ProcessingProvider.PYMUPDF]
        elif provider not in self.extractors:
            logger.error(f"Unknown extraction provider: {provider}")
            return False
        else:
            extractor = self.extractors[provider]

        # Check if we already have an extraction
        extraction, created = DocumentExtraction.objects.get_or_create(
            decision=decision, defaults={"extraction_status": ProcessingStatus.PENDING}
        )

        # A COMPLETED row with no/too-short text is a real state in this
        # codebase (extractor succeeded but produced nothing usable).  Treat it
        # as "not extracted" so the OCR fallback gets a chance, otherwise the
        # document can never recover.
        completed_but_useless = (
            extraction.extraction_status == ProcessingStatus.COMPLETED
            and not force
            and self._text_too_short(extraction.raw_text, extraction.page_count)
        )
        if completed_but_useless:
            logger.warning(
                f"Document {decision.ada} is COMPLETED but has no usable text "
                f"({len(extraction.raw_text or '')} chars) — re-processing"
            )

        # If not pending, we've already processed or are processing it
        if (
            not force
            and not completed_but_useless
            and not created
            and extraction.extraction_status != ProcessingStatus.PENDING
        ):
            if extraction.extraction_status == ProcessingStatus.COMPLETED:
                logger.info(f"Document {decision.ada} already extracted")
                return True
            elif extraction.extraction_status == ProcessingStatus.CORRUPTED_CONTENT:
                logger.info(f"Document {decision.ada} already marked as corrupted.")
                return True
            elif extraction.extraction_status == ProcessingStatus.PROCESSING:
                # A row can get stuck in PROCESSING forever if the worker
                # died mid-extraction (there is no reaper).  Treat rows that
                # haven't been touched for a while as stale and re-process.
                from datetime import timedelta

                from django.utils import timezone as dj_timezone

                stale_after = dj_timezone.now() - timedelta(minutes=30)
                if (
                    extraction.updated_at
                    and extraction.updated_at < stale_after
                ):
                    logger.warning(
                        f"Document {decision.ada} stuck in PROCESSING since "
                        f"{extraction.updated_at} — resetting and re-processing."
                    )
                    # fall through to re-processing below
                else:
                    logger.info(
                        f"Document {decision.ada} is currently being processed"
                    )
                    return False

        # Update status to processing
        extraction.extraction_status = ProcessingStatus.PROCESSING
        extraction.save(update_fields=["extraction_status"])

        # Initialize the importer
        importer = DocumentExtractionImporter()

        # Download the PDF
        logger.debug(f"Downloading PDF for {decision.ada}")
        temp_path, success = self.download_pdf(decision.document_url_or_fallback)
        if not success:
            logger.error(f"Failed to download PDF for {decision.ada}")
            importer.mark_extraction_failed(extraction, "Failed to download PDF")
            return False

        logger.debug(f"Downloaded PDF to {temp_path}")

        try:
            # Start timing the extraction
            start_time = time.time()
            logger.debug(f"Starting text extraction for {decision.ada}")

            # Extract text using the selected provider (extractor already fetched above)
            result: ExtractionResult = extractor.extract_text(temp_path)
            native_char_count = len(result.text or "")
            native_provider_name = provider_name
            extraction_metadata = dict(result.metadata or {})
            extraction_metadata["native_extraction"] = {
                "provider": provider_name,
                "char_count": native_char_count,
                "page_count": result.page_count,
            }
            ocr_applied = bool(result.ocr_applied)
            ocr_confidence = result.confidence
            requires_vision = bool(result.requires_vision)

            # Cheap native quality check BEFORE deciding on OCR.  A
            # photographed page often yields only the signature header
            # (~200 chars), which passes the length threshold but is flagged
            # as corrupted by the preprocessor.  That flag is the reliable
            # signal that the body was never extracted.
            native_preprocessing = None
            native_is_corrupted = False
            if (
                (result.text or "").strip()
                and not result.ocr_applied
                and provider != ProcessingProvider.TESSERACT
            ):
                native_preprocessing = self.text_preprocessor.preprocess(
                    result.text
                )
                native_is_corrupted = bool(
                    native_preprocessing.is_corrupted
                )

            # ── OCR fallback ───────────────────────────────────────────
            # Some Diavgeia documents are photographs: native extraction
            # succeeds but returns nothing useful.  When OCR is enabled, retry
            # the same temp PDF with Tesseract and keep whichever text is
            # longer.  Missing tesseract/Greek data must never crash the
            # worker — it degrades to NEEDS_VISION.
            text_too_short = self._text_too_short(result.text, result.page_count)
            native_cap_exceeded = native_char_count > OCR_MAX_NATIVE_CHARS
            ocr_requested = (
                allow_ocr
                and provider != ProcessingProvider.TESSERACT
                and (text_too_short or native_is_corrupted)
            )

            if ocr_requested:
                from core.services.feature_flag_service import feature_flags

                ocr_flag_enabled = feature_flags.is_enabled(
                    "DOCUMENT_OCR_ENABLED"
                )
                ocr_allowed = ocr_flag_enabled and not native_cap_exceeded

                if native_cap_exceeded:
                    skip_reason = "native_too_large"
                elif not ocr_flag_enabled:
                    skip_reason = "feature_flag_disabled"
                else:
                    skip_reason = None

                ocr_decision = {
                    "native_chars": native_char_count,
                    "page_count": result.page_count,
                    "too_short": text_too_short,
                    "corrupted": native_is_corrupted,
                    "native_cap": OCR_MAX_NATIVE_CHARS,
                    "ocr_enabled": ocr_flag_enabled,
                    "decision": "ocr" if ocr_allowed else "skip",
                    "reason": skip_reason,
                }
                extraction_metadata["ocr_decision"] = dict(ocr_decision)
                logger.bind(document_ada=decision.ada, **ocr_decision).info(
                    "ocr_decision"
                )

                if ocr_allowed:
                    try:
                        logger.info(
                            f"Native extraction for {decision.ada} produced "
                            f"{native_char_count} chars — trying Tesseract OCR"
                        )
                        ocr_result: ExtractionResult = self.extractors[
                            ProcessingProvider.TESSERACT
                        ].extract_text(temp_path)
                        if len(ocr_result.text or "") > native_char_count:
                            result = ocr_result
                            provider_name = ProcessingProvider.TESSERACT.value
                            extraction_metadata = dict(ocr_result.metadata or {})
                            extraction_metadata["native_extraction"] = {
                                "provider": native_provider_name,
                                "char_count": native_char_count,
                                "page_count": result.page_count,
                            }
                            extraction_metadata["ocr_decision"] = dict(ocr_decision)
                            extraction_metadata["ocr_fallback"] = {
                                "applied": True,
                                "dpi": (ocr_result.metadata or {}).get("dpi"),
                                "lang": (ocr_result.metadata or {}).get("lang"),
                            }
                            ocr_applied = True
                            ocr_confidence = ocr_result.confidence
                            requires_vision = bool(ocr_result.requires_vision)
                            logger.info(
                                f"OCR fallback for {decision.ada}: "
                                f"{native_char_count} → "
                                f"{len(ocr_result.text or '')} chars "
                                f"(confidence={ocr_confidence})"
                            )
                        else:
                            # Keep the native text; only escalate to vision
                            # when there is nothing usable to keep.
                            if not (result.text or "").strip():
                                requires_vision = True
                            skipped_reason = (ocr_result.metadata or {}).get(
                                "ocr_skipped"
                            )
                            if skipped_reason:
                                extraction_metadata["ocr_skipped"] = skipped_reason
                                extraction_metadata["ocr_fallback"] = {
                                    "applied": False,
                                    "reason": skipped_reason,
                                }
                            else:
                                extraction_metadata["ocr_fallback"] = {
                                    "applied": False,
                                    "reason": "ocr_text_not_longer",
                                    "char_count": len(ocr_result.text or ""),
                                }
                    except OcrBusy:
                        # Global admission control is saturated (or Redis is
                        # unavailable).  Keep the native text; failing open is
                        # what melted the host during the incident.
                        logger.bind(document_ada=decision.ada).warning(
                            "ocr_skipped_busy"
                        )
                        extraction_metadata["ocr_skipped"] = "busy"
                        extraction_metadata["ocr_fallback"] = {
                            "applied": False,
                            "reason": "busy",
                        }
                        requires_vision = requires_vision or not (
                            result.text or ""
                        ).strip()
                    except Exception as exc:
                        logger.error(
                            f"OCR fallback failed for {decision.ada}: {exc}"
                        )
                        extraction_metadata["ocr_fallback"] = {
                            "applied": False,
                            "error": str(exc)[:500],
                        }
                        # No usable text at all → mark for vision rather than
                        # reporting a successful empty extraction.
                        requires_vision = requires_vision or not (
                            result.text or ""
                        ).strip()
                else:
                    logger.info(
                        f"OCR fallback for {decision.ada} skipped ({skip_reason})"
                    )
                    extraction_metadata["ocr_fallback"] = {
                        "applied": False,
                        "reason": skip_reason,
                    }
                    if native_cap_exceeded:
                        extraction_metadata["ocr_skipped"] = "native_too_large"

            raw_extracted_text = result.text
            processed_text = (
                raw_extracted_text  # Default to raw if no processing happens
            )
            is_corrupted = False
            preprocessing_result = None

            if raw_extracted_text and not raw_extracted_text.isspace():
                if ocr_applied:
                    logger.debug(
                        f"Starting text preprocessing for {decision.ada} "
                        f"(OCR text, length: {len(raw_extracted_text)})"
                    )
                    preprocessing_result = self.text_preprocessor.preprocess(
                        raw_extracted_text
                    )
                elif native_preprocessing is not None:
                    # Reuse the quality check already done for the OCR
                    # decision — do not preprocess the same text twice.
                    preprocessing_result = native_preprocessing
                else:
                    logger.debug(
                        f"Starting text preprocessing for {decision.ada} "
                        f"(Original length: {len(raw_extracted_text)})"
                    )
                    preprocessing_result = self.text_preprocessor.preprocess(
                        raw_extracted_text
                    )

                # Unpack the fields from the model
                processed_text = preprocessing_result.processed_text
                is_corrupted = preprocessing_result.is_corrupted

                if is_corrupted:
                    logger.warning(
                        f"Content for {decision.ada} detected as potentially corrupted."
                    )
                    # Log additional corruption details for debugging
                    if preprocessing_result.corruption_indicators:
                        logger.debug(
                            f"Corruption indicators: {preprocessing_result.corruption_indicators}"
                        )
                    if preprocessing_result.confidence_score is not None:
                        logger.debug(
                            f"Corruption detection confidence: {preprocessing_result.confidence_score:.3f}"
                        )

                if processed_text != raw_extracted_text:
                    logger.debug(
                        f"Text preprocessed for {decision.ada}. New length: {len(processed_text)}"
                    )
                else:
                    logger.debug(
                        f"No significant changes made by text preprocessor for {decision.ada}."
                    )

                # Log performance stats if available
                if preprocessing_result.performance_stats:
                    total_time = preprocessing_result.performance_stats.get("total", 0)
                    logger.debug(
                        f"Preprocessing took {total_time*1000:.1f}ms for {decision.ada}"
                    )

            else:
                logger.warning(
                    f"No text extracted or only whitespace from {decision.ada}, skipping preprocessing."
                )

            # Calculate processing time
            processing_time_ms = int((time.time() - start_time) * 1000)

            final_text_to_log_and_save = (
                processed_text
                if processed_text and not processed_text.isspace()
                else ""
            )

            # Per-document details stay at DEBUG so a bulk run does not flood
            # the logs; the structured INFO line below is the single record
            # emitted for each processed document.
            if final_text_to_log_and_save:
                text_length = len(final_text_to_log_and_save)
                # Show first and last 100 characters
                preview_start = final_text_to_log_and_save[:100].strip()
                preview_end = (
                    final_text_to_log_and_save[-100:].strip()
                    if text_length > 100
                    else ""
                )

                logger.debug(
                    f"Extracted {text_length} characters from {decision.ada} in {processing_time_ms}ms"
                )
                logger.debug(f"Content start: '{preview_start}...'")
                if preview_end and preview_end != preview_start:
                    logger.debug(f"Content end: '...{preview_end}'")

                if result.page_count:
                    logger.debug(f"Document has {result.page_count} pages")
            elif raw_extracted_text:
                logger.warning(
                    f"Text became empty after preprocessing for {decision.ada}. Original text was present."
                )
            else:
                logger.warning(f"No text extracted from {decision.ada}")

            # Create a new ExtractionResult with the processed text for the importer
            final_extraction_result = ExtractionResult(
                text=final_text_to_log_and_save,
                page_count=result.page_count,
                metadata=extraction_metadata,
                is_scanned=bool(result.is_scanned),
                requires_vision=requires_vision,
                ocr_applied=ocr_applied,
                confidence=ocr_confidence,
            )
            # Use the importer to handle database operations
            updated_extraction = importer.import_extraction_result(
                decision=decision,
                result=final_extraction_result,  # Use the result with processed text
                provider_name=provider_name,
                processing_time_ms=processing_time_ms,
                extraction=extraction,
                is_corrupted=is_corrupted,
                preprocessing_result=(
                    preprocessing_result if "preprocessing_result" in locals() else None
                ),
            )

            # OCR replaced the text: re-run the text processes whose stored
            # offsets were just cleared, and refresh the search index.
            if ocr_applied and final_text_to_log_and_save:
                self._refresh_after_ocr(decision, updated_extraction)

            logger.info(
                f"Document {decision.ada} extracted",
                document_ada=decision.ada,
                character_count=len(final_text_to_log_and_save),
                page_count=result.page_count,
                processing_time_ms=processing_time_ms,
                provider=provider_name,
                corrupted=is_corrupted,
                extraction_status=(
                    ProcessingStatus.CORRUPTED_CONTENT.value
                    if is_corrupted
                    else (
                        ProcessingStatus.NEEDS_VISION.value
                        if final_extraction_result.requires_vision
                        else ProcessingStatus.COMPLETED.value
                    )
                ),
            )
            return True

        except Exception as e:
            logger.error(f"Error extracting text from {decision.ada}: {str(e)}")
            importer.mark_extraction_failed(extraction, str(e))
            return False

        finally:
            # Clean up temp file
            self.cleanup_temp_file(temp_path)
            logger.debug(f"Cleaned up temp file for {decision.ada}")


class DocumentAnalysisService:
    """
    Orchestrates the document analysis process
    """

    def __init__(self):
        self.text_extractor = TextExtractionProcessor()
        # We'll initialize other processors as needed

    def process_decision(
        self,
        decision: Decision,
        provider: str = None,
        force: bool = False,
        allow_ocr: bool = True,
    ) -> Dict[str, Any]:
        """
        Main entry point for processing a decision document
        """
        results = {
            "success": False,
            "extraction_status": None,
            "analysis_performed": [],
        }

        # Step 1: Extract text (if not already done)
        extraction = self._get_or_extract_text(
            decision, provider, force=force, allow_ocr=allow_ocr
        )
        if not extraction:
            return results

        results["extraction_status"] = extraction.extraction_status
        results["success"] = True

        # If we need vision processing, don't continue to analysis yet
        if extraction.extraction_status == ProcessingStatus.NEEDS_VISION:
            results["needs_vision"] = True
            return results

        # If extraction failed, don't continue
        if extraction.extraction_status != ProcessingStatus.COMPLETED:
            return results

        # Step 2: Generate summary if we have text
        # We can add this later

        return results

    def _get_or_extract_text(
        self,
        decision: Decision,
        provider: str = None,
        force: bool = False,
        allow_ocr: bool = True,
    ) -> Optional[DocumentExtraction]:
        """Get existing extraction or create a new one"""
        try:
            extraction = DocumentExtraction.objects.get(decision=decision)

            has_text = bool((extraction.raw_text or "").strip())

            if not force:
                # A COMPLETED row with text is done.  A COMPLETED row without
                # usable text is NOT done — fall through so OCR can recover it.
                if (
                    extraction.extraction_status == ProcessingStatus.COMPLETED
                    and has_text
                ):
                    return extraction

                if extraction.extraction_status == ProcessingStatus.NEEDS_VISION:
                    return extraction

                # If failed but we haven't retried too much, try again
                if (
                    extraction.extraction_status == ProcessingStatus.FAILED
                    and extraction.retry_count < 3
                ):
                    self.text_extractor.process_document(
                        decision, provider, allow_ocr=allow_ocr
                    )
                    return DocumentExtraction.objects.get(decision=decision)

                # Nothing to do (e.g. PROCESSING not stale yet) — process_document
                # owns the decision to re-run or bail out.
                if extraction.extraction_status in (
                    ProcessingStatus.PENDING,
                    ProcessingStatus.PROCESSING,
                    ProcessingStatus.COMPLETED,
                ):
                    self.text_extractor.process_document(
                        decision, provider, allow_ocr=allow_ocr
                    )
                    return DocumentExtraction.objects.get(decision=decision)

                return extraction

            # Forced re-extraction (recovery path): re-run even when a
            # COMPLETED/NEEDS_VISION row exists.
            self.text_extractor.process_document(
                decision, provider, force=True, allow_ocr=allow_ocr
            )
            return DocumentExtraction.objects.get(decision=decision)

        except DocumentExtraction.DoesNotExist:
            # No extraction yet, create one
            success = self.text_extractor.process_document(
                decision, provider, force=force, allow_ocr=allow_ocr
            )
            if success:
                return DocumentExtraction.objects.get(decision=decision)
            return None


# Here you would add additional services for each specific AI provider
class OpenAISummaryAnalyzer:
    """Generates summaries using OpenAI"""


class AnthropicSummaryAnalyzer:
    """Generates summaries using Anthropic Claude"""


class OpenAIEmbeddingGenerator:
    """Generates embeddings using OpenAI"""
