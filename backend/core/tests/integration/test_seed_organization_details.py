import pytest
import responses
from core.models import Organization, Signer, SignerUnit, Unit
from core.services.seed_service import SeedService

pytestmark = pytest.mark.django_db


@pytest.fixture
def test_organization():
    """Create a test organization."""
    return Organization.objects.create(
        uid="6174",
        latin_name="TestOrg",
        label="Test Organization",
        status="active",
        category="GOVERNMENT",
    )


@pytest.mark.fast
@responses.activate
def test_seed_organization_details(
    test_organization,
    mock_positions_json,
    mock_units_json,
    mock_signers_json,
):
    # Mock API responses for units, positions, and signers
    units_payload = mock_units_json

    positions_payload = mock_positions_json

    signers_payload = mock_signers_json

    # Set up mock responses
    responses.add(
        responses.GET,
        f"https://diavgeia.gov.gr/opendata/organizations/{test_organization.uid}/units",
        json=units_payload,
        status=200,
    )

    responses.add(
        responses.GET,
        f"https://diavgeia.gov.gr/opendata/organizations/{test_organization.uid}/positions",
        json=positions_payload,
        status=200,
    )

    responses.add(
        responses.GET,
        f"https://diavgeia.gov.gr/opendata/organizations/{test_organization.uid}/signers",
        json=signers_payload,
        status=200,
    )

    service = SeedService()
    results = service.seed_organization_details(test_organization.uid)

    # Check results counts
    assert results["units"] == len(units_payload["units"])
    assert results["positions"] == len(positions_payload["positions"])
    assert results["signers"] == len(signers_payload["signers"])

    # Verify database state
    assert Unit.objects.filter(organization=test_organization).count() == len(
        units_payload["units"]
    )
    assert Signer.objects.filter(organization=test_organization).count() == len(
        signers_payload["signers"]
    )

    # Verify relationships
    unit = Unit.objects.get(uid="81204")
    assert unit.domains.count() == 2

    signer = Signer.objects.get(uid="100084253")
    signer_units = SignerUnit.objects.filter(signer=signer)
    assert signer_units.count() == 1
    assert signer_units.first().unit_id == "81204"
    assert signer_units.first().position_id == "POS_10091"
