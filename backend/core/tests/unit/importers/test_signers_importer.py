# from core.importers.signer import SignerImporter
# from diavgeia_api.models.organizations import Signer as SignerDTO
# import pytest


# @pytest.fixture
# def signer_dto():
#     """Sample position DTO for testing."""
#     return PositionDTO(
#         uid="pos123",
#         label="Mitsos",
#     )

# class Signer(BaseModel):
#     """Represents a single signer. Uses API field names directly."""

#     uid: str
#     firstName: str
#     lastName: str
#     active: bool
#     activeFrom: Optional[datetime.datetime] = None
#     activeUntil: Optional[datetime.datetime] = None
#     organizationId: str
#     hasOrganizationSignRights: bool
#     units: List[SignerUnit]

#     @field_validator("activeFrom", "activeUntil", mode="before")
#     @classmethod
#     def timestamp_ms_to_datetime(cls, v):
#         """Convert timestamp in milliseconds to datetime object."""
#         if v is not None:
#             # Convert milliseconds to seconds
#             return datetime.datetime.fromtimestamp(v / 1000, tz=datetime.timezone.utc)
#         return None

# @pytest.fixture
# def expected_signer_defaults():
#     """Expected mapping results for position."""
#     return {
#         'label': 'Mitsos',
#     }


# def test_position_to_defaults_mapping(
#     position_dto,
#     expected_position_defaults
# ):
#     imp = PositionImporter()
#     defaults = imp._to_defaults(position_dto)
#     assert defaults == expected_position_defaults, f"Expected {expected_position_defaults}, but got {defaults}"
