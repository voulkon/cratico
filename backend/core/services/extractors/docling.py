import os
import time

from core.protocols.extraction_protocol import ExtractionResult
from loguru import logger


class DoclingExtractor:
    """
    Text extractor using Docling library for advanced document processing.

    Note: Docling has heavy initialization (plugins, models, accelerators).
    Converter and chunker are cached after first use per instance.
    """

    # Class-level counters for performance monitoring
    _converter_init_count = 0
    _chunker_init_count = 0
    _total_converter_init_time = 0.0
    _total_chunker_init_time = 0.0

    def __init__(self, split_into_pages=True):
        """
        Initialize with configuration options

        Args:
            split_into_pages: Whether to split into pages/chunks (default: True)
        """
        self.split_into_pages = split_into_pages
        self._converter = None
        self._chunker = None
        self._instance_id = id(self)  # Track unique instances

    @property
    def converter(self):
        if self._converter is None:
            start_time = time.time()
            logger.info(
                f"[SYS]️ Initializing Docling DocumentConverter (instance {self._instance_id})..."
            )

            from docling.document_converter import DocumentConverter

            self._converter = DocumentConverter()

            init_time = time.time() - start_time
            DoclingExtractor._converter_init_count += 1
            DoclingExtractor._total_converter_init_time += init_time

            logger.info(
                f"[OK] DocumentConverter initialized in {init_time:.2f}s "
                f"(total inits: {DoclingExtractor._converter_init_count}, "
                f"avg time: {DoclingExtractor._total_converter_init_time / DoclingExtractor._converter_init_count:.2f}s)"
            )
        return self._converter

    @property
    def chunker(self):
        if self._chunker is None:
            start_time = time.time()
            logger.info(
                f"[SYS]️ Initializing Docling HybridChunker (instance {self._instance_id})..."
            )

            from docling.chunking import HybridChunker

            self._chunker = HybridChunker(tokenizer="BAAI/bge-small-en-v1.5")

            init_time = time.time() - start_time
            DoclingExtractor._chunker_init_count += 1
            DoclingExtractor._total_chunker_init_time += init_time

            logger.info(
                f"[OK] HybridChunker initialized in {init_time:.2f}s "
                f"(total inits: {DoclingExtractor._chunker_init_count}, "
                f"avg time: {DoclingExtractor._total_chunker_init_time / DoclingExtractor._chunker_init_count:.2f}s)"
            )
        return self._chunker

    def extract_text(self, file_path: str) -> ExtractionResult:
        """Extract text using Docling"""
        try:
            # Process the document
            result = self.converter.convert(file_path)
            doc = result.document

            # Extract text
            full_text = doc.export_to_text()

            # Count pages if available, or estimate
            page_count = len(doc.pages) if hasattr(doc, "pages") and doc.pages else 1

            # Determine if scanned (heuristic)
            is_scanned = len(full_text.strip()) < 100

            # Initial metadata
            metadata = {
                "provider": "DOCLING",
                "file_size_bytes": os.path.getsize(file_path),
            }

            # If not splitting into pages, return just the full text
            if not self.split_into_pages:
                metadata["skip_page_splitting"] = True
                logger.debug(
                    f"Docling extraction: returning full text without chunking ({len(full_text)} chars)"
                )
                return ExtractionResult(
                    text=full_text,
                    page_count=page_count,
                    is_scanned=is_scanned,
                    # Important: Set pages_data to None to skip page creation
                    pages_data=None,
                    metadata=metadata,
                )

            # Otherwise, use chunker to create "pages" (semantic chunks)
            logger.debug(f"Docling extraction: attempting to create semantic chunks")
            chunk_iter = self.chunker.chunk(doc)

            pages_data = []
            for i, chunk in enumerate(chunk_iter):
                try:
                    enriched_text = self.chunker.contextualize(chunk=chunk)
                    if enriched_text and not enriched_text.isspace():
                        for_page_data = {
                            "page_number": i
                            + 1,  # This is a chunk number, not a page number
                            "text": enriched_text,
                            "character_count": len(enriched_text),
                        }
                        pages_data.append(for_page_data)
                except Exception as chunk_error:
                    logger.warning(f"Failed to process chunk {i}: {chunk_error}")
                    continue

            # Log chunking results
            if pages_data:
                logger.debug(
                    f"Docling extraction: created {len(pages_data)} semantic chunks"
                )
                metadata["chunk_count"] = len(pages_data)
                metadata["chunking_method"] = "hybrid_chunker"
            else:
                logger.debug(
                    f"Docling extraction: no chunks created, will use single page fallback"
                )

            return ExtractionResult(
                text=full_text,
                page_count=page_count,
                is_scanned=is_scanned,
                pages_data=pages_data if pages_data else None,
                metadata=metadata,
            )

        except ImportError as e:
            # Don't hide the real error - log it and re-raise
            logger.error(f"ImportError during Docling extraction: {e}")
            logger.error(
                f"This is likely a missing optional dependency, not Docling itself"
            )
            logger.exception("Full traceback:")
            raise

        except Exception as e:
            logger.error(f"Error in Docling extraction: {e}")
            logger.exception("Full traceback:")
            raise
