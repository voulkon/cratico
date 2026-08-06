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


class TextExtractionProcessor(BaseDocumentProcessor):
    """Handles text extraction from PDFs using various providers"""

    # Define extractors as class variables (shared across all instances)
    # NOTE: PyMuPDF is lightweight and fast (0.5s), Docling is heavy but more accurate (12s+ init)
    # Use DOCUMENT_EXTRACTOR env var to override: PYMUPDF (default) or DOCLING
    extractors = {
        ProcessingProvider.PYMUPDF: PyMuPDFExtractor(),
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

    def process_document(self, decision: Decision, provider: str = None) -> bool:
        """
        Main entry point for text extraction

        Args:
            decision: The decision to process
            provider: Optional provider name to use (defaults to PYPDF)

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

        # If not pending, we've already processed or are processing it
        if not created and extraction.extraction_status != ProcessingStatus.PENDING:
            if extraction.extraction_status == ProcessingStatus.COMPLETED:
                logger.info(f"Document {decision.ada} already extracted")
                return True
            elif extraction.extraction_status == ProcessingStatus.CORRUPTED_CONTENT:
                logger.info(f"Document {decision.ada} already marked as corrupted.")
                return True
            elif extraction.extraction_status == ProcessingStatus.PROCESSING:
                logger.info(f"Document {decision.ada} is currently being processed")
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

            raw_extracted_text = result.text
            processed_text = (
                raw_extracted_text  # Default to raw if no processing happens
            )
            is_corrupted = False
            preprocessing_result = None

            if raw_extracted_text and not raw_extracted_text.isspace():
                logger.info(
                    f"Starting text preprocessing for {decision.ada} (Original length: {len(raw_extracted_text)})"
                )

                # Get the Pydantic model from preprocessor
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
                    logger.info(
                        f"Text preprocessed for {decision.ada}. New length: {len(processed_text)}"
                    )
                else:
                    logger.info(
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

            # Log extraction results with content preview
            if final_text_to_log_and_save:
                text_length = len(final_text_to_log_and_save)
                # Show first and last 100 characters
                preview_start = final_text_to_log_and_save[:100].strip()
                preview_end = (
                    final_text_to_log_and_save[-100:].strip()
                    if text_length > 100
                    else ""
                )

                logger.info(
                    f"Extracted {text_length} characters from {decision.ada} in {processing_time_ms}ms"
                )
                logger.info(f"Content start: '{preview_start}...'")
                if preview_end and preview_end != preview_start:
                    logger.info(f"Content end: '...{preview_end}'")

                if result.page_count:
                    logger.info(f"Document has {result.page_count} pages")
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
                char_count=len(final_text_to_log_and_save),
                metadata=result.metadata,
            )
            # Use the importer to handle database operations
            importer.import_extraction_result(
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

            logger.info(f"Successfully processed {decision.ada}")
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
        self, decision: Decision, provider: str = None
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
        extraction = self._get_or_extract_text(decision, provider)
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
        self, decision: Decision, provider: str = None
    ) -> Optional[DocumentExtraction]:
        """Get existing extraction or create a new one"""
        try:
            extraction = DocumentExtraction.objects.get(decision=decision)

            # If completed or needs vision, return it
            if extraction.extraction_status in (
                ProcessingStatus.COMPLETED,
                ProcessingStatus.NEEDS_VISION,
            ):
                return extraction

            # If failed but we haven't retried too much, try again
            if (
                extraction.extraction_status == ProcessingStatus.FAILED
                and extraction.retry_count < 3
            ):
                self.text_extractor.process_document(decision, provider)
                return DocumentExtraction.objects.get(decision=decision)

            # Otherwise, return what we have
            return extraction

        except DocumentExtraction.DoesNotExist:
            # No extraction yet, create one
            success = self.text_extractor.process_document(decision, provider)
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
