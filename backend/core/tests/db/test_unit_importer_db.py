import pytest
from core.importers.unit import UnitDomainImporter, UnitImporter
from core.models import Organization, Unit, UnitDomain
from diavgeia_api.models.organizations import Unit as UnitDTO

pytestmark = pytest.mark.django_db


@pytest.fixture
def test_organization():
    """Create a test organization for foreign key references."""
    return Organization.objects.create(
        uid="org123",
        latin_name="TestOrg",
        label="Test Organization",
        status="active",
        category="GOVERNMENT",
    )


@pytest.mark.fast
def test_create_and_update_units(test_organization):
    imp = UnitImporter()

    # first call creates
    created = imp.import_many(
        [
            UnitDTO(
                uid="unit123",
                label="Finance Department",
                active=True,
                category="DEPARTMENT",
                parentId="a_test_parent",
            )
        ],
        defaults={"organization": test_organization, "parent": None},
    )
    parent_unit_created = imp.import_many(
        [
            UnitDTO(
                uid="unit321",
                label="Accounting Department",
                active=True,
                category="DEPARTMENT",
                parentId="b_test_parent",
            )
        ],
        defaults={"organization": test_organization, "parent": None},
    )
    assert created == 1
    unit_fetched = Unit.objects.get(uid="unit123")
    parent_unit_fetched = Unit.objects.get(uid="unit321")
    assert unit_fetched.label == "Finance Department"
    assert unit_fetched.organization == test_organization

    # second call updates, no new row
    created = imp.import_many(
        [
            UnitDTO(
                uid="unit123",
                label="Updated Finance Department",
                active=True,
                category="DEPARTMENT",
                parentId="b_test_parent",
            )
        ],
        defaults={"organization": test_organization, "parent": parent_unit_fetched},
    )
    assert created == 0
    unit_fetched.refresh_from_db()
    assert unit_fetched.label == "Updated Finance Department"


class DomainDTO:
    def __init__(self, domain):
        self.uid = domain  # Use domain as the uid
        self.domain = domain


@pytest.mark.fast
def test_create_and_update_unit_domains():
    # Create parent unit first
    org = Organization.objects.create(
        uid="org123",
        latin_name="TestOrg",
        label="Test Organization",
        status="active",
        category="GOVERNMENT",
    )
    unit = Unit.objects.create(uid="unit123", label="IT Department", organization=org)

    imp = UnitDomainImporter()

    # first call creates
    created = imp.import_many(
        [DomainDTO(domain) for domain in ["example.com", "test.org"]],
        defaults={"unit": unit},
    )
    assert created == 2

    domains = UnitDomain.objects.filter(unit=unit)
    assert domains.count() == 2
    # assert set(d.domain for d in domains) == {"example.com", "test.org"}
