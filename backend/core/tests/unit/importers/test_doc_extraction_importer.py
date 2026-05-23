import pytest
from core.importers.document_extraction import DocumentExtractionImporter
from core.models.document_analysis import DocumentExtraction, ProcessingStatus

# Use your existing fixture


@pytest.mark.django_db
@pytest.mark.requires_postgresql
def test_document_extraction_import(
    mock_decision, pymupdf_result, page_count_of_pdf, expected_text_in_pdf
):
    """Test document extraction import with all functionality"""
    # Skip if not PostgreSQL
    from django.conf import settings

    # Skip without using pytest.skip() which can cause issues with collection
    if not getattr(settings, "USING_POSTGRESQL_FOR_TESTS", False):
        pytest.fail("This test requires PostgreSQL (set PG_TEST=1)")

    # Import the extraction result
    importer = DocumentExtractionImporter()
    extraction = importer.import_extraction_result(
        decision=mock_decision,
        result=pymupdf_result,
        provider_name="PYMUPDF",
        processing_time_ms=150,
    )

    # Basic validation (from the original test_basic_import)
    assert extraction.extraction_status == ProcessingStatus.COMPLETED
    assert expected_text_in_pdf in extraction.raw_text
    assert extraction.page_count == page_count_of_pdf
    assert extraction.is_scanned_document is False
    assert extraction.extraction_provider == "PYMUPDF"

    # PostgreSQL-specific validation (from test_text_imported_with_search)
    # Force a database refresh to ensure triggers ran
    extraction.refresh_from_db()

    # Check that search vector exists (PostgreSQL feature)
    assert extraction.search_vector is not None

    # Test search functionality if the extracted text contains specific terms
    for search_term in ["test", "document", "τμημα"]:
        if search_term.lower() in pymupdf_result.text.lower():
            from django.contrib.postgres.search import SearchQuery

            # Choose appropriate config based on the search term language
            config = "greek" if search_term == "τμημα" else "english"

            query = SearchQuery(search_term, config=config)
            results = DocumentExtraction.objects.filter(search_vector=query)

            # Verify the document is found in search results
            assert results.count() >= 1
            assert extraction.pk in [
                r.pk for r in results
            ], f"Search term '{search_term}' not found in search vector"
