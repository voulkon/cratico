from unittest.mock import MagicMock, patch

import pytest
from core.models.document_analysis import ProcessingProvider, ProcessingStatus
from core.services.document_processor import TextExtractionProcessor


@pytest.mark.django_db
@pytest.mark.requires_postgresql
def test_process_document_with_pymupdf(
    mock_decision, pdf_to_extract_text_from, expected_text_in_pdf, page_count_of_pdf
):
    """Test the text extraction processor with PlainTextExtractor"""

    # Create sample text content

    # Set up mocks
    with patch(
        "core.services.document_processor.TextExtractionProcessor.download_pdf"
    ) as mock_download, patch(
        "core.services.document_processor.TextExtractionProcessor.cleanup_temp_file"
    ) as mock_cleanup:
        mock_download.return_value = (pdf_to_extract_text_from, True)
        mock_cleanup.return_value = None

        # Patch PostgreSQL-specific functionality when needed
        with patch(
            "django.contrib.postgres.search.SearchVectorField.contribute_to_class",
            MagicMock(),
        ):
            # Create and run the processor
            processor = TextExtractionProcessor()

            # Ensure the PlainTextExtractor is registered
            # (adjust if you have a different registration mechanism)
            from core.services.extractors.pymupdf import PyMuPDFExtractor

            processor.extractors = {ProcessingProvider.PYMUPDF: PyMuPDFExtractor()}

            # Run the processor
            result = processor.process_document(
                mock_decision, ProcessingProvider.PYMUPDF
            )

    # Assertions
    assert result is True

    # Check the extraction was saved in the database
    from core.models.document_analysis import DocumentExtraction

    extraction = DocumentExtraction.objects.get(decision=mock_decision)
    assert extraction.extraction_status == ProcessingStatus.COMPLETED
    assert expected_text_in_pdf in extraction.raw_text
    assert extraction.page_count == page_count_of_pdf
    assert extraction.extraction_provider == ProcessingProvider.PYMUPDF
