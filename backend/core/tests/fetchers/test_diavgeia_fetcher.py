from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from diavgeia_api.models.organizations import Unit


def test_unit_is_fetched():
    a_fetcher = DiavgeiaFetcher()
    wanted_unit = "100006945"
    wanted_unit: Unit = a_fetcher.fetch_a_unit(wanted_unit)
    assert isinstance(wanted_unit, Unit)
    # Check all properties of the Unit object
    assert (
        wanted_unit.label
        == "ΔΙΕΥΘΥΝΣΗ ΕΝΕΡΓΕΙΑΚΩΝ ΠΟΛΙΤΙΚΩΝ ΚΑΙ ΕΝΕΡΓΕΙΑΚΗΣ ΑΠΟΔΟΤΙΚΟΤΗΤΑΣ"
    )

    assert wanted_unit.category == "ADMINISTRATION"
    assert wanted_unit.active is True
    assert wanted_unit.parentId == "100006937"
