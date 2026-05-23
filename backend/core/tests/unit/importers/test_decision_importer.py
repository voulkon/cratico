import decimal

import pytest
from core.importers.decisions import DecisionImporter
from core.models import Decision
from core.models.decisions import Attachment, DecisionAmountKAE, DecisionStatus
from core.models.organizations import Organization, Signer, Unit
from core.tests.utils import (
    create_amount_with_kae_dto,
    create_attachment_dto,
    create_decision_dto,
)
from django.test import TransactionTestCase

# --- Fixtures for Related Objects ---


@pytest.fixture
def test_organization(db):
    """Creates a reusable test Organization."""
    org, _ = Organization.objects.get_or_create(
        uid="org_test_1",
        defaults={
            "label": "Test Organization 1",
            "category": "TEST",
        },  # Add required fields
    )
    return org


@pytest.fixture
def test_signers(db, test_organization):  # <-- Add test_organization dependency here
    """Creates reusable test Signers linked to the test organization."""
    # Ensure all required fields for Signer are provided in defaults
    signer1, _ = Signer.objects.get_or_create(
        uid="signer_test_1",
        defaults={
            "last_name": "Signer1",
            "first_name": "Test",  # Add first_name if required
            "organization": test_organization,  # <-- Link to the organization
        },
    )
    signer2, _ = Signer.objects.get_or_create(
        uid="signer_test_2",
        defaults={
            "last_name": "Signer2",
            "first_name": "Test",  # Add first_name if required
            "organization": test_organization,  # <-- Link to the organization
        },
    )
    return [signer1, signer2]


@pytest.fixture
def test_units(db, test_organization):  # <-- Add test_organization dependency here
    """Creates reusable test Units linked to the test organization."""
    # Ensure all required fields for Unit are provided in defaults
    unit1, _ = Unit.objects.get_or_create(
        uid="unit_test_1",
        defaults={
            "label": "Unit 1",
            "category": "TEST_CAT",  # Add category if required
            "organization": test_organization,  # <-- Link to the organization
        },
    )
    unit2, _ = Unit.objects.get_or_create(
        uid="unit_test_2",
        defaults={
            "label": "Unit 2",
            "category": "TEST_CAT",  # Add category if required
            "organization": test_organization,  # <-- Link to the organization
        },
    )
    return [unit1, unit2]


@pytest.fixture
def test_act_type(db):
    """Creates a test ActType for foreign key references."""
    from core.models.types import ActType

    act_type, _ = ActType.objects.get_or_create(
        uid="dtype_test",
        defaults={
            "label": "Test Decision Type",
            "allowed_in_decisions": True,
        },
    )
    return act_type


# --- Updated Tests ---


@pytest.mark.fast
@pytest.mark.django_db(transaction=False)
def test_decision_importer_to_defaults(test_organization):
    """
    Tests the _to_defaults mapping for direct model fields.
    It does NOT test promoted fields or relations handled outside _to_defaults.
    """
    importer = DecisionImporter()
    test_ada = "ADATODEFAULTS"
    test_protocol = "PN123"
    test_subject = "Subject Test"
    test_version_id = "v1.0"

    dto = create_decision_dto(
        ada=test_ada,
        org_id=test_organization.uid,
        extra_fields_config=None,
        extra_attributes={
            "protocolNumber": test_protocol,
            "subject": test_subject,
            "decisionTypeId": "dtype_test",  # This won't be in defaults, it's in special_handling_fields
            "privateData": True,
            "status": DecisionStatus.PUBLISHED,
            "versionId": test_version_id,
            "documentUrl": "http://example.com/doc",
        },
    )

    # Call _to_defaults - this is what we are testing
    defaults = importer._to_defaults(dto)

    print("Defaults keys:", defaults.keys())  # For debugging

    # --- Assertions for fields DIRECTLY handled by _to_defaults ---
    assert "protocol_number" in defaults
    assert defaults["protocol_number"] == test_protocol

    assert "subject" in defaults
    assert defaults["subject"] == test_subject

    # decisionTypeId is in special_handling_fields, so it won't appear in defaults
    assert "decision_type_id" not in defaults

    assert "has_private_data" in defaults  # Check mapped name
    assert defaults["has_private_data"] is True

    assert "status" in defaults
    assert defaults["status"] == DecisionStatus.PUBLISHED

    assert "version_id" in defaults
    assert defaults["version_id"] == test_version_id

    assert "document_url" in defaults
    assert defaults["document_url"] == "http://example.com/doc"

    # --- Assertions for fields NOT handled by _to_defaults ---
    assert "organization_id" not in defaults  # Handled separately
    assert "signer_ids" not in defaults  # Handled separately
    assert "unit_ids" not in defaults  # Handled separately
    assert "attachments" not in defaults  # Handled separately
    assert "financial_year" not in defaults  # Handled by _extract_promoted_fields
    assert "amount" not in defaults  # Handled by _extract_promoted_fields
    assert "currency" not in defaults  # Handled by _extract_promoted_fields
    assert (
        "extra_field_values_json" not in defaults
    )  # Handled by _extract_promoted_fields

    # Ensure UID field itself isn't in defaults
    assert importer.uid_field not in defaults
    assert "ada" not in defaults


# Mark slow if DB interaction is heavy
@pytest.mark.django_db  # Essential for DB operations
def test_import_decisions_full(
    test_organization, test_signers, test_units, test_act_type
):
    """Tests the full import process including relations and updates."""
    importer = DecisionImporter()
    num_decisions = 3
    num_attachments = 2
    num_kae = 2
    specific_kae_codes = [f"KAE{i}" for i in range(num_kae)]

    # Create DTOs using predictable IDs matching fixtures
    decision_dtos = [
        create_decision_dto(
            ada=f"FULLIMPORTADA_{i}",
            org_id=test_organization.uid,  # from fixture
            signer_ids=[s.uid for s in test_signers],  # from fixture
            unit_ids=[u.uid for u in test_units],  # from fixture
            # Make sure this matches the fixture UID
            extra_attributes={"decisionTypeId": test_act_type.uid},
            num_attachments=num_attachments,
            extra_fields_config={
                "financial_year": 2025 - i,
                "has_amount": True,
                "num_kae": num_kae,
                "specific_kae": specific_kae_codes,
            },
        )
        for i in range(num_decisions)
    ]

    # --- Initial Import ---
    initial_count = Decision.objects.count()
    created_count = importer.import_decisions(decision_dtos)

    assert created_count == num_decisions
    assert Decision.objects.count() == initial_count + num_decisions

    # Verify one of the imported decisions in detail
    imported_decision = Decision.objects.get(ada="FULLIMPORTADA_0")
    assert imported_decision.organization == test_organization
    assert imported_decision.subject == decision_dtos[0].subject  # Check basic field
    assert imported_decision.financial_year == 2025
    assert imported_decision.amount is not None
    assert imported_decision.currency == "EUR"
    assert imported_decision.has_private_data == decision_dtos[0].privateData
    assert imported_decision.extra_field_values_json is not None
    assert imported_decision.extra_field_values_json["financialYear"] == 2025

    # Verify relations
    assert imported_decision.signers.count() == len(test_signers)
    assert set(imported_decision.signers.all()) == set(test_signers)
    assert imported_decision.units.count() == len(test_units)
    assert set(imported_decision.units.all()) == set(test_units)
    assert imported_decision.attachments.count() == num_attachments
    assert (
        Attachment.objects.filter(decision=imported_decision).count() == num_attachments
    )
    # Check attachment data (optional)
    first_attachment_dto = decision_dtos[0].attachments[0]
    db_attachment = imported_decision.attachments.get(
        attachment_id=first_attachment_dto.id
    )
    assert db_attachment.filename == first_attachment_dto.filename

    # Verify KAE amounts
    assert imported_decision.kae_amounts.count() == num_kae
    assert (
        DecisionAmountKAE.objects.filter(decision=imported_decision).count() == num_kae
    )
    db_kae = imported_decision.kae_amounts.get(kae=specific_kae_codes[0])
    # Find corresponding DTO KAE amount
    dto_kae_amount = next(
        k.amountWithVAT
        for k in decision_dtos[0].extraFieldValues.amountWithKae
        if k.kae == specific_kae_codes[0]
    )
    assert db_kae.amount == decimal.Decimal(str(dto_kae_amount))

    # --- Test Update (Re-import same data) ---
    # Modify one DTO slightly
    decision_dtos[0].subject = "Updated Subject"
    decision_dtos[0].extraFieldValues.financialYear = 2026  # Update a promoted field
    # Modify attachments (remove one, keep one the same, add one new)
    old_attachment_id_to_keep = decision_dtos[0].attachments[0].id
    new_attachment_dto = create_attachment_dto()
    decision_dtos[0].attachments = [
        decision_dtos[0].attachments[0],  # Keep the first one
        new_attachment_dto,  # Add a new one
    ]
    # Modify KAEs (change amount on one, remove one, add one)
    old_kae_to_update = decision_dtos[0].extraFieldValues.amountWithKae[0]
    old_kae_to_update.amountWithVAT = 9999.99
    new_kae_dto = create_amount_with_kae_dto(kae="NEW_KAE_CODE")
    decision_dtos[0].extraFieldValues.amountWithKae = [
        old_kae_to_update,  # Keep the first one with updated amount
        new_kae_dto,  # Add a new one
    ]

    update_created_count = importer.import_decisions(decision_dtos)

    assert update_created_count == 0  # No new decisions should be created
    assert Decision.objects.count() == initial_count + num_decisions  # Count unchanged

    # Verify updates on the first decision
    updated_decision = Decision.objects.get(ada="FULLIMPORTADA_0")
    assert updated_decision.subject == "Updated Subject"
    assert updated_decision.financial_year == 2026  # Promoted field updated

    # Verify attachment updates
    assert updated_decision.attachments.count() == 2  # Old one removed, new one added
    assert updated_decision.attachments.filter(
        attachment_id=old_attachment_id_to_keep
    ).exists()
    assert updated_decision.attachments.filter(
        attachment_id=new_attachment_dto.id
    ).exists()

    # Verify KAE updates
    assert updated_decision.kae_amounts.count() == 2  # One removed, one added
    updated_kae = updated_decision.kae_amounts.get(kae=old_kae_to_update.kae)
    assert updated_kae.amount == decimal.Decimal("9999.99")
    assert updated_decision.kae_amounts.filter(kae=new_kae_dto.kae).exists()
    assert not updated_decision.kae_amounts.filter(
        kae=specific_kae_codes[1]
    ).exists()  # Verify the second original KAE was removed


import pytest
import vcr
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.decisions import Decision
from core.models.entities import DecisionAmountField, DecisionEntityRelationship


@pytest.mark.django_db(transaction=True)
class TestDecisionImporterIntegration(TransactionTestCase):
    # class TestDecisionImporterIntegration(TestCase):
    """Integration tests for decision import with AFM and amount linking."""

    # Centralized ADA value
    TEST_ADA = "9ΥΘΧΩ9Γ-1Μ6"

    @vcr.use_cassette(f"fixtures/vcr_cassettes/test_ada_{TEST_ADA}.yaml")
    def test_decision_import_with_afm_and_amount_linking(self):
        """Test that AFM entities and amounts are correctly linked after import."""

        # Setup
        importer = DecisionImporter()
        fetcher = DiavgeiaFetcher()

        # Fetch the test decision using centralized ADA
        decision_dto = fetcher.fetch_a_decision(self.TEST_ADA)

        assert decision_dto is not None, f"Could not fetch decision {self.TEST_ADA}"

        # Import the decision
        created_count = importer.import_many([decision_dto])
        assert created_count == 1

        # Verify the decision was created
        decision = Decision.objects.get(ada=self.TEST_ADA)
        assert decision is not None

        # Check that AFM entities were extracted
        relationships = DecisionEntityRelationship.objects.filter(decision=decision)
        assert relationships.count() > 0, "No AFM entities were extracted"

        # Check that amounts were extracted
        amount_fields = DecisionAmountField.objects.filter(decision=decision)
        assert amount_fields.count() > 0, "No amounts were extracted"

        # Check that amounts are linked to entity relationships
        linked_amounts = amount_fields.filter(associated_relationship__isnull=False)
        assert (
            linked_amounts.count() > 0
        ), "No amounts are linked to entity relationships"

        # Verify the linking is correct
        for amount_field in linked_amounts:
            relationship = amount_field.associated_relationship
            assert relationship.decision == decision

            # Extract containers from both paths
            amount_container = (
                amount_field.parent_key_path.rsplit(".", 1)[0]
                if "." in amount_field.parent_key_path
                else amount_field.parent_key_path
            )
            rel_container = (
                relationship.parent_key_path.rsplit(".", 1)[0]
                if "." in relationship.parent_key_path
                else relationship.parent_key_path
            )

            # Now both should be "sponsor[0]"
            assert (
                amount_container == rel_container
            ), f"Container mismatch: {amount_container} != {rel_container}"

    def test_ada_centralization(self):
        """Test that the ADA value is properly centralized."""
        assert self.TEST_ADA == "9ΥΘΧΩ9Γ-1Μ6"
