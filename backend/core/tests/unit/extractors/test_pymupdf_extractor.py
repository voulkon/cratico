import pytest


@pytest.mark.fast
def test_pymupdf_extractor(pymupdf_result, page_count_of_pdf):

    assert isinstance(pymupdf_result.text, str)
    assert pymupdf_result.page_count == page_count_of_pdf
    assert pymupdf_result.is_scanned is False
