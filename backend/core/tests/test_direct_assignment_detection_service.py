"""
Unit tests for DirectAssignmentDetectionService

Tests cover:
- Core classification logic (type, amount, threshold)
- Edge cases (null values, boundary conditions)
- Bulk classification
- Query helpers
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from core.models.decision_classification import DirectAssignmentDetectionMethod
from core.services.direct_assignment_detection_service import classification_service

pytestmark = pytest.mark.django_db

# Define test data directory (relative to this file)
TEST_DATA_DIR = Path(__file__).parent / "data" / "direct_assignment_text_patterns"


def load_text_detection_test_cases(test_data_dir: Path) -> list:
    """
    Load all test cases from JSON files in test_data_dir.

    Recursively scans for .json files and converts them to pytest.param objects.
    Each JSON file should have:
    - id: test case identifier (required)
    - ada: decision ADA (optional - for real decision reference)
    - text_content: the text to test for direct assignment detection
    - should_detect: boolean indicating if direct assignment should be detected
    - notes: optional description of the test case
    """
    test_cases = []

    for json_file in sorted(test_data_dir.rglob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Get optional ADA (None if not present)
        ada = data.get("ada", None)

        test_case = pytest.param(
            data["text_content"],
            data["should_detect"],
            ada,  # Include ADA as third parameter
            id=data.get(
                "id", json_file.stem
            ),  # Use ID from JSON or filename as fallback
        )
        test_cases.append(test_case)

    return test_cases


# Load all test cases from JSON files
TEXT_DETECTION_TEST_CASES = load_text_detection_test_cases(TEST_DATA_DIR)


class TestClassificationLogic:
    """Test core classification algorithm"""

    def test_classify_direct_assignment_valid(self):
        """Should classify as direct assignment when type=Δ.1 and amount < threshold"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)

        # Create amount using DecisionAmountField (how the system actually stores amounts)
        DecisionAmountFieldFactory(
            decision=decision, amount=Decimal("30000.00")  # Below €37,200 threshold
        )

        result = classification_service.classify_decision(decision)

        assert result["is_direct_assignment"] is True
        assert result["confidence"] == 1.0
        assert result["amount"] == Decimal("30000.00")
        assert "Δ.1" in result["reason"]
        assert result["detection_method"] == DirectAssignmentDetectionMethod.METADATA

    @pytest.mark.parametrize(
        "text_content,should_detect,ada",
        TEXT_DETECTION_TEST_CASES,
    )
    def test_classify_direct_assignment_text_detection(
        self, text_content, should_detect, ada
    ):
        """
        Test direct assignment detection based on text content patterns.

        Test cases are loaded from JSON files in data/direct_assignment_text_patterns/

        Each test case includes:
        - text_content: The Greek text to analyze
        - should_detect: Whether direct assignment should be detected
        - ada: (Optional) Real decision ADA for reference

        This verifies that the service correctly identifies direct assignment
        phrases in Greek text, handling various spellings and formats.
        """
        from conftest import (
            DecisionFactory,
            DecisionTypeFactory,
            DocumentExtractionFactory,
        )

        # Create decision WITHOUT Δ.1 type (forcing text-only detection)
        decision_type = DecisionTypeFactory(uid="Β.1.1")
        decision = DecisionFactory(
            decision_type=decision_type,
            ada=ada if ada else "TEST-ADA",  # Use actual ADA if provided
        )

        # Create text extraction
        DocumentExtractionFactory(decision=decision, raw_text=text_content)

        result = classification_service.classify_decision(decision)

        if should_detect:
            assert (
                result["is_direct_assignment"] is True
            ), f"Expected to detect direct assignment in text: '{text_content}'" + (
                f" (ADA: {ada})" if ada else ""
            )
            assert result["detection_method"] == DirectAssignmentDetectionMethod.TEXT
            assert result["confidence"] < 1.0  # Lower confidence without metadata
        else:
            assert (
                result["is_direct_assignment"] is False
            ), f"Should NOT detect direct assignment in text: '{text_content}'" + (
                f" (ADA: {ada})" if ada else ""
            )
            assert result["detection_method"] == DirectAssignmentDetectionMethod.NONE

    def test_classify_direct_assignment_both_methods(self):
        """Should detect via BOTH when metadata AND text confirm"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
            DocumentExtractionFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)

        # Metadata confirms: correct type and amount
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("25000.00"))

        # Text also confirms
        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης προμήθειας υλικών"
        )

        result = classification_service.classify_decision(decision)

        assert result["is_direct_assignment"] is True
        assert result["detection_method"] == DirectAssignmentDetectionMethod.BOTH
        assert result["confidence"] == 1.0
        assert "text confirmation" in result["reason"]

    def test_classify_text_only_no_extraction(self):
        """Should handle cases where there's no text extraction"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)

        DecisionAmountFieldFactory(decision=decision, amount=Decimal("20000.00"))

        # No DocumentExtraction created
        result = classification_service.classify_decision(decision)

        # Should still work based on metadata
        assert result["is_direct_assignment"] is True
        assert result["detection_method"] == DirectAssignmentDetectionMethod.METADATA

    def test_classify_text_indicates_but_amount_too_high(self):
        """Should use TEXT method when text indicates but amount is above threshold"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
            DocumentExtractionFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)

        # Amount above threshold
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("50000.00"))

        # But text indicates direct assignment
        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης για μεγάλο έργο"
        )

        result = classification_service.classify_decision(decision)

        # Should still classify as direct assignment but with lower confidence
        assert result["is_direct_assignment"] is True
        assert result["detection_method"] == DirectAssignmentDetectionMethod.TEXT
        assert result["confidence"] == 0.6  # Lower confidence due to conflict
        assert "metadata shows amount" in result["reason"]

    def test_classify_no_type_but_text_indicates(self):
        """Should detect via text even without decision type"""
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(decision_type=None)

        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης καθαρισμού"
        )

        result = classification_service.classify_decision(decision)

        assert result["is_direct_assignment"] is True
        assert result["detection_method"] == DirectAssignmentDetectionMethod.TEXT
        assert result["confidence"] == 0.8  # Lower confidence without metadata


class TestClassifyAndSave:
    """Test classification with database persistence"""

    def test_classify_and_save_metadata_detection(self):
        """Should save classification with METADATA detection method"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("25000.00"))

        classification = classification_service.classify_and_save(decision)

        assert classification.decision == decision
        assert classification.is_direct_assignment is True
        assert (
            classification.detection_method == DirectAssignmentDetectionMethod.METADATA
        )
        assert classification.classifier_version == "v2.0"
        assert classification.classified_at is not None

    def test_classify_and_save_text_detection(self):
        """Should save classification with TEXT detection method"""
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(decision_type=None)
        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης υπηρεσιών"
        )

        classification = classification_service.classify_and_save(decision)

        assert classification.is_direct_assignment is True
        assert classification.detection_method == DirectAssignmentDetectionMethod.TEXT

    def test_classify_and_save_both_methods(self):
        """Should save classification with BOTH detection method"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
            DocumentExtractionFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("25000.00"))
        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης"
        )

        classification = classification_service.classify_and_save(decision)

        assert classification.is_direct_assignment is True
        assert classification.detection_method == DirectAssignmentDetectionMethod.BOTH

    def test_classify_and_save_updates_existing(self):
        """Should update existing classification when called again"""
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionFactory,
            DecisionTypeFactory,
            DocumentExtractionFactory,
        )

        decision_type = DecisionTypeFactory(uid="Δ.1")
        decision = DecisionFactory(decision_type=decision_type)
        DecisionAmountFieldFactory(decision=decision, amount=Decimal("25000.00"))

        # First save - metadata only
        first = classification_service.classify_and_save(decision)
        first_id = first.decision_id
        assert first.detection_method == DirectAssignmentDetectionMethod.METADATA

        # Add text extraction
        DocumentExtractionFactory(
            decision=decision, raw_text="Απόφαση απευθείας ανάθεσης"
        )

        # Re-classify
        second = classification_service.classify_and_save(decision)

        # Should update same record
        assert second.decision_id == first_id
        assert second.detection_method == DirectAssignmentDetectionMethod.BOTH


# Commented out tests - can be enabled if needed
#     def test_classify_not_direct_assignment_wrong_type(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify as direct assignment if type is not Δ.1"""
#         decision_type = decision_type_factory(uid="Β.1.1")  # Wrong type
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("20000.00")  # Even though amount is low
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False
#         assert result['confidence'] == 1.0
#         assert "Not Δ.1 type" in result['reason']

#     def test_classify_not_direct_assignment_above_threshold(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify as direct assignment if amount >= threshold"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("40000.00")  # Above €37,200 threshold
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False
#         assert result['confidence'] == 1.0
#         assert "threshold" in result['reason'].lower()

#     def test_classify_threshold_boundary_below(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should classify as direct assignment at €37,199.99 (just below threshold)"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("37199.99")  # Just below threshold
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is True

#     def test_classify_threshold_boundary_at(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify as direct assignment at exactly €37,200"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("37200.00")  # Exactly at threshold
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False

#     def test_classify_no_decision_type(
#         self,
#         decision_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify if decision has no type"""
#         decision = decision_factory(
#             decision_type=None
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("20000.00")
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False
#         assert "No decision type" in result['reason']

#     def test_classify_no_amount(
#         self,
#         decision_factory,
#         decision_type_factory
#     ):
#         """Should NOT classify if decision has no amount"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         # Create decision without any DecisionAmountField (no amounts at all)
#         decision = decision_factory(
#             decision_type=decision_type
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False
#         assert result['confidence'] == 0.5  # Low confidence
#         assert "No valid amount" in result['reason']

#     def test_classify_zero_amount(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify if amount is zero"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create zero amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("0.00")
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False
#         assert "No valid amount" in result['reason']

#     def test_classify_negative_amount(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT classify if amount is negative"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create negative amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("-1000.00")
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is False


# class TestClassifyAndSave:
#     """Test classification with database persistence"""

#     def test_classify_and_save_creates_new(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should create new DecisionClassification record"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("25000.00")
#         )

#         assert not DecisionClassification.objects.filter(decision=decision).exists()

#         classification = classification_service.classify_and_save(decision)

#         assert classification.decision == decision
#         assert classification.is_direct_assignment is True
#         assert classification.classifier_version == "v1.0"
#         assert classification.classified_at is not None

#     def test_classify_and_save_updates_existing(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should update existing DecisionClassification (idempotency)"""
#         from core.models.entities import DecisionAmountField

#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         amount_field = decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("25000.00")
#         )

#         # Create initial classification
#         first_classification = classification_service.classify_and_save(decision)
#         first_id = first_classification.id
#         first_time = first_classification.classified_at

#         # Update the decision amount to be non-direct assignment
#         amount_field.amount = Decimal("50000.00")  # Above threshold
#         amount_field.save()

#         # Re-classify
#         second_classification = classification_service.classify_and_save(decision)

#         # Should update same record, not create new one
#         assert second_classification.id == first_id
#         assert second_classification.is_direct_assignment is False
#         assert second_classification.classified_at >= first_time

#     def test_classify_and_save_non_direct_assignment(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should save non-direct assignment classification"""
#         decision_type = decision_type_factory(uid="Β.1.1")  # Wrong type
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("10000.00")
#         )

#         classification = classification_service.classify_and_save(decision)

#         assert classification.is_direct_assignment is False


# class TestBulkClassification:
#     """Test bulk classification operations"""

#     def test_bulk_classify_mixed_results(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should correctly classify a mix of decisions"""
#         decision_type_d1 = decision_type_factory(uid="Δ.1")
#         decision_type_other = decision_type_factory(uid="Β.1.1")

#         # Create 3 direct assignments
#         for _ in range(3):
#             decision = decision_factory(decision_type=decision_type_d1)
#             decision_amount_field_factory(
#                 decision=decision,
#                 amount=Decimal("20000.00")
#             )

#         # Create 2 non-direct assignments (wrong type)
#         for _ in range(2):
#             decision = decision_factory(decision_type=decision_type_other)
#             decision_amount_field_factory(
#                 decision=decision,
#                 amount=Decimal("20000.00")
#             )

#         # Create 2 non-direct assignments (above threshold)
#         for _ in range(2):
#             decision = decision_factory(decision_type=decision_type_d1)
#             decision_amount_field_factory(
#                 decision=decision,
#                 amount=Decimal("50000.00")
#             )

#         from core.models.decisions import Decision
#         stats = classification_service.bulk_classify(Decision.objects.all())

#         assert stats['total_processed'] == 7
#         assert stats['direct_assignments'] == 3
#         assert stats['non_direct_assignments'] == 4
#         assert stats['created'] == 7
#         assert stats['updated'] == 0
#         assert stats['errors'] == 0

#     def test_bulk_classify_updates_existing(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should update existing classifications"""
#         from core.models.entities import DecisionAmountField

#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         amount_field = decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("25000.00")
#         )

#         # Create initial classification
#         classification_service.classify_and_save(decision)

#         # Change decision amount
#         amount_field.amount = Decimal("50000.00")
#         amount_field.save()

#         # Bulk classify should update
#         from core.models.decisions import Decision
#         stats = classification_service.bulk_classify(Decision.objects.filter(id=decision.id))

#         assert stats['updated'] == 1
#         assert stats['created'] == 0

#         # Verify update
#         classification = DecisionClassification.objects.get(decision=decision)
#         assert classification.is_direct_assignment is False

#     def test_bulk_classify_empty_queryset(self):
#         """Should handle empty queryset gracefully"""
#         from core.models.decisions import Decision
#         stats = classification_service.bulk_classify(Decision.objects.none())

#         assert stats['total_processed'] == 0
#         assert stats['direct_assignments'] == 0

#     def test_bulk_classify_batch_processing(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should process decisions in batches"""
#         decision_type = decision_type_factory(uid="Δ.1")

#         # Create 150 decisions (more than one batch)
#         for _ in range(150):
#             decision = decision_factory(decision_type=decision_type)
#             decision_amount_field_factory(
#                 decision=decision,
#                 amount=Decimal("20000.00")
#             )

#         from core.models.decisions import Decision
#         stats = classification_service.bulk_classify(
#             Decision.objects.all(),
#             batch_size=50
#         )

#         assert stats['total_processed'] == 150
#         assert stats['direct_assignments'] == 150
#         assert DecisionClassification.objects.count() == 150


# class TestQueryHelpers:
#     """Test helper methods for finding unclassified decisions"""

#     def test_get_unclassified_decisions(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should return decisions without classification"""
#         decision_type = decision_type_factory(uid="Δ.1")

#         # Create classified decision
#         classified_decision = decision_factory(
#             decision_type=decision_type
#         )
#         decision_amount_field_factory(
#             decision=classified_decision,
#             amount=Decimal("20000.00")
#         )
#         classification_service.classify_and_save(classified_decision)

#         # Create unclassified decisions
#         unclassified_1 = decision_factory(
#             decision_type=decision_type
#         )
#         decision_amount_field_factory(
#             decision=unclassified_1,
#             amount=Decimal("15000.00")
#         )
#         unclassified_2 = decision_factory(
#             decision_type=decision_type
#         )
#         decision_amount_field_factory(
#             decision=unclassified_2,
#             amount=Decimal("10000.00")
#         )

#         unclassified = classification_service.get_unclassified_decisions()
#         unclassified_ids = list(unclassified.values_list('id', flat=True))

#         assert unclassified_1.id in unclassified_ids
#         assert unclassified_2.id in unclassified_ids
#         assert classified_decision.id not in unclassified_ids

#     def test_get_unclassified_decisions_with_limit(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should respect limit parameter"""
#         decision_type = decision_type_factory(uid="Δ.1")

#         # Create 5 unclassified decisions
#         for _ in range(5):
#             decision = decision_factory(decision_type=decision_type)
#             decision_amount_field_factory(
#                 decision=decision,
#                 amount=Decimal("15000.00")
#             )

#         unclassified = classification_service.get_unclassified_decisions(limit=3)

#         assert unclassified.count() == 3

#     def test_get_outdated_classifications(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should return decisions with outdated classifier version"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("20000.00")
#         )

#         # Create classification with old version
#         DecisionClassification.objects.create(
#             decision=decision,
#             is_direct_assignment=True,
#             classifier_version="v0.9"  # Old version
#         )

#         outdated = classification_service.get_outdated_classifications()
#         outdated_ids = list(outdated.values_list('id', flat=True))

#         assert decision.id in outdated_ids

#     def test_get_outdated_classifications_excludes_current(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should NOT return decisions with current classifier version"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("20000.00")
#         )

#         # Classify with current version
#         classification_service.classify_and_save(decision)

#         outdated = classification_service.get_outdated_classifications()
#         outdated_ids = list(outdated.values_list('id', flat=True))

#         assert decision.id not in outdated_ids


# class TestEdgeCases:
#     """Test edge cases and error conditions"""

#     def test_classify_very_small_amount(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should classify decisions with very small amounts"""
#         decision_type = decision_type_factory(uid="Δ.1")
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create very small amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("0.01")  # 1 cent
#         )

#         result = classification_service.classify_decision(decision)

#         assert result['is_direct_assignment'] is True

#     def test_classify_exact_threshold_variations(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Test variations around the exact threshold"""
#         decision_type = decision_type_factory(uid="Δ.1")

#         # Just below
#         d1 = decision_factory(decision_type=decision_type)
#         decision_amount_field_factory(decision=d1, amount=Decimal("37199.99"))
#         assert classification_service.classify_decision(d1)['is_direct_assignment'] is True

#         # Exactly at
#         d2 = decision_factory(decision_type=decision_type)
#         decision_amount_field_factory(decision=d2, amount=Decimal("37200.00"))
#         assert classification_service.classify_decision(d2)['is_direct_assignment'] is False

#         # Just above
#         d3 = decision_factory(decision_type=decision_type)
#         decision_amount_field_factory(decision=d3, amount=Decimal("37200.01"))
#         assert classification_service.classify_decision(d3)['is_direct_assignment'] is False

#     def test_classify_with_case_sensitive_type(
#         self,
#         decision_factory,
#         decision_type_factory,
#         decision_amount_field_factory
#     ):
#         """Should match decision type case-sensitively"""
#         decision_type = decision_type_factory(uid="δ.1")  # Lowercase delta
#         decision = decision_factory(
#             decision_type=decision_type
#         )
#         # Create amount using DecisionAmountField
#         decision_amount_field_factory(
#             decision=decision,
#             amount=Decimal("20000.00")
#         )

#         result = classification_service.classify_decision(decision)

#         # Should NOT match (case sensitive)
#         assert result['is_direct_assignment'] is False
#         assert "Not Δ.1 type" in result['reason']
