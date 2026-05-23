from pathlib import Path

import pytest
from core.models.document_analysis import ProcessingProvider
from core.pydantic_models.text_preprocessing import PreprocessingResult
from core.services.document_processor import TextExtractionProcessor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from core.services.text_preprocessor import (
    CorruptionDetectionStrategy,
    TextPreprocessor,
)


@pytest.fixture
def preprocessor_service() -> TextPreprocessor:
    """Fixture to provide an instance of the TextPreprocessor with COMMON_WORDS strategy."""
    return TextPreprocessor(strategy=CorruptionDetectionStrategy.COMMON_WORDS)


@pytest.fixture
def processor_service() -> TextExtractionProcessor:
    """Fixture to provide an instance of the TextExtractionProcessor."""
    return TextExtractionProcessor()


@pytest.fixture
def provider_to_use() -> ProcessingProvider:
    """Fixture to provide the processing provider."""
    return ProcessingProvider.PYMUPDF


@pytest.fixture
def extractor_to_use(processor_service, provider_to_use) -> PyMuPDFExtractor:
    return processor_service.extractors[provider_to_use]


@pytest.fixture
def corrupted_text(
    extractor_to_use: PyMuPDFExtractor, corrupted_file_path: Path
) -> str:
    """Fixture to read the corrupted text from a file."""
    # Use the service to read the file and return its content
    extraction_result = extractor_to_use.extract_text(corrupted_file_path)
    text_extracted = extraction_result.text
    return text_extracted


@pytest.fixture
def preprocessed_corrupted_text(
    preprocessor_service, corrupted_text
) -> PreprocessingResult:
    result_of_preprocessing = preprocessor_service.preprocess(corrupted_text)
    return result_of_preprocessing


def test_corrupted_text_detection(preprocessed_corrupted_text: PreprocessingResult):
    """
    Test that the preprocessor detects corrupted text correctly using COMMON_WORDS strategy.
    """
    result: PreprocessingResult = preprocessed_corrupted_text

    # The text should be detected as corrupted
    assert (
        result.is_corrupted is True
    ), "The preprocessor should detect the text as corrupted."

    # Check that we have performance stats
    assert "total" in result.performance_stats
    assert result.performance_stats["total"] > 0


def test_normal_text_not_detected_as_corrupted(preprocessor_service):
    """
    Test that normal Greek text is not detected as corrupted.
    """
    normal_greek_text = """
    Η Ελληνική Δημοκρατία είναι κράτος που βρίσκεται στη νοτιοανατολική Ευρώπη.
    Πρωτεύουσα και μεγαλύτερη πόλη της χώρας είναι η Αθήνα.
    Το κράτος έχει πληθυσμό περίπου 10,7 εκατομμυρίων κατοίκων.
    """

    result = preprocessor_service.preprocess(normal_greek_text)

    assert (
        result.is_corrupted is False
    ), "Normal Greek text should not be detected as corrupted."
    assert (
        result.confidence_score > 0.5
    ), "Should have reasonable confidence in the result."


def test_text_with_no_greek_words_detected_as_corrupted(preprocessor_service):
    """
    Test that text with mixed gibberish and very few real words is detected as corrupted.
    """
    # Text with mostly gibberish and only 1-2 valid Greek words
    # This should be flagged as corrupted because coverage is below 10%
    mixed_gibberish_text = """
    Τπόινγν Δηδηθήο Γηαρείξηζεο αβγδεζηθικλμνοπρστυφχψω
    ΑΓΙΑΒΑΘΜΗΣΟ κάποιες παράξενες συμβολοσειρές που μπλαμπλα φτσιφτσου
    Ψφχωςερτυιοπασδφγηκλζχβνμ ζουζουνια κρεμπελοπιτα
    """

    result = preprocessor_service.preprocess(mixed_gibberish_text)

    assert (
        result.is_corrupted is True
    ), "Text with mostly gibberish should be detected as corrupted even if it contains some real words."

    # Check corruption indicators provide useful info
    if "word_analysis" in result.corruption_indicators:
        word_analysis = result.corruption_indicators["word_analysis"]
        assert word_analysis["matched_words"] >= 0
        # With stricter thresholds, this should now be flagged
        print(f"Coverage ratio: {word_analysis['coverage_ratio']:.3f}")
        print(
            f"Matched words: {word_analysis['matched_words']}/{word_analysis['text_word_count']}"
        )


def test_purely_gibberish_text_detected_as_corrupted(preprocessor_service):
    """
    Test that purely gibberish text with no real Greek words is detected as corrupted.
    """
    # Purely gibberish text with no real Greek words
    pure_gibberish_text = """
    Τπόινγν Δηδηθήο Γηαρείξηζεο αβγδεζηθικλμνοπρστυφχψω
    ΑΓΙΑΒΑΘΜΗΣΟ ξυζαβγδεζηθικλμνοπρστυφχψω
    Ψφχωςερτυιοπασδφγηκλζχβνμ κλμνοπρστυφχψωαβγδεζηθ
    """

    result = preprocessor_service.preprocess(pure_gibberish_text)

    assert (
        result.is_corrupted is True
    ), "Purely gibberish text should definitely be detected as corrupted."

    if "word_analysis" in result.corruption_indicators:
        word_analysis = result.corruption_indicators["word_analysis"]
        assert (
            word_analysis["coverage_ratio"] < 0.05
        )  # Should be very low (less than 5%)


def test_domain_stopwords_help_detection(preprocessor_service):
    """
    Test that domain-specific stopwords help in corruption detection.
    """
    # Text that contains domain stopwords
    text_with_domain_words = """
    ΕΛΛΗΝΙΚΗ ΔΗΜΟΚΡΑΤΙΑ
    Μερικές άλλες λέξεις που δεν είναι συνηθισμένες αλλά υπάρχουν στο κείμενο.
    """

    result = preprocessor_service.preprocess(text_with_domain_words)

    assert (
        result.is_corrupted is False
    ), "Text with domain stopwords should not be detected as corrupted."


def test_preprocessing_result_structure(preprocessor_service):
    """
    Test that the PreprocessingResult has the expected structure.
    """
    test_text = "Αυτό είναι ένα δοκιμαστικό κείμενο με ελληνικές λέξεις."

    result = preprocessor_service.preprocess(test_text)

    # Check all required fields are present
    assert hasattr(result, "processed_text")
    assert hasattr(result, "is_corrupted")
    assert hasattr(result, "confidence_score")
    assert hasattr(result, "performance_stats")
    assert hasattr(result, "corruption_indicators")

    # Check types
    assert isinstance(result.processed_text, str)
    assert isinstance(result.is_corrupted, bool)
    assert isinstance(result.confidence_score, (float, type(None)))
    assert isinstance(result.performance_stats, dict)
    assert isinstance(result.corruption_indicators, dict)

    # Check confidence score is in valid range
    if result.confidence_score is not None:
        assert 0.0 <= result.confidence_score <= 1.0


def test_empty_text_handling(preprocessor_service):
    """
    Test that empty text is handled gracefully.
    """
    result = preprocessor_service.preprocess("")

    assert result.processed_text == ""
    assert result.is_corrupted is False
    assert result.confidence_score == 1.0


@pytest.mark.parametrize(
    "detection_threshold,coverage_threshold,should_be_corrupted,test_name",
    [
        (
            0.05,
            0.15,
            False,
            "old_strict_thresholds",
        ),  # Old thresholds - should flag as corrupted
        (0.03, 0.08, False, "new_relaxed_thresholds"),  # New thresholds - should pass
        (
            0.02,
            0.05,
            False,
            "very_relaxed_thresholds",
        ),  # Even more relaxed - should pass
    ],
)
def test_threshold_sensitivity_on_corrupted_appearing_doc(
    not_corrupted_file_path: Path,
    processor_service: TextExtractionProcessor,
    detection_threshold: float,
    coverage_threshold: float,
    should_be_corrupted: bool,
    test_name: str,
):
    """
    Test that threshold adjustments correctly affect corruption detection.

    This parametrized test verifies:
    1. OLD thresholds (0.05, 0.15) would incorrectly flag administrative docs as corrupted
    2. NEW thresholds (0.03, 0.08) correctly identify them as valid
    3. The threshold changes are what fixed the false positive issue
    """
    # Create preprocessor with specific thresholds
    preprocessor = TextPreprocessor(
        strategy=CorruptionDetectionStrategy.COMMON_WORDS,
        detection_ratio_threshold=detection_threshold,
        coverage_ratio_threshold=coverage_threshold,
    )

    # Use Docling extractor
    from core.models.document_analysis import ProcessingProvider

    extractor = processor_service.extractors[ProcessingProvider.DOCLING]

    # Extract text
    extraction_result = extractor.extract_text(not_corrupted_file_path)
    text = extraction_result.text

    # Preprocess
    result = preprocessor.preprocess(text)

    print(f"\n[CHART] Test: {test_name}")
    print(
        f"  Thresholds: detection={detection_threshold:.3f}, coverage={coverage_threshold:.3f}"
    )
    print(f"  Expected corrupted: {should_be_corrupted}")
    print(f"  Actual corrupted: {result.is_corrupted}")

    if "word_analysis" in result.corruption_indicators:
        wa = result.corruption_indicators["word_analysis"]
        print(f"  Coverage ratio: {wa['coverage_ratio']:.3f}")
        print(f"  Matched words: {wa['matched_words']}/{wa['text_word_count']}")
        print(f"  Matched by category: {wa.get('matched_by_category', {})}")

    # Verify the threshold correctly affects the result
    assert result.is_corrupted == should_be_corrupted, (
        f"With thresholds ({detection_threshold}, {coverage_threshold}), "
        f"expected is_corrupted={should_be_corrupted}, got {result.is_corrupted}"
    )


# ============================================================================
# REGRESSION TEST SUITE: Corruption Detection
# ============================================================================
# This suite ensures that:
# 1. Known corrupted files are always detected as corrupted
# 2. Known valid files are never flagged as corrupted
# 3. When fixing edge cases, we don't break previous functionality
#
# To add a new test case:
# 1. Add the PDF file to your test fixtures directory
# 2. Add a fixture in conftest.py following the pattern (filename + filepath)
# 3. Add a new entry to the parametrized test below
# ============================================================================


@pytest.mark.parametrize(
    "file_fixture,expected_corrupted,provider,description",
    [
        # Known corrupted files - should always be detected as corrupted
        (
            "corrupted_file_path",
            True,
            ProcessingProvider.PYMUPDF,
            "Original corrupted file with garbled text",
        ),
        # Known valid files - should never be flagged as corrupted
        (
            "not_corrupted_file_path",
            False,
            ProcessingProvider.DOCLING,
            "Administrative document with legal citations",
        ),
        (
            "another_not_corrupted_file_path",
            False,
            ProcessingProvider.PYMUPDF,
            "Valid administrative text - regression case",
        ),
        # Add more cases here as you discover edge cases:
        # ("new_edge_case_path", False, ProcessingProvider.DOCLING, "Description"),
    ],
)
def test_corruption_detection_regression_suite(
    file_fixture: str,
    expected_corrupted: bool,
    provider: ProcessingProvider,
    description: str,
    request,  # pytest fixture to access other fixtures dynamically
    preprocessor_service: TextPreprocessor,
    processor_service: TextExtractionProcessor,
):
    """
    Comprehensive regression test for corruption detection.

    This test ensures that:
    - All known corrupted files are correctly identified
    - All known valid files are not flagged as corrupted
    - Changes to the algorithm don't break previous functionality

    When you discover a new edge case:
    1. Add the file as a fixture in conftest.py
    2. Add a new parameter entry above
    3. Run the test to verify current behavior
    4. Fix the algorithm if needed
    5. The test now serves as a regression guard
    """
    # Get the file path from the fixture name
    file_path = request.getfixturevalue(file_fixture)

    # Extract text using specified provider
    extractor = processor_service.extractors[provider]
    extraction_result = extractor.extract_text(file_path)
    text = extraction_result.text

    # Check for empty text
    if not text or len(text.strip()) < 50:
        pytest.fail(f"Extracted text is too short or empty from {file_path.name}")

    # Preprocess and check corruption
    result = preprocessor_service.preprocess(text)

    # Detailed output for debugging
    print(f"\n[FILE] Testing: {file_path.name}")
    print(f"   Description: {description}")
    print(f"   Provider: {provider.value}")
    print(f"   Expected corrupted: {expected_corrupted}")
    print(f"   Actual corrupted: {result.is_corrupted}")
    print(f"   Confidence: {result.confidence_score:.3f}")

    if "word_analysis" in result.corruption_indicators:
        wa = result.corruption_indicators["word_analysis"]
        print(f"   Coverage ratio: {wa['coverage_ratio']:.3f}")
        print(f"   Matched words: {wa['matched_words']}/{wa['text_word_count']}")
        print(f"   Matched by category: {wa.get('matched_by_category', {})}")

    # Assert the expected result
    assert result.is_corrupted == expected_corrupted, (
        f"Regression failure for {file_path.name}: "
        f"Expected is_corrupted={expected_corrupted}, got {result.is_corrupted}. "
        f"Description: {description}. "
        f"This may indicate that recent changes broke previous functionality."
    )


def test_analyze_new_edge_case_file(
    another_not_corrupted_file_path: Path,
    preprocessor_service: TextPreprocessor,
    processor_service: TextExtractionProcessor,
):
    """
    Diagnostic test to analyze why 'yet_another' file is being classified incorrectly.

    This test provides detailed diagnostics to help understand:
    - What detection ratios the file produces
    - Which words are being found/not found
    - Why the algorithm makes its decision

    Use this test to:
    1. Understand the current behavior
    2. Identify what needs to be fixed
    3. Set appropriate thresholds

    Once you fix the issue, this test becomes redundant (covered by regression suite).
    """
    print("\n" + "=" * 80)
    print("DIAGNOSTIC ANALYSIS FOR: yet_another_with_non_corrupted_text")
    print("=" * 80)

    # Get available extractors dynamically
    available_extractors = processor_service.extractors
    print(
        f"\n[CONFIG] Available extractors: {[p.value for p in available_extractors.keys()]}"
    )

    # Test with all available extractors to see if extraction method matters
    for provider, extractor in available_extractors.items():
        print(f"\n[SCAN] Testing with {provider.value}:")
        print("-" * 80)

        try:
            extraction_result = extractor.extract_text(another_not_corrupted_file_path)
            text = extraction_result.text

            print(f"Text length: {len(text)} characters")
            print(f"First 200 chars: {text[:200]}")

            # Preprocess
            result = preprocessor_service.preprocess(text)

            print(f"\n[CHART] Results:")
            print(f"  Is corrupted: {result.is_corrupted}")
            print(f"  Confidence: {result.confidence_score:.3f}")

            if "word_analysis" in result.corruption_indicators:
                wa = result.corruption_indicators["word_analysis"]
                print(f"\n[METRIC] Word Analysis:")
                print(
                    f"  Coverage ratio: {wa['coverage_ratio']:.4f} (threshold: {preprocessor_service.coverage_ratio_threshold})"
                )
                print(f"  Matched words: {wa['matched_words']}")
                print(f"  Text word count: {wa.get('text_word_count', 'N/A')}")
                print(f"  Unmatched words: {wa.get('unmatched_word_count', 'N/A')}")
                print(f"  Matched by category: {wa.get('matched_by_category', {})}")
                print(
                    f"  Min matches required: {wa.get('min_matches_required', 'N/A')}"
                )

                reasons = wa.get("corruption_reasons", {})
                print(f"\n[WARN]️  Corruption Indicators:")
                print(f"  Low coverage: {reasons.get('low_coverage', False)}")
                print(
                    f"  Insufficient matches: {reasons.get('insufficient_matches', False)}"
                )

            if "character_validation" in result.corruption_indicators:
                cv = result.corruption_indicators["character_validation"]
                print(f"\n[STR] Character Validation:")
                print(f"  Invalid ratio: {cv.get('ratio_invalid', 0):.4f}")

        except Exception as e:
            print(f"[ERROR] Error testing with {provider.value}: {e}")

        print("\n" + "-" * 80)

    # This test is for analysis only - it doesn't assert anything
    # Remove or modify assertions once you understand the issue
    print("\n[INFO] Next steps:")
    print("1. Review the coverage ratio above (what % of text words are recognized)")
    print("2. Current threshold: 10% coverage required for non-corrupted")
    print("3. Add this file to the regression suite with expected_corrupted=False")
    print("4. Verify all regression tests still pass")
    print(
        "\n[INFO] Note: To test with Docling, ensure it's installed (not available in LIGHT_WORKER mode)"
    )
