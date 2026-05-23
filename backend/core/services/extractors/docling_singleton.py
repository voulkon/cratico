"""
Singleton pattern for Docling extractors to prevent repeated heavy initialization.

This module provides thread-safe singleton access to Docling extractors,
ensuring that the heavy DocumentConverter and HybridChunker are initialized
only once per worker process, not once per task.

Usage in document_processor.py:
    from core.services.extractors.docling_singleton import get_docling_extractor

    # In TextExtractionProcessor class:
    extractors = {
        ProcessingProvider.DOCLING: get_docling_extractor(),
        # ...
    }
"""

import threading
from functools import lru_cache

from core.services.extractors.docling import DoclingExtractor
from loguru import logger


# Thread-safe singleton using lru_cache
@lru_cache(maxsize=1)
def get_docling_extractor(split_into_pages=True):
    """
    Get or create a singleton Docling extractor instance.

    This ensures that the expensive DocumentConverter and HybridChunker
    are initialized only once per worker process.

    Args:
        split_into_pages: Whether to split documents into pages/chunks

    Returns:
        DoclingExtractor: Singleton instance
    """
    logger.info("[CONFIG] Creating singleton Docling extractor instance")
    return DoclingExtractor(split_into_pages=split_into_pages)


# Alternative: Manual singleton with explicit locking
class DoclingExtractorSingleton:
    """
    Thread-safe singleton for Docling extractor.

    Use this if you need more control than lru_cache provides.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls, split_into_pages=True):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    logger.info(
                        "[CONFIG] Creating singleton Docling extractor instance (manual)"
                    )
                    cls._instance = DoclingExtractor(split_into_pages=split_into_pages)
        return cls._instance

    @classmethod
    def get_instance(cls, split_into_pages=True):
        """Get the singleton instance."""
        if cls._instance is None:
            cls(split_into_pages=split_into_pages)
        return cls._instance

    @classmethod
    def reset(cls):
        """Reset the singleton (mainly for testing)."""
        with cls._lock:
            cls._instance = None


# Module-level instance (simplest approach)
_docling_extractor_instance = None
_docling_extractor_lock = threading.Lock()


def get_module_level_extractor(split_into_pages=True):
    """
    Get module-level singleton extractor.

    This is the simplest approach and works well for Celery workers
    since each worker process has its own memory space.
    """
    global _docling_extractor_instance

    if _docling_extractor_instance is None:
        with _docling_extractor_lock:
            if _docling_extractor_instance is None:
                logger.info("[CONFIG] Creating module-level Docling extractor instance")
                _docling_extractor_instance = DoclingExtractor(
                    split_into_pages=split_into_pages
                )

    return _docling_extractor_instance
