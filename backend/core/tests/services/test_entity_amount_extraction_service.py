"""
Unit tests for EntityAmountExtractionService

Tests the single source of truth for extracting:
- AFM entities (sponsors, grantees, contractors, persons, etc.)
- Amounts (with VAT, without VAT, award amounts, etc.)

Tests cover:
- Extraction with counterparts (person field populated)
- Extraction without counterparts (empty person array)
- Edge cases (missing fields, invalid AFMs, etc.)
- Amount and entity linking
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from core.models.entities import DecisionAmountField, DecisionEntityRelationship
from core.services.entity_amount_extraction_service import (
    ExtractionResult,
    extract_entities_and_amounts,
)

pytestmark = pytest.mark.django_db

# Define test data directory (relative to this file)
TEST_DATA_DIR = Path(__file__).parent.parent / "data" / "afm_test_patterns" / "extraction"


def load_extraction_test_cases(test_data_dir: Path) -> list:
    """
    Load all test cases from JSON files in test_data_dir.

    Recursively scans for .json files and converts them to pytest.param objects.
    Each JSON file should have:
    - id: test case identifier
    - ada: decision ADA
    - extra_field_values_json: the decision data
    - expected: dict with 'entities' and 'amounts' counts
                  optionally 'total_amount' (float) to verify sum of amounts
    """
    test_cases = []

    for json_file in sorted(test_data_dir.rglob("*.json")):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Skip files that aren't extraction test cases (e.g. text sidecars)
        if "expected" not in data:
            continue

        # Get optional total_amount (None if not present)
        expected_total_amount = data["expected"].get("total_amount", None)

        test_case = pytest.param(
            data["ada"],
            data["extra_field_values_json"],
            data["expected"]["entities"],
            data["expected"]["amounts"],
            expected_total_amount,  # Will be None if not in JSON
            id=data.get("id", json_file.stem),  # Use filename as fallback ID
        )
        test_cases.append(test_case)

    return test_cases


# Load all test cases from JSON files
EXTRACTION_TEST_CASES = load_extraction_test_cases(TEST_DATA_DIR)


class TestEntityAmountExtractionService:
    """Test the unified entity and amount extraction service"""

    @pytest.mark.parametrize(
        "ada,extra_field_values_json,expected_entities,expected_amounts,expected_total_amount",
        EXTRACTION_TEST_CASES,
        # No ids parameter needed - they're embedded in pytest.param() from JSON files
    )
    def test_extract_from_real_decisions(
        self,
        ada,
        extra_field_values_json,
        expected_entities,
        expected_amounts,
        expected_total_amount,
    ):
        """
        Test extraction on real decision data from Diavgeia.

        Test cases are loaded from JSON files in data/afm_test_patterns/extraction/

        This verifies that the service correctly extracts:
        - Entities from person[] arrays and other entity fields
        - Amounts from awardAmount, expenseAmount, and other amount fields
        - Links amounts to entities when both exist
        - Optionally verifies total amount sum (if specified in test case)
        """
        from conftest import DecisionFactory

        # Create a minimal decision with just the essential fields
        decision = DecisionFactory(
            ada=ada, extra_field_values_json=extra_field_values_json
        )

        # Extract using the convenience function
        result = extract_entities_and_amounts(decision, save_to_db=True)

        # Verify the result object
        assert isinstance(result, ExtractionResult)
        assert result.decision_ada == ada
        assert result.had_extractable_content is True
        assert result.entities_found == expected_entities
        assert result.entities_created == expected_entities
        assert result.amounts_found == expected_amounts
        assert result.amounts_created == expected_amounts
        assert len(result.errors) == 0

        # Verify database persistence
        actual_entities = DecisionEntityRelationship.objects.filter(
            decision=decision
        ).count()
        actual_amounts = DecisionAmountField.objects.filter(decision=decision).count()

        # Verify linking: when entities and amounts exist, they should be linked
        # This handles both patterns:
        # 1. Numbered pattern: sponsor[0].expenseAmount → sponsor[0]
        # 2. Direct assignment: person[0] + awardAmount → linked
        if actual_entities > 0 and actual_amounts > 0:
            linked_amounts = DecisionAmountField.objects.filter(
                decision=decision, associated_relationship__isnull=False
            ).count()

            # All amounts should be linked when entities are present
            assert (
                linked_amounts == actual_amounts
            ), f"Expected all {actual_amounts} amounts to be linked to entities, but only {linked_amounts} were linked"

        assert (
            actual_entities == expected_entities
        ), f"Expected {expected_entities} entities, found {actual_entities}"
        assert (
            actual_amounts == expected_amounts
        ), f"Expected {expected_amounts} amounts, found {actual_amounts}"

        # Optionally verify total amount sum (only if specified in test case)
        if expected_total_amount is not None:
            from django.db.models import Sum

            total = DecisionAmountField.objects.filter(decision=decision).aggregate(
                total=Sum("amount")
            )["total"]

            assert total is not None, "Expected amounts but got None"
            assert abs(total - Decimal(str(expected_total_amount))) < Decimal(
                "0.01"
            ), f"Expected total amount {expected_total_amount}, found {total}"

    # def test_extract_with_counterpart_detailed(self):
    #     """
    #     Detailed test for extraction with counterpart.

    #     Verifies:
    #     - Entity is created with correct AFM and name
    #     - Amount is extracted with correct value and currency
    #     - Entity and amount are linked together
    #     """
    #     decision = DecisionFactory(
    #         ada="Ρ5ΟΓΩΕ6-Ι41",
    #         extra_field_values_json={
    #             "person": [{
    #                 "afm": "802497241",
    #                 "name": "ΕΛΕΓΚΤΙΚΟΣ ΚΡΙΚΟΣ ΜΟΝΟΠΡΟΣΩΠΗ Ι Κ Ε",
    #                 "afmType": "EL"
    #             }],
    #             "awardAmount": {"amount": 37200.0, "currency": "EUR"}
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # Check entity details
    #     assert result.entities_created == 1
    #     entity_rel = DecisionEntityRelationship.objects.get(decision=decision)
    #     assert entity_rel.entity.afm == "802497241"
    #     assert entity_rel.entity.name == "ΕΛΕΓΚΤΙΚΟΣ ΚΡΙΚΟΣ ΜΟΝΟΠΡΟΣΩΠΗ Ι Κ Ε"
    #     assert entity_rel.role == EntityRole.PERSON
    #     assert "person" in entity_rel.parent_key_path.lower()

    #     # Check amount details
    #     assert result.amounts_created == 1
    #     amount_field = DecisionAmountField.objects.get(decision=decision)
    #     assert amount_field.amount == Decimal("37200.00")
    #     assert amount_field.currency == "EUR"
    #     assert amount_field.source_field_name == "awardAmount"

    #     # Check linking (if they're in same container, they should be linked)
    #     # In this case they're not in the same container, so no linking expected

    # def test_extract_without_counterpart_detailed(self):
    #     """
    #     Detailed test for extraction WITHOUT counterpart.

    #     Verifies:
    #     - No entity is created (empty person array)
    #     - Amount is still extracted correctly
    #     - Amount has no associated relationship
    #     """
    #     decision = DecisionFactory(
    #         ada="6ΜΚ4ΟΚ91-32Χ",
    #         extra_field_values_json={
    #             "person": [],  # Empty!
    #             "awardAmount": {"amount": 37200.0, "currency": "EUR"}
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # No entities should be created
    #     assert result.entities_created == 0
    #     assert DecisionEntityRelationship.objects.filter(decision=decision).count() == 0

    #     # Amount should still be extracted
    #     assert result.amounts_created == 1
    #     amount_field = DecisionAmountField.objects.get(decision=decision)
    #     assert amount_field.amount == Decimal("37200.00")
    #     assert amount_field.currency == "EUR"
    #     assert amount_field.associated_relationship is None  # No entity to link to

    # def test_extract_multiple_persons(self):
    #     """Test extraction when person array has multiple entries"""
    #     decision = DecisionFactory(
    #         ada="TEST-MULTI",
    #         extra_field_values_json={
    #             "person": [
    #                 {"afm": "123456789", "name": "Person A", "afmType": "EL"},
    #                 {"afm": "987654321", "name": "Person B", "afmType": "EL"}
    #             ],
    #             "awardAmount": {"amount": 50000.0, "currency": "EUR"}
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # Should extract 2 entities
    #     assert result.entities_created == 2
    #     entities = DecisionEntityRelationship.objects.filter(decision=decision)
    #     assert entities.count() == 2
    #     afms = {e.entity.afm for e in entities}
    #     assert afms == {"123456789", "987654321"}

    #     # Should still extract 1 amount
    #     assert result.amounts_created == 1

    # def test_extract_sponsor_with_amount(self):
    #     """Test extraction of sponsor with associated expense amount"""
    #     decision = DecisionFactory(
    #         ada="TEST-SPONSOR",
    #         extra_field_values_json={
    #             "sponsor": [{
    #                 "sponsorAFMName": "111111111",
    #                 "sponsorName": "Big Corporation",
    #                 "expenseAmount": {"amount": 100000.0, "currency": "EUR"},
    #                 "afmType": "EL"
    #             }]
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # Should extract 1 entity (sponsor)
    #     assert result.entities_created == 1
    #     entity_rel = DecisionEntityRelationship.objects.get(decision=decision)
    #     assert entity_rel.role == EntityRole.SPONSOR

    #     # Should extract 1 amount (expenseAmount)
    #     assert result.amounts_created == 1
    #     amount_field = DecisionAmountField.objects.get(decision=decision)
    #     assert amount_field.amount == Decimal("100000.00")
    #     assert amount_field.source_field_name == "expenseAmount"

    #     # They should be linked (same container path)
    #     assert amount_field.associated_relationship == entity_rel

    # def test_extract_no_extra_field_values(self):
    #     """Test handling of decisions with no extra_field_values_json"""
    #     decision = DecisionFactory(
    #         ada="TEST-EMPTY",
    #         extra_field_values_json=None
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     assert result.entities_created == 0
    #     assert result.amounts_created == 0
    #     assert result.had_extractable_content is False

    # def test_extract_skip_if_existing(self):
    #     """Test idempotent mode - should skip if already extracted"""
    #     decision = DecisionFactory(
    #         ada="TEST-SKIP",
    #         extra_field_values_json={
    #             "person": [{"afm": "123456789", "name": "Test Person", "afmType": "EL"}],
    #             "awardAmount": {"amount": 10000.0, "currency": "EUR"}
    #         }
    #     )

    #     # First extraction
    #     service = EntityAmountExtractionService()
    #     result1 = service.extract_from_decision(
    #         decision,
    #         save_to_db=True,
    #         skip_if_existing=False
    #     )

    #     assert result1.entities_created == 1
    #     assert result1.amounts_created == 1

    #     # Second extraction with skip_if_existing=True
    #     result2 = service.extract_from_decision(
    #         decision,
    #         save_to_db=True,
    #         skip_if_existing=True
    #     )

    #     # Should skip and report existing counts
    #     assert result2.entities_created == 1  # Reports existing
    #     assert result2.amounts_created == 1   # Reports existing

    #     # Verify no duplicates were created
    #     assert DecisionEntityRelationship.objects.filter(decision=decision).count() == 1
    #     assert DecisionAmountField.objects.filter(decision=decision).count() == 1

    # def test_extract_invalid_afm_skipped(self):
    #     """Test that invalid AFMs are skipped"""
    #     decision = DecisionFactory(
    #         ada="TEST-INVALID",
    #         extra_field_values_json={
    #             "person": [
    #                 {"afm": "123", "name": "Invalid AFM", "afmType": "EL"},  # Too short
    #                 {"afm": "123456789", "name": "Valid AFM", "afmType": "EL"}  # Valid
    #             ]
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # Should only extract the valid AFM
    #     assert result.entities_created == 1
    #     entity_rel = DecisionEntityRelationship.objects.get(decision=decision)
    #     assert entity_rel.entity.afm == "123456789"

    # def test_extract_skip_organization_afms(self):
    #     """Test that organization AFMs are skipped based on afmType"""
    #     decision = DecisionFactory(
    #         ada="TEST-ORG",
    #         extra_field_values_json={
    #             "person": [
    #                 {
    #                     "afm": "999999999",
    #                     "name": "Organization",
    #                     "afmType": "PublicOrganization"  # Should be skipped
    #                 },
    #                 {
    #                     "afm": "888888888",
    #                     "name": "Company",
    #                     "afmType": "EL"  # Should be extracted
    #                 }
    #             ]
    #         }
    #     )

    #     result = extract_entities_and_amounts(decision, save_to_db=True)

    #     # Should only extract the non-organization AFM
    #     assert result.entities_created == 1
    #     entity_rel = DecisionEntityRelationship.objects.get(decision=decision)
    #     assert entity_rel.entity.afm == "888888888"
