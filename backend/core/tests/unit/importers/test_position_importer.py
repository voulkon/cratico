import pytest
from core.importers.positions import PositionImporter
from diavgeia_api.models.organizations import Position as PositionDTO


@pytest.fixture
def position_dto():
    """Sample position DTO for testing."""
    return PositionDTO(
        uid="pos123",
        label="CFO",
    )


@pytest.fixture
def expected_position_defaults():
    """Expected mapping results for position."""
    return {
        "label": "CFO",
    }


@pytest.mark.fast
def test_position_to_defaults_mapping(position_dto, expected_position_defaults):
    imp = PositionImporter()
    defaults = imp._to_defaults(position_dto)
    assert (
        defaults == expected_position_defaults
    ), f"Expected {expected_position_defaults}, but got {defaults}"
