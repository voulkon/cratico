import pytest
from core.importers.organization import OrganizationImporter
from core.models.organizations import OrganizationStatus
from diavgeia_api.models.organizations import Organization


@pytest.fixture
def organization_dto():
    return Organization(
        uid="42",
        latinName="Foo",
        abbreviation=None,
        label="Foo SA",
        status="active",
        category="NPDD",
        vatNumber="EL123",
        website=None,
    )


@pytest.fixture
def expected_defaults_mapping():
    to_return = {
        "abbreviation": None,
        "category": "NPDD",
        "fek_issue": None,
        "fek_number": None,
        "fek_year": None,
        "label": "Foo SA",
        "latin_name": "Foo",
        "status": OrganizationStatus.ACTIVE.value,
        "supervisor_org_name": None,
        "supervisor_org_uid": None,
        "vat_number": "EL123",
        "website": None,
    }
    return to_return


@pytest.mark.fast
def test_to_defaults_mapping(organization_dto, expected_defaults_mapping):
    imp = OrganizationImporter()
    defaults = imp._to_defaults(organization_dto)
    are_they_same = defaults == expected_defaults_mapping
    assert are_they_same, f"Expected {expected_defaults_mapping}, but got {defaults}"
