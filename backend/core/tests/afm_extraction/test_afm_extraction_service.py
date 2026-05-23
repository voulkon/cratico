import json
from pathlib import Path

import pytest
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.decisions import Decision
from core.models.entities import AFMEntity, DecisionEntityRelationship
from core.services.afm_extractor import AFMExtractionService
from loguru import logger


def load_ada_based_test_cases(django_folder_of_data: Path) -> list:
    """Load all ADA-based test cases from the new JSON structure."""
    test_case_file = django_folder_of_data / "ada_based_test_cases.json"
    if not test_case_file.exists():
        pytest.skip(f"ADA test case file not found at {test_case_file}")

    with open(test_case_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Flatten all scenario types into a single list
    all_cases = []
    for scenario_type, cases in data.items():
        if isinstance(cases, list):  # Skip any non-list items
            all_cases.extend(cases)

    # Filter out any empty or malformed test cases and limit for testing
    valid_cases = [
        case
        for case in all_cases
        if case and "input_data" in case and "expected_results" in case
    ]
    return valid_cases[:10]  # Limit to first 10 for faster testing


def get_or_fetch_decision(ada: str) -> Decision:
    """Get decision from database or fetch it from API if not found."""
    try:
        # First, try to get it from the database
        decision = Decision.objects.get(ada=ada)
        logger.info(f"Found decision {ada} in database")
        return decision
    except Decision.DoesNotExist:
        # If not in database, fetch from API
        logger.info(f"Decision {ada} not in database, fetching from API")
        fetcher = DiavgeiaFetcher()

        try:
            decision_dtos = fetcher.fetch_a_decision(ada)
            if not decision_dtos:
                pytest.skip(f"Could not fetch decision {ada} from API")

            # Import the decision
            from core.importers.decisions import DecisionImporter

            importer = DecisionImporter()
            imported_decisions = importer.import_many([decision_dtos])

            if not imported_decisions:
                pytest.skip(f"Failed to import decision {ada}")

            decision = Decision.objects.get(ada=ada)
            logger.info(f"Successfully fetched and imported decision {ada}")
            return decision

        except Exception as e:
            pytest.skip(f"Failed to fetch decision {ada}: {str(e)}")


@pytest.fixture
def afm_service() -> AFMExtractionService:
    """Provides a clean instance of the AFMExtractionService for each test."""
    return AFMExtractionService()


@pytest.fixture
def ada_test_cases(django_folder_of_data: Path) -> list:
    """Load all ADA-based test cases once per module."""
    return load_ada_based_test_cases(django_folder_of_data)


# --- Main Test Class ---


class TestAFMExtractionService:

    @pytest.mark.django_db
    def test_afm_extraction_logic_only(
        self, afm_service: AFMExtractionService, ada_test_cases: list
    ):
        """
        Tests the core extraction logic WITHOUT saving to the database.
        Uses REAL decisions either from database or fetched from API.
        """
        for test_case in ada_test_cases:
            ada = test_case["ada"]

            # Get the real decision from database or API
            real_decision = get_or_fetch_decision(ada)

            # Act: Run the extraction service in logic-only mode
            extracted_entities = afm_service.extract_afms_from_decision(
                real_decision, save_to_db=False
            )

            # Assert: Verify the extracted data matches the expected results
            expected_results = test_case["expected_results"]

            assert len(extracted_entities) == len(expected_results), (
                f"ADA {ada}: Expected {len(expected_results)} entities, "
                f"but got {len(extracted_entities)}\n"
                f"Extracted AFMs: {[e['afm'] for e in extracted_entities]}\n"
                f"Expected AFMs: {[r['afm'] for r in expected_results]}"
            )

            # Create a simplified set for reliable comparison (using sets to ignore order)
            extracted_set = {
                (e["afm"], e["source_field_name"]) for e in extracted_entities
            }
            expected_set = {
                (res["afm"], res["source_field_name"]) for res in expected_results
            }

            assert extracted_set == expected_set, (
                f"ADA {ada}: AFM mismatch.\n"
                f"Expected: {expected_set}\n"
                f"Got: {extracted_set}\n"
                f"Missing: {expected_set - extracted_set}\n"
                f"Extra: {extracted_set - expected_set}"
            )

    @pytest.mark.django_db
    def test_afm_extraction_and_database_save(
        self, afm_service: AFMExtractionService, ada_test_cases: list
    ):
        """
        Tests the extraction logic WITH saving to the database.
        Uses REAL decisions and verifies database state.
        """
        for test_case in ada_test_cases:
            ada = test_case["ada"]

            # Get the real decision from database or API
            real_decision = get_or_fetch_decision(ada)

            # Clear any existing AFM relationships for this decision to start clean
            DecisionEntityRelationship.objects.filter(decision=real_decision).delete()

            # Act: Run the extraction service with saving enabled
            afm_service.extract_afms_from_decision(real_decision, save_to_db=True)

            # Assert: Check the database state
            expected_results = test_case["expected_results"]

            # Check total number of relationships created
            actual_relationships = DecisionEntityRelationship.objects.filter(
                decision=real_decision
            )
            assert actual_relationships.count() == len(expected_results), (
                f"ADA {ada}: Expected {len(expected_results)} relationships, "
                f"got {actual_relationships.count()}"
            )

            # Verify each expected relationship was created correctly
            for result in expected_results:
                afm_value = result["afm"]
                source_field = result["source_field_name"]
                expected_role = result["role"]

                # Check that the AFM entity exists
                assert AFMEntity.objects.filter(
                    afm=afm_value
                ).exists(), f"ADA {ada}: AFM entity {afm_value} not found"

                # Check that the relationship exists with correct attributes
                relationship = DecisionEntityRelationship.objects.filter(
                    decision=real_decision, entity__afm=afm_value
                ).first()

                assert (
                    relationship is not None
                ), f"ADA {ada}: Relationship for AFM {afm_value} not found"
                assert relationship.source_field_name == source_field, (
                    f"ADA {ada}: Wrong source field for {afm_value}. "
                    f"Expected: {source_field}, Got: {relationship.source_field_name}"
                )
                assert relationship.role == expected_role, (
                    f"ADA {ada}: Wrong role for {afm_value}. "
                    f"Expected: {expected_role}, Got: {relationship.role}"
                )

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        "scenario_type",
        [
            "single_person_cases",
            "multiple_people_cases",
            "sponsor_cases",
            "grantor_grantee_cases",
            "donation_cases",
            "organization_cases",
        ],
    )
    def test_scenario_specific_extraction(
        self, afm_service, django_folder_of_data, scenario_type
    ):
        """Test specific scenario types using REAL decisions."""
        test_case_file = django_folder_of_data / "ada_based_test_cases.json"

        with open(test_case_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if scenario_type not in data or not data[scenario_type]:
            pytest.skip(f"No test cases for scenario: {scenario_type}")

        # Test the first case in this scenario
        test_case = data[scenario_type][0]
        ada = test_case["ada"]

        # Get the real decision
        real_decision = get_or_fetch_decision(ada)

        extracted_entities = afm_service.extract_afms_from_decision(
            real_decision, save_to_db=False
        )
        expected_results = test_case["expected_results"]

        assert len(extracted_entities) == len(expected_results), (
            f"Scenario {scenario_type}, ADA {ada}: "
            f"Expected {len(expected_results)} entities, got {len(extracted_entities)}"
        )

        # Verify roles are correct for this scenario type
        extracted_roles = {e["role"] for e in extracted_entities}
        expected_roles = {r["role"] for r in expected_results}
        assert (
            extracted_roles == expected_roles
        ), f"Scenario {scenario_type}: Role mismatch. Expected: {expected_roles}, Got: {extracted_roles}"

    @pytest.mark.django_db
    def test_known_complex_decision_6ΣΜ246ΜΤΛΒ_ΖΑΦ(self, afm_service):
        """Test the specific 7-people decision we know about."""
        ada = "6ΣΜ246ΜΤΛΒ-ΖΑΦ"

        # Get the real decision
        real_decision = get_or_fetch_decision(ada)

        # Extract AFMs
        extracted_entities = afm_service.extract_afms_from_decision(
            real_decision, save_to_db=False
        )

        # We know this decision should have 7 people
        expected_afms = {
            "114716471",
            "070890452",
            "999550735",
            "998014210",
            "999730457",
            "114711162",
            "094394592",
        }

        assert (
            len(extracted_entities) == 7
        ), f"Expected 7 entities, got {len(extracted_entities)}"

        extracted_afms = {e["afm"] for e in extracted_entities}
        assert (
            extracted_afms == expected_afms
        ), f"AFM mismatch. Expected: {expected_afms}, Got: {extracted_afms}"

        # All should be PERSON role
        for entity in extracted_entities:
            assert (
                entity["role"] == "PERSON"
            ), f"Expected PERSON role, got {entity['role']}"
            assert entity["source_field_name"] == "afm", f"Expected 'afm' field"
