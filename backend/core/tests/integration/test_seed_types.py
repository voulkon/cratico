import pytest
import responses
from core.models.types import ActType, ExtraField
from core.services.seed_service import SeedService

pytestmark = pytest.mark.django_db


@pytest.fixture
def mock_types_summary_response():
    """Mock response for the types list endpoint."""
    return {
        "decisionTypes": [
            {"uid": "Δ1", "label": "Διορισμός", "allowedInDecisions": True},
            {"uid": "Δ2", "label": "Διαγωνισμός", "allowedInDecisions": True},
            {"uid": "Δ3", "label": "Δημοσίευση", "allowedInDecisions": True},
        ]
    }


@pytest.fixture
def mock_type_details_response():
    """Mock response for a type details endpoint."""
    return {
        "uid": "Δ1",
        "label": "Διορισμός",
        "allowedInDecisions": True,
        "parent": None,
        "extraFields": [
            {
                "uid": "appointeeInfo",
                "label": "Στοιχεία Διοριζόμενου",
                "type": "object",
                "validation": None,
                "required": True,
                "multiple": False,
                "maxLength": 0,
                "dictionary": None,
                "searchTerm": "appointeeInfo",
                "relAdaDecisionTypes": None,
                "relAdaConstrainedInOrganization": None,
                "nestedFields": [
                    {
                        "uid": "appointeeName",
                        "label": "Ονοματεπώνυμο",
                        "type": "string",
                        "validation": None,
                        "required": True,
                        "multiple": False,
                        "maxLength": 200,
                        "dictionary": None,
                        "searchTerm": "appointeeName",
                        "relAdaDecisionTypes": None,
                        "relAdaConstrainedInOrganization": None,
                        "nestedFields": [],
                    },
                    {
                        "uid": "appointeePosition",
                        "label": "Θέση",
                        "type": "string",
                        "validation": None,
                        "required": True,
                        "multiple": False,
                        "maxLength": 200,
                        "dictionary": None,
                        "searchTerm": "appointeePosition",
                        "relAdaDecisionTypes": None,
                        "relAdaConstrainedInOrganization": None,
                        "nestedFields": [],
                    },
                ],
            }
        ],
    }


@pytest.mark.fast
@responses.activate
def test_seed_types_happy_path(mock_types_summary_response, mock_type_details_response):
    """Test the entire type seeding process with API mocks."""

    # Setup mock responses for the API calls
    responses.add(
        responses.GET,
        "https://diavgeia.gov.gr/opendata/types",
        json=mock_types_summary_response,
        status=200,
    )

    # Add mock responses for each type's details
    for type_info in mock_types_summary_response["decisionTypes"]:
        if type_info["uid"] == "Δ1":
            # Use our detailed mock for the first type
            response_data = mock_type_details_response
        else:
            # For others, use a simpler response with no extra fields
            response_data = {
                "uid": type_info["uid"],
                "label": type_info["label"],
                "allowedInDecisions": type_info["allowedInDecisions"],
                "parent": None,
                "extraFields": [],
            }

        responses.add(
            responses.GET,
            f"https://diavgeia.gov.gr/opendata/types/{type_info['uid']}/details",
            json=response_data,
            status=200,
        )

    # Run the seed service
    service = SeedService()
    result = service.seed_types(force=True)

    # Validate the results
    assert result["status"] == "success"
    assert result["seeded"] is True

    # Check database state
    assert ActType.objects.count() == 3

    # Check the type with extra fields
    detailed_type = ActType.objects.get(uid="Δ1")
    assert detailed_type.label == "Διορισμός"
    assert detailed_type.allowed_in_decisions is True

    # Check that extra fields were created
    assert (
        ExtraField.objects.filter(act_type=detailed_type).count() == 3
    )  # 1 parent + 2 nested fields

    # Check parent-child relationships
    parent_field = ExtraField.objects.get(uid="appointeeInfo")
    assert parent_field.field_type == "object"
    assert parent_field.required is True

    # Check nested fields
    child_fields = ExtraField.objects.filter(parent_field=parent_field)
    assert child_fields.count() == 2

    # Verify API was called the expected number of times
    assert len(responses.calls) == 4  # 1 for types list + 3 for type details

    # Test that subsequent calls don't recreate the data
    second_result = service.seed_types(force=False)
    assert second_result["seeded"] is False
    assert "Already populated" in second_result["message"]

    # But with force=True it should update
    third_result = service.seed_types(force=True)
    assert third_result["seeded"] is True
