import pytest
from core.importers.types import ActTypeImporter, ExtraFieldImporter
from core.models.types import ActType, ExtraField
from diavgeia_api.models.types import ExtraField as ExtraFieldDTO
from diavgeia_api.models.types import TypeDetails, TypeSummary


@pytest.fixture
def type_summary_dto():
    """Create a simple TypeSummary DTO for testing."""
    return TypeSummary(uid="type_1", label="Test Type", allowedInDecisions=True)


@pytest.fixture
def type_details_dto():
    """Create a TypeDetails DTO with extra fields for testing."""
    return TypeDetails(
        uid="type_1",
        label="Test Type",
        allowedInDecisions=True,
        parent="parent_type_1",
        extraFields=[
            ExtraFieldDTO(
                uid="field_1",
                label="Test Field",
                type="string",
                required=True,
                multiple=False,
                maxLength=100,
                validation="email",
                dictionary=None,
                searchTerm="test_field",
                relAdaDecisionTypes=None,
                relAdaConstrainedInOrganization=None,
                fixedValueList=None,
                nestedFields=[],
            ),
            ExtraFieldDTO(
                uid="field_2",
                label="Nested Field Container",
                type="object",
                required=False,
                multiple=True,
                maxLength=0,
                validation=None,
                dictionary=None,
                searchTerm="nested_container",
                relAdaDecisionTypes=None,
                relAdaConstrainedInOrganization=None,
                fixedValueList=None,
                nestedFields=[
                    ExtraFieldDTO(
                        uid="nested_field_1",
                        label="Nested Field",
                        type="number",
                        required=True,
                        multiple=False,
                        maxLength=0,
                        validation=None,
                        dictionary=None,
                        searchTerm=None,
                        relAdaDecisionTypes=None,
                        relAdaConstrainedInOrganization=None,
                        fixedValueList=None,
                        nestedFields=[],
                    )
                ],
            ),
        ],
    )


@pytest.fixture
def expected_type_defaults():
    """Expected defaults mapping for ActType."""
    return {"label": "Test Type", "allowed_in_decisions": True}


@pytest.fixture
def expected_extra_field_defaults():
    """Expected defaults mapping for ExtraField."""
    return {
        "label": "Test Field",
        "field_type": "string",
        "required": True,
        "multiple": False,
        "max_length": 100,
        "validation": "email",
        "dictionary": None,
        "search_term": "test_field",
        "rel_ada_decision_types": None,
        "rel_ada_constrained_in_organization": None,
        # "fixed_value_list": None,
    }


@pytest.mark.fast
def test_act_type_to_defaults_mapping(type_summary_dto, expected_type_defaults):
    """Test that ActTypeImporter._to_defaults correctly maps fields."""
    importer = ActTypeImporter()
    defaults = importer._to_defaults(type_summary_dto)

    assert (
        defaults == expected_type_defaults
    ), f"Expected {expected_type_defaults}, but got {defaults}"


@pytest.mark.fast
def test_extra_field_to_defaults_mapping(
    type_details_dto, expected_extra_field_defaults
):
    """Test that ExtraFieldImporter._to_defaults correctly maps fields."""
    importer = ExtraFieldImporter()
    # Use first extra field from the type_details_dto
    defaults = importer._to_defaults(type_details_dto.extraFields[0])

    assert (
        defaults == expected_extra_field_defaults
    ), f"Expected {expected_extra_field_defaults}, but got {defaults}"


@pytest.mark.django_db
def test_act_type_import_details(type_details_dto):
    """Test importing a complete type with details."""
    # First create parent type referenced by the DTO
    parent_type = ActType.objects.create(
        uid="parent_type_1", label="Parent Type", allowed_in_decisions=True
    )

    importer = ActTypeImporter()
    result = importer.import_details(type_details_dto)

    # Verify the result structure
    assert "act_type" in result
    assert "created" in result
    assert result["created"] is True

    # Verify the imported type
    act_type = result["act_type"]
    assert act_type.uid == type_details_dto.uid
    assert act_type.label == type_details_dto.label
    assert act_type.allowed_in_decisions == type_details_dto.allowedInDecisions
    assert act_type.parent == parent_type

    # Verify update works too (set created=False)
    update_result = importer.import_details(type_details_dto)
    assert update_result["created"] is False
    assert update_result["updated"] is True


@pytest.mark.django_db
def test_extra_field_import_for_type(type_details_dto):
    """Test importing extra fields for a type, including nested fields."""
    importer = ExtraFieldImporter()

    # First create the act type to link fields to
    act_type = ActType.objects.create(
        uid=type_details_dto.uid,
        label=type_details_dto.label,
        allowed_in_decisions=type_details_dto.allowedInDecisions,
    )

    # Import the extra fields
    stats = importer.import_for_type(type_details_dto)

    # Verify stats
    assert stats["created"] == 3  # 1 top-level + 1 container
    assert stats["updated"] == 0

    # Verify extra fields were created
    assert ExtraField.objects.filter(act_type=act_type).count() == 3

    # Verify first field (with help text)
    field_1 = ExtraField.objects.get(uid="field_1", act_type=act_type)
    assert field_1.label == "Test Field"
    assert field_1.field_type == "string"
    assert field_1.required is True
    assert field_1.validation == "email"

    # Verify container field
    field_2 = ExtraField.objects.get(uid="field_2", act_type=act_type)
    assert field_2.field_type == "object"
    assert field_2.multiple is True

    # Verify nested field
    nested_field = ExtraField.objects.get(uid="nested_field_1", act_type=act_type)
    assert nested_field.label == "Nested Field"
    assert nested_field.field_type == "number"
    assert nested_field.parent_field == field_2

    # Test update scenario
    # Modify DTO and reimport
    type_details_dto.extraFields[0].label = "Updated Field"
    type_details_dto.extraFields[0].required = False

    # Import again
    update_stats = importer.import_for_type(type_details_dto)

    # Check update stats
    assert update_stats["created"] == 0
    assert update_stats["updated"] == 3

    # Verify field was updated
    updated_field = ExtraField.objects.get(uid="field_1", act_type=act_type)
    assert updated_field.label == "Updated Field"
    assert updated_field.required is False


@pytest.mark.django_db
def test_import_many_types():
    """Test importing multiple types at once."""
    importer = ActTypeImporter()

    # Create multiple type DTOs
    type_dtos = [
        TypeSummary(uid=f"type_{i}", label=f"Type {i}", allowedInDecisions=True)
        for i in range(1, 4)
    ]

    # Import them
    created_count = importer.import_many(type_dtos)

    # Verify all were created
    assert created_count == 3
    assert ActType.objects.count() == 3

    # Verify specific attributes
    for i in range(1, 4):
        act_type = ActType.objects.get(uid=f"type_{i}")
        assert act_type.label == f"Type {i}"
        assert act_type.allowed_in_decisions is True


@pytest.mark.django_db
def test_import_nested_fields_deeply():
    """Test importing deeply nested fields (3 levels)."""
    # Create a DTO with deeply nested fields
    deep_dto = TypeDetails(
        uid="deep_type",
        label="Deep Nested Type",
        allowedInDecisions=True,
        extraFields=[
            ExtraFieldDTO(
                uid="level1",
                label="Level 1",
                type="object",
                required=True,
                multiple=False,
                maxLength=0,
                nestedFields=[
                    ExtraFieldDTO(
                        uid="level2",
                        label="Level 2",
                        type="object",
                        required=True,
                        multiple=False,
                        maxLength=0,
                        nestedFields=[
                            ExtraFieldDTO(
                                uid="level3",
                                label="Level 3",
                                type="string",
                                required=True,
                                multiple=False,
                                maxLength=50,
                                nestedFields=[],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    # Create the type first
    act_type = ActType.objects.create(
        uid="deep_type", label="Deep Nested Type", allowed_in_decisions=True
    )

    # Import the fields
    importer = ExtraFieldImporter()
    stats = importer.import_for_type(deep_dto)

    # Verify stats
    assert stats["created"] == 3  # 1 field at each level

    # Get the fields
    level1 = ExtraField.objects.get(uid="level1", act_type=act_type)
    level2 = ExtraField.objects.get(uid="level2", act_type=act_type)
    level3 = ExtraField.objects.get(uid="level3", act_type=act_type)

    # Verify hierarchy
    assert level1.parent_field is None
    assert level2.parent_field == level1
    assert level3.parent_field == level2
