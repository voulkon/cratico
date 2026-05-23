"""
Unit tests for LanguageDetectionService

Tests are data-driven using JSON test files for easy expansion.
Add new test cases by creating/editing JSON files in data/language_detection/

Test coverage:
- Pure Greek text detection
- Pure Latin text detection
- Mixed script detection
- Neutral (numbers/punctuation) detection
- Edge cases and boundary conditions
- Real-world search scenarios
- Search weight calculation
"""

import json
from pathlib import Path

import pytest
from core.services.language_detection_service import (
    LanguageDetectionService,
    language_detector,
)

pytestmark = pytest.mark.django_db(transaction=False)

# Define test data directory (relative to backend/core/tests/)
TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "language_detection"


def load_test_cases(test_data_dir: Path) -> list:
    """
    Load all test cases from JSON files in the test data directory.

    Returns a list of tuples: (test_id, test_case_data, category)
    """
    test_cases = []

    # Find all JSON files in the directory
    json_files = sorted(test_data_dir.glob("*.json"))

    for json_file in json_files:
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
            category = data.get("category", json_file.stem)

            for case in data.get("test_cases", []):
                test_id = f"{category}:{case['id']}"
                test_cases.append((test_id, case, category))

    return test_cases


# Load all test cases from JSON files
TEST_CASES = load_test_cases(TEST_DATA_DIR)


class TestLanguageDetection:
    """Test core language detection logic"""

    @pytest.mark.parametrize("test_id,test_case,category", TEST_CASES)
    def test_language_detection_from_json(self, test_id, test_case, category):
        """
        Test language detection using JSON test data.

        This single test method runs all test cases from all JSON files.
        To add new tests, just add new JSON files or cases to existing files.
        """
        text = test_case["text"]
        expected_language = test_case["expected_language"]
        min_confidence = test_case.get("min_confidence", 0.5)

        # Perform detection
        result = LanguageDetectionService.detect(text)

        # Assert language
        assert result.language == expected_language, (
            f"Test '{test_id}' failed: "
            f"Expected language '{expected_language}', got '{result.language}' "
            f"for text: '{text}'"
        )

        # Assert confidence
        assert result.confidence >= min_confidence, (
            f"Test '{test_id}' failed: "
            f"Expected confidence >= {min_confidence}, got {result.confidence:.2f} "
            f"for text: '{text}'"
        )

        # Check optional greek_ratio constraint
        if "min_greek_ratio" in test_case:
            min_greek_ratio = test_case["min_greek_ratio"]
            assert result.greek_ratio >= min_greek_ratio, (
                f"Test '{test_id}' failed: "
                f"Expected greek_ratio >= {min_greek_ratio}, got {result.greek_ratio:.2f} "
                f"for text: '{text}'"
            )

        # Check optional latin_ratio constraint
        if "min_latin_ratio" in test_case:
            min_latin_ratio = test_case["min_latin_ratio"]
            assert result.latin_ratio >= min_latin_ratio, (
                f"Test '{test_id}' failed: "
                f"Expected latin_ratio >= {min_latin_ratio}, got {result.latin_ratio:.2f} "
                f"for text: '{text}'"
            )


class TestSearchWeights:
    """Test search weight calculation for PostgreSQL FTS"""

    @pytest.mark.parametrize(
        "test_id,test_case,category",
        [tc for tc in TEST_CASES if "expected_weights" in tc[1]],
    )
    def test_search_weights_from_json(self, test_id, test_case, category):
        """
        Test search weight calculation using JSON test data.

        Only runs on test cases that have 'expected_weights' defined.
        """
        text = test_case["text"]
        expected_weights = test_case["expected_weights"]

        # Get weights
        greek_weight, latin_weight = LanguageDetectionService.get_search_weights(text)

        # Assert weights
        assert [greek_weight, latin_weight] == expected_weights, (
            f"Test '{test_id}' failed: "
            f"Expected weights {expected_weights}, got [{greek_weight}, {latin_weight}] "
            f"for text: '{text}'"
        )

    def test_greek_query_prioritizes_greek_fields(self):
        """Greek queries should prioritize Greek fields (A) over Latin (C)"""
        greek_weight, latin_weight = LanguageDetectionService.get_search_weights(
            "ΔΗΜΟΣ"
        )
        assert greek_weight == "A"
        assert latin_weight == "C"

    def test_latin_query_prioritizes_latin_fields(self):
        """Latin queries should prioritize Latin fields (A) over Greek (C)"""
        greek_weight, latin_weight = LanguageDetectionService.get_search_weights(
            "Athens"
        )
        assert greek_weight == "C"
        assert latin_weight == "A"

    def test_mixed_query_balanced_weights(self):
        """Mixed queries should have balanced weights (A, B)"""
        greek_weight, latin_weight = LanguageDetectionService.get_search_weights(
            "ΔΗΜΟΣ Athens"
        )
        assert greek_weight == "A"
        assert latin_weight == "B"

    def test_neutral_query_balanced_weights(self):
        """Neutral queries (numbers) should have balanced weights"""
        greek_weight, latin_weight = LanguageDetectionService.get_search_weights(
            "123456"
        )
        assert greek_weight == "A"
        assert latin_weight == "B"


class TestSearchRankWeights:
    """Test Django SearchRank weight calculation"""

    def test_greek_query_rank_weights(self):
        """Greek queries should favor A fields (Greek)"""
        weights = LanguageDetectionService.get_search_rank_weights("ΔΗΜΟΣ")
        assert len(weights) == 4  # [D, C, B, A]
        assert weights[3] == 1.0  # A field gets highest weight
        assert weights[1] < weights[3]  # C field gets lower weight

    def test_latin_query_rank_weights(self):
        """Latin queries should favor C fields (Latin)"""
        weights = LanguageDetectionService.get_search_rank_weights("Athens")
        assert len(weights) == 4
        assert weights[1] == 1.0  # C field (Latin) gets highest weight

    def test_mixed_query_rank_weights(self):
        """Mixed queries should have balanced weights"""
        weights = LanguageDetectionService.get_search_rank_weights("ΔΗΜΟΣ Athens")
        assert len(weights) == 4
        # Should have default balanced weights
        assert weights[3] > weights[1]  # A > C


class TestHelperMethods:
    """Test convenience helper methods"""

    def test_is_greek_true(self):
        """is_greek() should return True for Greek text"""
        assert LanguageDetectionService.is_greek("ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ") is True

    def test_is_greek_false(self):
        """is_greek() should return False for non-Greek text"""
        assert LanguageDetectionService.is_greek("Athens") is False
        assert LanguageDetectionService.is_greek("ΔΗΜΟΣ Athens") is False

    def test_is_latin_true(self):
        """is_latin() should return True for Latin text"""
        assert LanguageDetectionService.is_latin("Municipality of Athens") is True

    def test_is_latin_false(self):
        """is_latin() should return False for non-Latin text"""
        assert LanguageDetectionService.is_latin("ΔΗΜΟΣ") is False
        assert LanguageDetectionService.is_latin("ΔΗΜΟΣ Athens") is False

    def test_is_mixed_true(self):
        """is_mixed() should return True for mixed text"""
        assert LanguageDetectionService.is_mixed("ΔΗΜΟΣ Athens") is True

    def test_is_mixed_false(self):
        """is_mixed() should return False for pure text"""
        assert LanguageDetectionService.is_mixed("ΔΗΜΟΣ") is False
        assert LanguageDetectionService.is_mixed("Athens") is False


class TestResultObject:
    """Test LanguageDetectionResult dataclass"""

    def test_result_attributes(self):
        """Result should have all expected attributes"""
        result = LanguageDetectionService.detect("ΔΗΜΟΣ")

        assert hasattr(result, "language")
        assert hasattr(result, "confidence")
        assert hasattr(result, "greek_ratio")
        assert hasattr(result, "latin_ratio")
        assert hasattr(result, "total_chars")

    def test_result_string_representation(self):
        """Result should have readable string representation"""
        result = LanguageDetectionService.detect("ΔΗΜΟΣ")
        str_repr = str(result)

        assert "Language:" in str_repr
        assert "confidence:" in str_repr
        assert "greek:" in str_repr
        assert "latin:" in str_repr

    def test_result_ratios_sum_to_one(self):
        """Greek ratio + Latin ratio should equal 1.0 for non-neutral text"""
        result = LanguageDetectionService.detect("ΔΗΜΟΣ Athens")

        if result.total_chars > 0:
            # Allow small floating point error
            total = result.greek_ratio + result.latin_ratio
            assert abs(total - 1.0) < 0.0001


class TestSingletonInstance:
    """Test the convenience singleton instance"""

    def test_singleton_exists(self):
        """language_detector singleton should exist"""
        assert language_detector is not None

    def test_singleton_detect(self):
        """Singleton should have detect method"""
        result = language_detector.detect("ΔΗΜΟΣ")
        assert result.language == "greek"


class TestPerformance:
    """Test performance with large datasets"""

    def test_performance_many_detections(self):
        """Should handle many detections efficiently"""
        import time

        test_texts = [
            "ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ",
            "Municipality of Athens",
            "ΔΗΜΟΣ Athens",
            "123456789",
            "ΥΠΟΥΡΓΕΙΟ",
            "Ministry",
        ] * 1000  # 6000 detections

        start = time.time()
        for text in test_texts:
            LanguageDetectionService.detect(text)
        elapsed = time.time() - start

        assert (
            elapsed < 1.0
        ), f"Performance issue: {elapsed:.2f}s for {len(test_texts)} detections"

    def test_performance_long_text(self):
        """Should handle long text efficiently"""
        import time

        # Very long Greek text
        long_text = "ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ " * 1000

        start = time.time()
        result = LanguageDetectionService.detect(long_text)
        elapsed = time.time() - start

        assert result.language == "greek"
        assert elapsed < 0.1, f"Performance issue with long text: {elapsed:.2f}s"


class TestEdgeCasesAdditional:
    """Additional edge case tests not covered by JSON"""

    def test_unicode_normalization(self):
        """Should handle different Unicode normalizations"""
        # These might be visually identical but different Unicode
        text1 = "Αθήνα"  # Composed form
        text2 = "Αθήνα"  # Decomposed form (if different)

        result1 = LanguageDetectionService.detect(text1)
        result2 = LanguageDetectionService.detect(text2)

        # Both should be detected as Greek
        assert result1.language == "greek"
        assert result2.language == "greek"

    def test_consistency_across_calls(self):
        """Multiple calls with same input should give same result"""
        text = "ΔΗΜΟΣ ΑΘΗΝΑΙΩΝ"

        result1 = LanguageDetectionService.detect(text)
        result2 = LanguageDetectionService.detect(text)
        result3 = LanguageDetectionService.detect(text)

        assert result1.language == result2.language == result3.language
        assert result1.confidence == result2.confidence == result3.confidence
        assert result1.greek_ratio == result2.greek_ratio == result3.greek_ratio


# Summary test to print statistics
class TestSummary:
    """Print test summary statistics"""

    def test_print_test_summary(self):
        """Print summary of test coverage"""
        print("\n" + "=" * 70)
        print("LANGUAGE DETECTION TEST SUMMARY")
        print("=" * 70)

        # Count test cases by category
        categories = {}
        for test_id, test_case, category in TEST_CASES:
            categories[category] = categories.get(category, 0) + 1

        print(f"\nTotal test cases loaded from JSON: {len(TEST_CASES)}")
        print(f"Test data directory: {TEST_DATA_DIR}")
        print("\nTest cases by category:")
        for category, count in sorted(categories.items()):
            print(f"  - {category}: {count} cases")

        print("\nJSON test files:")
        for json_file in sorted(TEST_DATA_DIR.glob("*.json")):
            print(f"  - {json_file.name}")

        print("\n" + "=" * 70)
        print("To add new test cases:")
        print(
            "  1. Edit existing JSON files in: backend/core/tests/data/language_detection/"
        )
        print("  2. Or create new JSON files following the same structure")
        print("  3. Tests will automatically pick up new cases")
        print("=" * 70 + "\n")
