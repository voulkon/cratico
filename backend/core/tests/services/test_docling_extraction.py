"""
Test Docling extraction to debug the mysterious "not installed" error.
Run this inside the worker container to see the actual error.
"""

import pytest

pytest.importorskip("docling", reason="docling is not installed (install the 'docling' poetry group)")

from core.services.extractors.docling import DoclingExtractor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from loguru import logger


@pytest.fixture
def docling_extractor():
    """Fixture for Docling extractor"""
    return DoclingExtractor(split_into_pages=False)  # No chunking to simplify


@pytest.fixture
def pymupdf_extractor():
    """Fixture for PyMuPDF extractor"""
    return PyMuPDFExtractor()


def test_docling_basic_extraction(docling_extractor, not_corrupted_file_path):
    """
    Basic test: Can Docling extract text at all?
    This will show us the REAL error message.
    """
    logger.info(f"[TEST] Testing Docling extraction on: {not_corrupted_file_path}")

    try:
        result = docling_extractor.extract_text(str(not_corrupted_file_path))

        logger.success(f"[OK] Extraction succeeded!")
        logger.info(f"  Text length: {len(result.text)}")
        logger.info(f"  Page count: {result.page_count}")
        logger.info(f"  Is scanned: {result.is_scanned}")
        logger.info(f"  Metadata: {result.metadata}")
        logger.info(f"  Preview: {result.text[:200]}...")

        # Basic assertions
        assert result.text, "Text should not be empty"
        assert len(result.text) > 100, "Text should have meaningful content"
        assert result.page_count > 0, "Should have at least one page"

        return result

    except Exception as e:
        logger.error(f"[ERROR] Extraction failed with: {type(e).__name__}")
        logger.error(f"   Error message: {str(e)}")
        logger.exception("Full traceback:")
        raise


def test_compare_pymupdf_vs_docling(
    pymupdf_extractor, docling_extractor, not_corrupted_file_path
):
    """
    Compare PyMuPDF (known working) vs Docling side-by-side.
    """
    logger.info(f"\n{'='*60}")
    logger.info(f"[CHART] COMPARISON TEST: PyMuPDF vs Docling")
    logger.info(f"{'='*60}\n")

    # Test PyMuPDF first (baseline)
    logger.info("1️⃣ Testing PyMuPDF (baseline)...")
    try:
        pymupdf_result = pymupdf_extractor.extract_text(str(not_corrupted_file_path))
        logger.success(f"[OK] PyMuPDF succeeded: {len(pymupdf_result.text)} chars")
    except Exception as e:
        logger.error(f"[ERROR] PyMuPDF failed: {e}")
        pytest.fail("PyMuPDF (baseline) should not fail")

    # Test Docling
    logger.info("\n2️⃣ Testing Docling...")
    try:
        docling_result = docling_extractor.extract_text(str(not_corrupted_file_path))
        logger.success(f"[OK] Docling succeeded: {len(docling_result.text)} chars")

        # Compare results
        logger.info(f"\n[METRIC] Comparison:")
        logger.info(f"  PyMuPDF chars: {len(pymupdf_result.text)}")
        logger.info(f"  Docling chars:  {len(docling_result.text)}")
        logger.info(
            f"  Difference: {abs(len(pymupdf_result.text) - len(docling_result.text))} chars"
        )

        # Both should extract something
        assert docling_result.text, "Docling should extract text"
        assert (
            len(docling_result.text) > 100
        ), "Docling should extract meaningful content"

    except Exception as e:
        logger.error(f"[ERROR] Docling failed: {type(e).__name__}: {str(e)}")
        logger.error(f"\n[SCAN] This is the REAL error we need to fix!")
        raise


def test_docling_all_test_files(docling_extractor, pdf_for_testing_path):
    """
    Test Docling on ALL available test PDFs to see if any work.
    """
    pdf_files = list(pdf_for_testing_path.glob("*.pdf"))

    logger.info(f"\n{'='*60}")
    logger.info(f"[DIR] Found {len(pdf_files)} PDF files in test directory")
    logger.info(f"{'='*60}\n")

    results = []

    for pdf_file in pdf_files:
        logger.info(f"Testing: {pdf_file.name}")
        try:
            result = docling_extractor.extract_text(str(pdf_file))
            success = True
            char_count = len(result.text)
            error = None
            logger.success(f"  [OK] Success - {char_count} chars")
        except Exception as e:
            success = False
            char_count = 0
            error = f"{type(e).__name__}: {str(e)}"
            logger.error(f"  [ERROR] Failed - {error}")

        results.append(
            {
                "file": pdf_file.name,
                "success": success,
                "chars": char_count,
                "error": error,
            }
        )

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info(f"[CHART] SUMMARY")
    logger.info(f"{'='*60}")
    success_count = sum(1 for r in results if r["success"])
    logger.info(f"[OK] Successful: {success_count}/{len(results)}")
    logger.info(f"[ERROR] Failed: {len(results) - success_count}/{len(results)}")

    if success_count == 0:
        logger.error("\n[WARN]️  NONE of the PDFs could be processed!")
        logger.error("This suggests a systemic issue with Docling setup.")

        # Show unique error types
        unique_errors = set(r["error"] for r in results if r["error"])
        logger.error(f"\nUnique errors encountered:")
        for error in unique_errors:
            logger.error(f"  • {error}")

    # Don't fail the test, just report
    assert len(pdf_files) > 0, "Should have at least one test PDF"


def test_docling_import_check():
    """
    Verify that Docling and its dependencies are actually importable.
    """
    logger.info("[SCAN] Checking Docling imports...")

    try:
        import docling

        logger.success(
            f"[OK] docling package imported: {docling.__version__ if hasattr(docling, '__version__') else 'unknown version'}"
        )
    except ImportError as e:
        logger.error(f"[ERROR] Cannot import docling: {e}")
        pytest.fail("Docling package is not installed")

    try:
        from docling.document_converter import DocumentConverter

        logger.success("[OK] DocumentConverter imported")
    except ImportError as e:
        logger.error(f"[ERROR] Cannot import DocumentConverter: {e}")
        pytest.fail("DocumentConverter not available")

    try:
        pass

        logger.success("[OK] HybridChunker imported")
    except ImportError as e:
        logger.error(f"[ERROR] Cannot import HybridChunker: {e}")
        pytest.fail("HybridChunker not available")

    # Try to initialize converter
    try:
        DocumentConverter()
        logger.success("[OK] DocumentConverter initialized successfully")
    except Exception as e:
        logger.error(
            f"[ERROR] Failed to initialize DocumentConverter: {type(e).__name__}: {e}"
        )
        raise

    logger.success("\n[OK] All Docling imports successful!")
