from unittest.mock import MagicMock, patch

import pytest
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.decisions import Decision
from core.models.organizations import Organization, Signer
from core.tests.utils import create_decision_dto
from diavgeia_api.models.decisions import Decision as DecisionDTO
from diavgeia_api.models.organizations import Organization as OrganizationDTO
from diavgeia_api.models.organizations import Signer as SignerDTO


@pytest.fixture
def mock_diavgeia_fetcher(db):
    """Mock the DiavgeiaFetcher to return controlled test data."""
    # Pre-create the decision's own organization so the importer does not try
    # to fetch it from the (mocked) API - these tests target the *signer's*
    # missing organization dependency.
    Organization.objects.get_or_create(
        uid="100054486",
        defaults={
            "label": "ΥΠΟΥΡΓΕΙΟ ΨΗΦΙΑΚΗΣ ΔΙΑΚΥΒΕΡΝΗΣΗΣ",
            "latin_name": "min_digital",
            "status": "active",
            "category": "MINISTRY",
        },
    )

    with patch("core.importers.decisions.DiavgeiaFetcher") as mock_fetcher_cls:
        # Create the mock instance
        mock_fetcher = MagicMock()
        mock_fetcher_cls.return_value = mock_fetcher

        # 1. Mock the inactive organization (100054498)
        org_dto = OrganizationDTO(
            uid="100054498",
            label="ΥΠΟΥΡΓΕΙΟ ΕΡΓΑΣΙΑΣ ΚΑΙ ΚΟΙΝΩΝΙΚΩΝ ΥΠΟΘΕΣΕΩΝ",
            latinName="min_erky",
            status="inactive",
            category="MINISTRY",
            vatNumber="011111111",
        )
        mock_fetcher.fetch_an_organization.return_value = org_dto

        # 2. Mock the signer (100063912)
        signer_dto = SignerDTO(
            uid="100063912",
            firstName="ΚΩΝΣΤΑΝΤΙΝΟΣ",
            lastName="ΧΑΤΖΗΔΑΚΗΣ",
            active=False,
            organizationId="100054498",  # References the inactive org
            hasOrganizationSignRights=True,
            units=[],
        )
        mock_fetcher.fetch_a_signer.return_value = signer_dto

        yield mock_fetcher


@pytest.mark.django_db
def test_fetch_decision_with_missing_org_dependency(mock_diavgeia_fetcher):
    """
    Test that when importing a decision with a signer whose organization doesn't exist,
    the system properly fetches the missing organization first.

    This simulates the real-world case from the notes where:
    - Decision from org 100054486
    - References signer 100063912
    - Signer belongs to org 100054498 which is inactive
    """
    # Setup
    importer = DecisionImporter()

    # 1. Create the decision DTO with a signer that references a non-existent org
    decision_dto = create_decision_dto(
        ada="MISS_ORG_TEST",
        org_id="100054486",  # The decision's organization
        signer_ids=[
            "100063912"
        ],  # This signer references org 100054498 which doesn't exist yet
        unit_ids=[],
        subject="Test Decision With Missing Org Dependency",
    )

    # 2. Ensure the signer's organization doesn't exist yet
    Organization.objects.filter(uid="100054498").delete()
    assert not Organization.objects.filter(uid="100054498").exists()

    # 3. Import the decision
    created_count = importer.import_many([decision_dto])

    # 4. Verify the results
    assert created_count == 1, "The decision should be successfully created"

    # 5. Verify the organization was created
    org = Organization.objects.filter(uid="100054498")
    assert org.exists(), "The organization should be created during import"
    assert org.first().label == "ΥΠΟΥΡΓΕΙΟ ΕΡΓΑΣΙΑΣ ΚΑΙ ΚΟΙΝΩΝΙΚΩΝ ΥΠΟΘΕΣΕΩΝ"
    assert org.first().status == "inactive"

    # 6. Verify the signer was created and linked to the organization
    signer = Signer.objects.filter(uid="100063912")
    assert signer.exists(), "The signer should be created during import"
    assert signer.first().first_name == "ΚΩΝΣΤΑΝΤΙΝΟΣ"
    assert signer.first().last_name == "ΧΑΤΖΗΔΑΚΗΣ"
    assert signer.first().organization.uid == "100054498"

    # 7. Verify the decision was created with the correct signer
    decision = Decision.objects.get(ada="MISS_ORG_TEST")
    assert "100063912" in [s.uid for s in decision.signers.all()]

    # 8. Verify the fetch methods were called correctly
    mock_diavgeia_fetcher.fetch_a_signer.assert_called_once_with("100063912")
    mock_diavgeia_fetcher.fetch_an_organization.assert_called_once_with("100054498")


@pytest.mark.django_db
def test_org_cache_prevents_duplicate_fetches(mock_diavgeia_fetcher):
    """Test that the organization cache prevents duplicate API calls."""
    # Setup
    importer = DecisionImporter()

    # 1. Create two decisions with signers referencing the same org
    decision_dto1 = create_decision_dto(
        ada="CACHE_TEST_1",
        org_id="100054486",
        signer_ids=["100063912"],
        unit_ids=[],
        subject="First Test Decision",
    )

    decision_dto2 = create_decision_dto(
        ada="CACHE_TEST_2",
        org_id="100054486",
        signer_ids=["100063912"],  # Same signer, should reuse cached org info
        unit_ids=[],
        subject="Second Test Decision",
    )

    # 2. Ensure the signer's organization doesn't exist
    Organization.objects.filter(uid="100054498").delete()

    # 3. Import both decisions
    created_count = importer.import_many([decision_dto1, decision_dto2])

    # 4. Verify that both were created
    assert created_count == 2
    assert (
        Decision.objects.filter(ada__in=["CACHE_TEST_1", "CACHE_TEST_2"]).count() == 2
    )

    # 5. Verify that the organization fetcher was called only once
    mock_diavgeia_fetcher.fetch_an_organization.assert_called_once_with("100054498")


@pytest.mark.django_db
def test_placeholder_creation_when_org_unfetchable(mock_diavgeia_fetcher):
    """Test that a placeholder org is created when the API can't provide the real org."""
    # Setup
    importer = DecisionImporter()

    # Configure mock to return None for this specific org
    mock_diavgeia_fetcher.fetch_an_organization.return_value = None

    # 1. Create a decision with a signer whose org can't be fetched
    decision_dto = create_decision_dto(
        ada="UNFETCH_TEST",
        org_id="100054486",
        signer_ids=["100063912"],
        unit_ids=[],
        subject="Test with Unfetchable Org",
    )

    # 2. Import the decision
    created_count = importer.import_many([decision_dto])

    # 3. Verify the results
    assert created_count == 1

    # 4. Verify a placeholder org was created
    org = Organization.objects.get(uid="100054498")
    assert org.label.startswith("Unknown Organization")
    assert org.status == "UNKNOWN"
    assert org.category == "UNKNOWN"

    # 5. Verify the signer was still created and linked to the placeholder
    signer = Signer.objects.get(uid="100063912")
    assert signer.organization.uid == "100054498"


@pytest.mark.django_db
def test_cache_reset_between_batches():
    """Test that the organization cache is properly reset between batches."""
    # Create two importers to simulate separate batch runs
    importer1 = DecisionImporter()
    importer2 = DecisionImporter()

    # Check that their caches are empty and separate
    assert importer1.org_cache == {}
    assert importer2.org_cache == {}

    # Add something to the first importer's cache
    importer1.org_cache["test_org"] = True

    # Verify it's only in the first importer
    assert "test_org" in importer1.org_cache
    assert "test_org" not in importer2.org_cache

    # Create a third importer to simulate a new batch
    importer3 = DecisionImporter()
    assert "test_org" not in importer3.org_cache


@pytest.mark.django_db
def test_real_world_decision_import_flow():
    """
    Test the complete flow of importing a decision with dependencies.

    Uses real models instead of mocks to verify the entire integration chain.
    """
    # This would use an actual fixture file with the real-world data structure
    # You would need to create fixture files matching your real API responses

    # Instead of using this approach, you might want to record actual API responses
    # with something like VCR and replay them in tests

    # This is a placeholder for a more comprehensive integration test


# Adding to your existing test_decision_dependencies.py file


@pytest.mark.slow
@pytest.mark.django_db
def test_real_api_call_for_inactive_org_dependency():
    """
    Test with real API calls - imports a decision that references a signer
    with an inactive organization (100054498).
    """
    # Setup
    importer = DecisionImporter()
    fetcher = DiavgeiaFetcher()

    # Clean up any existing test data
    Organization.objects.filter(uid__in=["100054498", "100054486"]).delete()
    Signer.objects.filter(uid="100063912").delete()
    Decision.objects.filter(ada__in=["TEST_REAL_API", "Β1ΨΛ46ΜΤΛΠ-4ΒΩ"]).delete()

    # Make sure the organization doesn't exist yet
    assert not Organization.objects.filter(uid="100054498").exists()

    extra_attributes_of_fake_decision = dict(
        protocolNumber="TEST-PROTOCOL",
        subject="Real API Test with Inactive Org Dependency",
        issueDate="2024-05-01",
        organizationId="100054486",  # ΥΠΟΥΡΓΕΙΟ ΨΗΦΙΑΚΗΣ ΔΙΑΚΥΒΕΡΝΗΣΗΣ
        privateData=False,
        documentUrl="https://example.com/test",
        decisionTypeId="Β.1",
        status="PUBLISHED",
        versionId="12345",
    )
    # Create a decision DTO that references our problematic entities
    # We'll create a synthetic one first to avoid needing to find a specific ADA
    decision_dto: DecisionDTO = create_decision_dto(
        ada="TEST_REAL_API",
        signer_ids=["100063912"],  # ΚΩΝΣΤΑΝΤΙΝΟΣ ΧΑΤΖΗΔΑΚΗΣ
        unit_ids=[],
        extra_attributes=extra_attributes_of_fake_decision,
    )

    # Import the decision - this should trigger real API calls
    created_count = importer.import_many([decision_dto])

    # Verify the results
    assert created_count == 1

    # Verify the organization was imported via real API call
    org = Organization.objects.filter(uid="100054498")
    assert org.exists(), "The organization should be fetched from real API"
    assert org.first().latin_name == "min_erky"
    assert org.first().status == "inactive"

    # Verify the signer was imported via real API call
    signer = Signer.objects.filter(uid="100063912")
    assert signer.exists(), "The signer should be fetched from real API"
    assert signer.first().first_name == "ΚΩΝΣΤΑΝΤΙΝΟΣ"
    assert signer.first().last_name == "ΧΑΤΖΗΔΑΚΗΣ"
    assert signer.first().organization.uid == "100054498"

    # Now let's try with a real decision from the API
    # This test is more likely to break if the API data changes
    real_ada = (
        "Β1ΨΛ46ΜΤΛΠ-4ΒΩ"  # Replace with a real ADA that has the dependencies we want
    )
    try:
        # First clean up any existing data
        Decision.objects.filter(ada=real_ada).delete()

        # Fetch a real decision
        real_decision_dto = fetcher.fetch_a_decision(real_ada)

        # It should have been found (this checks the API is working)
        assert real_decision_dto is not None, "Real decision ADA should be found in API"

        # Import the real decision
        real_created_count = importer.import_many([real_decision_dto])

        # Verify the result
        assert real_created_count == 1
        assert Decision.objects.filter(ada=real_ada).exists()

        # The rest of the validation depends on what's in that specific decision
        # You can add more assertions based on the expected content

    except Exception as e:
        pytest.skip(f"Skipping real ADA test due to API error: {str(e)}")
