from typing import Any, Optional

from core.models.decisions import Decision
from core.models.document_analysis import (
    DocumentExtraction,
    DocumentPage,
    ProcessingStatus,
    TextProcessResolution,
)
from core.protocols.extraction_protocol import ExtractionResult
from django.db import transaction
from django.utils import timezone
from loguru import logger


class DocumentExtractionImporter:
    """Handles importing document extraction results to the database"""

    def import_extraction_result(
        self,
        decision: Decision,
        result: ExtractionResult,
        provider_name: str,
        processing_time_ms: int,
        extraction: Optional[DocumentExtraction] = None,
        is_corrupted: bool = False,
        preprocessing_result: Optional[Any] = None,  # Add preprocessing result
    ) -> DocumentExtraction:
        """
        Import an extraction result for a decision

        Args:
            decision: The decision being processed
            result: The extraction result object
            provider_name: Name of the provider used
            processing_time_ms: Time taken to process in milliseconds
            extraction: Optional existing extraction object to update (will create if None)
            is_corrupted: Whether the content was detected as corrupted
            preprocessing_result: Optional preprocessing result with additional metadata

        Returns:
            DocumentExtraction: The created or updated extraction record
        """
        # Check if we already have an extraction or use the one provided
        if extraction is None:
            extraction, created = DocumentExtraction.objects.get_or_create(
                decision=decision,
                defaults={"extraction_status": ProcessingStatus.PENDING},
            )

        # Common fields to update
        previous_text = extraction.raw_text or ""
        text_changed = (result.text or "") != previous_text
        extraction.extraction_provider = provider_name
        extraction.extraction_date = timezone.now()
        extraction.processing_time_ms = processing_time_ms
        extraction.page_count = result.page_count

        # For backward compatibility, still store the full text
        # TODO: Remove this after migration is complete
        extraction.raw_text = result.text

        # OCR provenance.  Only overwrite ocr_metadata when OCR actually ran —
        # a later native re-extraction must not erase the OCR audit trail of
        # the text that was recovered.
        extraction.ocr_applied = bool(result.ocr_applied)
        if result.ocr_applied:
            extraction.ocr_confidence = result.confidence
            extraction.ocr_metadata = result.metadata or {}
        elif text_changed:
            extraction.ocr_confidence = None

        # Handle differently based on whether it's a scanned document.
        #
        # ``requires_vision`` is the only "we truly cannot read this" signal.
        # A scanned document WITH OCR text is COMPLETED — the corruption
        # detector may still flag OCR artifacts, but discarding the text would
        # defeat the whole recovery path.
        if result.requires_vision:
            extraction.extraction_status = ProcessingStatus.NEEDS_VISION
            extraction.is_scanned_document = True
            extraction.character_count = len(result.text) if result.text else 0
        elif is_corrupted and not result.ocr_applied:
            extraction.extraction_status = ProcessingStatus.CORRUPTED_CONTENT
            logger.warning(
                f"Marking extraction for {decision.ada} as CORRUPTED_CONTENT."
            )

            # Store corruption details if available
            if preprocessing_result:
                extraction.preprocessing_metadata = {
                    "corruption_indicators": preprocessing_result.corruption_indicators,
                    "confidence_score": preprocessing_result.confidence_score,
                    "performance_stats": preprocessing_result.performance_stats,
                    "processed_at": timezone.now().isoformat(),
                    "strategy_used": preprocessing_result.corruption_indicators.get(
                        "strategy_used", "unknown"
                    ),
                }
        else:
            # Complete the extraction (native good text OR usable OCR text)
            extraction.extraction_status = ProcessingStatus.COMPLETED
            extraction.is_scanned_document = bool(result.is_scanned)
            extraction.character_count = len(result.text) if result.text else 0

            # Store preprocessing metadata even for non-corrupted text.  OCR
            # text may be flagged as "corrupted" by the artifact detector —
            # record the indicators, but keep the COMPLETED status above.
            if preprocessing_result:
                extraction.preprocessing_metadata = {
                    "confidence_score": preprocessing_result.confidence_score,
                    "performance_stats": preprocessing_result.performance_stats,
                    "processed_at": timezone.now().isoformat(),
                    "strategy_used": (
                        preprocessing_result.corruption_indicators or {}
                    ).get("strategy_used", "unknown"),
                }

        # Persist OCR fallback audit details that the processor put on the
        # ExtractionResult (native char count, whether OCR ran and why).
        metadata_extra = {
            key: (result.metadata or {})[key]
            for key in ("native_extraction", "ocr_fallback")
            if result.metadata and key in result.metadata
        }
        if metadata_extra:
            extraction.preprocessing_metadata = {
                **(extraction.preprocessing_metadata or {}),
                **metadata_extra,
            }

        # Use transaction to ensure consistency between extraction and pages
        with transaction.atomic():
            # Save the extraction first
            extraction.save()

            # Text was replaced (OCR or a different extraction): every stored
            # char offset is now meaningless.  Delete the runs (spans cascade)
            # and the decision-level resolutions before anything re-runs on the
            # new text.
            if text_changed:
                deleted_runs, _ = extraction.text_process_runs.all().delete()
                deleted_res, _ = TextProcessResolution.objects.filter(
                    decision=decision
                ).delete()
                if deleted_runs or deleted_res:
                    logger.info(
                        f"Text changed for {decision.ada} — cleared "
                        f"{deleted_runs} text-process run/span row(s) and "
                        f"{deleted_res} resolution(s) with stale offsets"
                    )

            # Check if we should skip page creation
            skip_page_creation = result.metadata and result.metadata.get(
                "skip_page_splitting", False
            )

            if skip_page_creation:
                logger.debug(f"Skipping page creation for {decision.ada} as requested")
                # Create a single page with all text as a reference
                self._create_single_page_fallback(extraction, result.text)
            # Create or update page records if pages_data is available
            elif hasattr(result, "pages_data") and result.pages_data:
                self._create_or_update_pages(extraction, result.pages_data)
            else:
                # Fallback: create a single page with all the text.
                # This is the normal path for extractors that do not report
                # per-page data, so it must not warn once per document.
                logger.debug(
                    f"No pages_data available for {decision.ada}, creating single page"
                )
                self._create_single_page_fallback(extraction, result.text)

        return extraction

    def _create_or_update_pages(
        self, extraction: DocumentExtraction, pages_data: list
    ) -> None:
        """Create or update page records from pages_data"""
        # Clear existing pages if any (for re-processing scenarios)
        extraction.pages.all().delete()

        # Create new page records
        pages_to_create = []
        for page_data in pages_data:
            page = DocumentPage(
                extraction=extraction,
                page_number=page_data["page_number"],
                character_count=page_data.get(
                    "character_count",
                    len(page_data["text"]) if page_data["text"] else 0,
                ),
                # TODO: Add image/table detection from page_data if available
                has_images=page_data.get("has_images", False),
                has_tables=page_data.get("has_tables", False),
            )
            pages_to_create.append(page)

        # Bulk create for better performance
        DocumentPage.objects.bulk_create(pages_to_create)
        logger.debug(
            f"Created {len(pages_to_create)} pages for {extraction.decision.ada}"
        )

    def _create_single_page_fallback(
        self, extraction: DocumentExtraction, text: str
    ) -> None:
        """Fallback: create a single page with all the text"""
        # Clear existing pages
        extraction.pages.all().delete()

        DocumentPage.objects.create(
            extraction=extraction,
            page_number=1,
            character_count=len(text) if text else 0,
        )
        logger.debug(f"Created single fallback page for {extraction.decision.ada}")

    def mark_extraction_failed(
        self, extraction: DocumentExtraction, error_msg: str
    ) -> DocumentExtraction:
        """Update extraction record with failure information"""
        extraction.extraction_status = ProcessingStatus.FAILED
        extraction.error_message = error_msg
        extraction.retry_count += 1
        extraction.save()
        return extraction
