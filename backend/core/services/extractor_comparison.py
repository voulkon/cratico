import time
from typing import Any, Dict

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingProvider
from core.services.document_processor import (
    BaseDocumentProcessor,
    DocumentAnalysisService,
)
from core.services.extractors.docling import DoclingExtractor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from loguru import logger


class ExtractorComparison(BaseDocumentProcessor):
    """Compare different extraction methods on the same document"""

    def __init__(self):
        # Only include extractors that can run synchronously
        self.sync_extractors = {
            "PyMuPDF": PyMuPDFExtractor(),
            "Docling": DoclingExtractor(),
            "Docling (no chunks)": DoclingExtractor(split_into_pages=False),
        }

        # Async extractors that need worker processing
        self.async_extractors = [
            ProcessingProvider.DOCLING,
            # Add other worker-only extractors here
        ]

    def compare_extractors(
        self, decision: Decision, include_async: bool = False
    ) -> Dict[str, Any]:
        """
        Compare all extractors on a single document

        Args:
            decision: The decision to compare
            include_async: Whether to include async extractors (requires worker)

        Returns:
            Dict containing results from each extractor and comparison metrics
        """
        if not decision.document_url:
            logger.warning(f"Decision {decision.ada} has no document URL")
            return {"error": "No document URL"}

        logger.info(f"[SCAN] Comparing extractors for {decision.ada}")

        results = {
            "decision_ada": decision.ada,
            "document_url": decision.document_url,
            "extractions": {},
            "comparison": {},
            "async_processing": include_async,
        }

        # Process sync extractors
        temp_path = None
        try:
            # Download the PDF once for sync extractors
            if self.sync_extractors:
                temp_path, success = self.download_pdf(decision.document_url)
                if not success:
                    logger.error(f"[ERROR] Failed to download PDF for {decision.ada}")
                    return {"error": "Failed to download PDF"}

                # Run sync extractors on the same file
                for extractor_name, extractor in self.sync_extractors.items():
                    logger.info(f"[CONFIG] Running {extractor_name} on {decision.ada}")

                    start_time = time.time()
                    try:
                        result = extractor.extract_text(temp_path)
                        processing_time = int((time.time() - start_time) * 1000)

                        results["extractions"][extractor_name] = {
                            "success": True,
                            "result": result,
                            "processing_time_ms": processing_time,
                            "text_length": len(result.text),
                            "page_count": result.page_count,
                            "has_pages_data": result.pages_data is not None,
                            "pages_data_count": (
                                len(result.pages_data) if result.pages_data else 0
                            ),
                            "extraction_type": "sync",
                        }

                        logger.info(
                            f"[OK] {extractor_name}: {len(result.text)} chars, {result.page_count} pages, {processing_time}ms"
                        )

                    except Exception as e:
                        results["extractions"][extractor_name] = {
                            "success": False,
                            "error": str(e),
                            "processing_time_ms": int(
                                (time.time() - start_time) * 1000
                            ),
                            "extraction_type": "sync",
                        }
                        logger.error(f"[ERROR] {extractor_name} failed: {e}")

        finally:
            # Clean up temp file
            if temp_path:
                self.cleanup_temp_file(temp_path)

        # Process async extractors if requested
        if include_async:
            self._process_async_extractors(decision, results)

        # Generate comparison metrics
        results["comparison"] = self._generate_comparison_metrics(
            results["extractions"]
        )

        return results

    def _process_async_extractors(self, decision: Decision, results: Dict[str, Any]):
        """Process extractors that require async/worker processing"""
        logger.info(f"[RETRY] Processing async extractors for {decision.ada}")

        analysis_service = DocumentAnalysisService()

        for provider in self.async_extractors:
            provider_name = provider.value
            logger.info(f"[CONFIG] Running {provider_name} on {decision.ada} (async)")

            start_time = time.time()
            try:
                # Use the analysis service to process with the specific provider
                process_result = analysis_service.process_decision(
                    decision, provider_name
                )
                processing_time = int((time.time() - start_time) * 1000)

                if process_result.get("success"):
                    # Get the extraction result
                    extraction = DocumentExtraction.objects.get(decision=decision)

                    # Check if we have page data for this extraction
                    has_pages = extraction.pages.exists()
                    pages_count = extraction.pages.count() if has_pages else 0

                    results["extractions"][provider_name] = {
                        "success": True,
                        "processing_time_ms": processing_time,
                        "text_length": (
                            len(extraction.raw_text) if extraction.raw_text else 0
                        ),
                        "page_count": extraction.page_count or 0,
                        "has_pages_data": has_pages,
                        "pages_data_count": pages_count,
                        "extraction_type": "async",
                        "extraction_status": extraction.extraction_status,
                        # Note: We don't include the full result object for async to avoid serialization issues
                    }

                    logger.info(
                        f"[OK] {provider_name}: {len(extraction.raw_text or '')} chars, {extraction.page_count} pages, {processing_time}ms"
                    )
                else:
                    results["extractions"][provider_name] = {
                        "success": False,
                        "error": "Processing failed",
                        "processing_time_ms": processing_time,
                        "extraction_type": "async",
                    }
                    logger.error(f"[ERROR] {provider_name} processing failed")

            except Exception as e:
                results["extractions"][provider_name] = {
                    "success": False,
                    "error": str(e),
                    "processing_time_ms": int((time.time() - start_time) * 1000),
                    "extraction_type": "async",
                }
                logger.error(f"[ERROR] {provider_name} failed: {e}")

    def _generate_comparison_metrics(
        self, extractions: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Generate comparison metrics between extractors"""
        successful_extractions = {
            name: data
            for name, data in extractions.items()
            if data.get("success", False)
        }

        if len(successful_extractions) < 1:
            return {"note": "No successful extractions for comparison"}

        metrics = {}

        # Text length comparison
        text_lengths = {
            name: data["text_length"] for name, data in successful_extractions.items()
        }
        metrics["text_lengths"] = text_lengths

        if len(text_lengths) > 1:
            metrics["text_length_diff"] = max(text_lengths.values()) - min(
                text_lengths.values()
            )

        # Page count comparison
        page_counts = {
            name: data["page_count"] for name, data in successful_extractions.items()
        }
        metrics["page_counts"] = page_counts

        if len(page_counts) > 1:
            metrics["page_count_consistent"] = len(set(page_counts.values())) == 1

        # Performance comparison
        processing_times = {
            name: data["processing_time_ms"]
            for name, data in successful_extractions.items()
        }
        metrics["processing_times_ms"] = processing_times

        if processing_times:
            fastest = min(processing_times.keys(), key=lambda k: processing_times[k])
            metrics["fastest_extractor"] = fastest

        # Separate sync vs async extractors
        sync_extractors = [
            name
            for name, data in successful_extractions.items()
            if data.get("extraction_type") == "sync"
        ]
        async_extractors = [
            name
            for name, data in successful_extractions.items()
            if data.get("extraction_type") == "async"
        ]

        metrics["sync_extractors"] = sync_extractors
        metrics["async_extractors"] = async_extractors

        return metrics
