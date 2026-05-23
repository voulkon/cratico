import pytest
from core.importers.organization import OrganizationImporter
from core.models import Organization
from diavgeia_api.models.organizations import Organization as OrgDTO

pytestmark = pytest.mark.django_db


@pytest.mark.fast
def test_create_and_update_organizations():
    imp = OrganizationImporter()

    # first call creates
    created = imp.import_many(
        [OrgDTO(uid="1", latinName="Foo", label="Foo", status="active", category="")]
    )
    assert created == 1
    org = Organization.objects.get(uid="1")
    assert org.latin_name == "Foo"

    # second call updates, no new row
    created = imp.import_many(
        [OrgDTO(uid="1", latinName="Bar", label="Bar", status="active", category="")]
    )
    assert created == 0
    org.refresh_from_db()
    assert org.latin_name == "Bar"
