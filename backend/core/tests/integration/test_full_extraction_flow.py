from unittest.mock import patch

import pytest
from core.models.document_analysis import ProcessingProvider, ProcessingStatus
from core.services.document_processor import DocumentAnalysisService


@pytest.mark.requires_postgresql
@pytest.mark.django_db
def test_full_extraction_workflow(
    mock_decision, pdf_to_extract_text_from, expected_text_in_pdf, page_count_of_pdf
):
    """Test the full extraction workflow with real database"""

    # Create a Greek text sample
    greek_text = """
    ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ
    ΥΠΟΥΡΓΕΙΟ ΟΙΚΟΝΟΜΙΚΩΝ

    ΑΠΟΦΑΣΗ

    Θέμα: Έγκριση διοικητικής δαπάνης για το έτος 2023

    Έχοντας υπόψη τις διατάξεις του άρθρου 7 του Ν. 4270/2014, αποφασίζουμε:

    1. Εγκρίνουμε τη δαπάνη ύψους 50.000 ευρώ για την κάλυψη λειτουργικών αναγκών.
    2. Η δαπάνη θα βαρύνει τον προϋπολογισμό του οικονομικού έτους 2023.

    Ο ΥΠΟΥΡΓΟΣ
    """

    # Set up mocks
    with patch(
        "core.services.document_processor.TextExtractionProcessor.download_pdf"
    ) as mock_download, patch(
        "core.services.document_processor.TextExtractionProcessor.cleanup_temp_file"
    ) as mock_cleanup:
        mock_download.return_value = (pdf_to_extract_text_from, True)
        mock_cleanup.return_value = None

        # Run the document analysis service
        service = DocumentAnalysisService()
        result = service.process_decision(
            mock_decision, provider=ProcessingProvider.PYMUPDF
        )

    # Assertions
    assert result["success"] is True
    assert result["extraction_status"] == ProcessingStatus.COMPLETED

    # Test the search functionality
    from core.models.document_analysis import DocumentExtraction
    from django.contrib.postgres.search import SearchQuery

    query = SearchQuery("τμημα", config="greek")
    results = DocumentExtraction.objects.filter(search_vector=query)
    assert results.count() == 1

    # Test searching for "δαπάνη"
    query = SearchQuery("δαπάνη", config="greek")
    results = DocumentExtraction.objects.filter(search_vector=query)
    assert results.count() == 1

    # Test searching for "προϋπολογισμό"
    query = SearchQuery("προϋπολογισμό", config="greek")
    results = DocumentExtraction.objects.filter(search_vector=query)
    assert results.count() == 1
