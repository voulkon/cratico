import pytest
from core.services.extractors.plain_text import PlainTextExtractor


@pytest.mark.fast
def test_plaintext_extractor(pdf_to_extract_text_from):

    extractor = PlainTextExtractor()
    result = extractor.extract_text(pdf_to_extract_text_from)

    assert isinstance(result.text, str)
    assert result.page_count == 1
    assert result.is_scanned is False
