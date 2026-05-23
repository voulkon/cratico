import pytest
from core.importers.decisions import DecisionImporter
from core.models import Decision, Organization, Unit
from core.tests.utils import create_decision_dto

pytestmark = pytest.mark.django_db

# Test constants - no more magic strings!
TEST_ORG_ID = "5009"
TEST_UNIT_CHILD_ID = "100026211"
TEST_UNIT_PARENT_ID = "100026195"
TEST_SIGNER_ID = "110954"
TEST_ADA = "9ΜΤΝ7ΛΛ-ΠΩΓ"


def test_unit_organization_resolution_through_parent_chain_with_vcr(vcr_cassette):
    """
    Test the specific case where:
    - Decision has unit 100026211
    - Unit 100026211 has parentId 100026195 (no organizationId)
    - Unit 100026195 has parentId 5009 (no organizationId)
    - 5009 is an organization (not a unit)
    - Both units should end up with organizationId 5009
    """

    with vcr_cassette("test_unit_organization_resolution_through_parent_chain.yaml"):
        # Create the decision DTO
        decision_dto = create_decision_dto(
            ada=TEST_ADA,
            org_id=TEST_ORG_ID,
            unit_ids=[TEST_UNIT_CHILD_ID],  # Fixed: unit_ids not unitIds
            signer_ids=[TEST_SIGNER_ID],
        )

        # Import the decision - this will trigger the resolution logic
        importer = DecisionImporter()
        created_count = importer.import_many([decision_dto])

        # Verify the decision was created
        assert created_count == 1
        decision = Decision.objects.get(ada=TEST_ADA)

        # Verify both units were created with the correct organization
        unit_child = Unit.objects.get(uid=TEST_UNIT_CHILD_ID)
        unit_parent = Unit.objects.get(uid=TEST_UNIT_PARENT_ID)
        org = Organization.objects.get(uid=TEST_ORG_ID)

        # Both units should have the same organization
        assert unit_child.organization_id == TEST_ORG_ID
        assert unit_parent.organization_id == TEST_ORG_ID

        # Unit relationships
        assert unit_child.parent_id == TEST_UNIT_PARENT_ID
        assert unit_parent.organization_id == TEST_ORG_ID  # Parent points to org

        # Decision should be linked to the unit
        assert decision.units.filter(uid=TEST_UNIT_CHILD_ID).exists()

        # Verify the resolution path was tracked
        assert unit_child.resolution_path is not None
        assert unit_child.resolution_path["result"] in [
            "found_in_api_as_organization",
            "found_in_db_as_organization",
        ]
        assert unit_child.resolution_path["organization_id"] == TEST_ORG_ID
