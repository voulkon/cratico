import datetime

import pytest
from core.importers.unit import UnitImporter
from diavgeia_api.models.organizations import Unit as UnitDTO


@pytest.fixture
def unit_dto():
    """Sample unit DTO for testing."""
    return UnitDTO(
        uid="unit123",
        label="Finance Department",
        active=True,
        activeFrom="2023-01-01T00:00:00",
        activeUntil=None,
        category="DEPARTMENT",
        parentId="parent_unit456",
    )


@pytest.fixture
def expected_unit_defaults():
    """Expected mapping results for unit."""
    return {
        "label": "Finance Department",
        "active": True,
        "active_from": datetime.datetime(2023, 1, 1, 0, 0),
        "active_until": None,
        "category": "DEPARTMENT",
        # 'parent': 'parent_unit456',
    }


@pytest.mark.fast
def test_unit_to_defaults_mapping(unit_dto, expected_unit_defaults):
    imp = UnitImporter()
    defaults = imp._to_defaults(unit_dto)
    assert (
        defaults == expected_unit_defaults
    ), f"Expected {expected_unit_defaults}, but got {defaults}"
