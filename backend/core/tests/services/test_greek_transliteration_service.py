"""
Unit tests for Greek Transliteration Service

Tests are data-driven using JSON test files for easy expansion.
Add new test cases by creating/editing JSON files in data/transliteration/

Test coverage:
- Basic transliteration (Latin to Greek)
- Special combinations (TH, CH, PH, PS)
- Single letter mappings
- Complex words
- Edge cases
- Detection (needs_transliteration)
- Query transliteration
"""

import json
from pathlib import Path

import pytest
from core.services.transliteration import GreekTransliterationService

pytestmark = pytest.mark.django_db(transaction=False)

# Define test data directory (relative to backend/core/tests/)
TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "transliteration" / "greek"


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


class TestTransliteration:
    """Test core transliteration logic using JSON data"""

    @pytest.mark.parametrize(
        "test_id,test_case,category",
        [
            tc
            for tc in TEST_CASES
            if "expected" in tc[1]
            and tc[1].get("category") != "needs_transliteration_detection"
        ],
    )
    def test_transliteration_from_json(self, test_id, test_case, category):
        """
        Test transliteration using JSON test data.

        This single test method runs all transliteration test cases from all JSON files.
        To add new tests, just add new JSON files or cases to existing files.
        """
        input_text = test_case["input"]
        expected_output = test_case["expected"]

        # Perform transliteration
        result = GreekTransliterationService.transliterate(input_text)

        # Assert output
        assert result == expected_output, (
            f"Test '{test_id}' failed: "
            f"Expected '{expected_output}', got '{result}' "
            f"for input: '{input_text}'"
        )

    def test_preserve_original_flag(self):
        """Test preserve_original flag (not in JSON)"""
        result = GreekTransliterationService.transliterate(
            "DHMOS", preserve_original=True
        )
        assert result == "DHMOS"

    def test_handles_none(self):
        """Test handling of None input"""
        result = GreekTransliterationService.transliterate(None)
        assert result is None


class TestNeedsTransliteration:
    """Test detection of whether text needs transliteration"""

    @pytest.mark.parametrize(
        "test_id,test_case,category",
        [tc for tc in TEST_CASES if "expected_needs_transliteration" in tc[1]],
    )
    def test_needs_transliteration_from_json(self, test_id, test_case, category):
        """
        Test needs_transliteration detection using JSON test data.
        """
        input_text = test_case["input"]
        expected_needs = test_case["expected_needs_transliteration"]

        # Check if needs transliteration
        result = GreekTransliterationService.needs_transliteration(input_text)

        # Assert
        assert result == expected_needs, (
            f"Test '{test_id}' failed: "
            f"Expected needs_transliteration={expected_needs}, got {result} "
            f"for input: '{input_text}'"
        )


class TestTransliterateQuery:
    """Test smart query transliteration"""

    @pytest.mark.parametrize(
        "test_id,test_case,category",
        [tc for tc in TEST_CASES if tc[2] == "query_transliteration"],
    )
    def test_transliterate_query_from_json(self, test_id, test_case, category):
        """
        Test transliterate_query using JSON test data.
        """
        input_text = test_case["input"]
        expected_output = test_case["expected"]

        # Perform smart query transliteration
        result = GreekTransliterationService.transliterate_query(input_text)

        # Assert
        assert result == expected_output, (
            f"Test '{test_id}' failed: "
            f"Expected '{expected_output}', got '{result}' "
            f"for input: '{input_text}'"
        )


class TestPerformance:
    """Performance tests for transliteration"""

    def test_transliteration_speed(self):
        """Test that transliteration is fast enough for real-time search"""
        import time

        test_queries = [
            "DHMOS",
            "YPOURGEIA",
            "PERIFEREIA",
            "GENETIKI GRAMMATEIA",
            "NOMARCHIA",
            "DHMOTIKI EPICHEIRISI",
        ]

        start = time.time()
        for _ in range(1000):
            for query in test_queries:
                GreekTransliterationService.transliterate_query(query)
        elapsed = time.time() - start

        # Should be very fast (translating 6000 queries should take < 1 second)
        assert (
            elapsed < 1.0
        ), f"Transliteration too slow: {elapsed:.2f}s for 6000 queries"


class TestSummary:
    """Print test summary statistics"""

    def test_print_test_summary(self):
        """Print summary of test coverage"""
        print("\n" + "=" * 70)
        print("GREEK TRANSLITERATION TEST SUMMARY")
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
        print("  1. Edit existing JSON files in: core/tests/data/transliteration/")
        print("  2. Or create new JSON files following the same structure")
        print("  3. Tests will automatically pick up new cases")
        print("=" * 70 + "\n")
