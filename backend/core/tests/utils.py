import json
import pickle
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import choice, randint, random
from typing import Any, Dict, List, Optional

from diavgeia_api.models.decisions import Amount as AmountDTO
from diavgeia_api.models.decisions import AmountWithKAE as AmountWithKAEDTO
from diavgeia_api.models.decisions import Attachment as AttachmentDTO
from diavgeia_api.models.decisions import Decision as DecisionDTO
from diavgeia_api.models.decisions import DecisionStatus
from diavgeia_api.models.decisions import ExtraFieldValues as ExtraFieldValuesDTO
from faker import Faker

ROOT = Path(__file__).parent

faker = Faker()


def load_json_fixture(name: str):
    fixtures_path: Path = ROOT / "data" / "fixtures" / name
    with open(fixtures_path, "r", encoding="utf-8") as fp:
        return json.load(fp)


def load_pickle_fixture(name: str, fixtures_folder: str = "heavy_fixtures"):
    fixtures_path: Path = ROOT / "data" / fixtures_folder / name
    with open(fixtures_path, "rb") as fp:
        return pickle.load(fp)


def save_pickle_fixture(data, name: str, fixtures_folder: str = "heavy_fixtures"):
    fixtures_path: Path = ROOT / "data" / fixtures_folder / name
    fixtures_path.parent.mkdir(parents=True, exist_ok=True)
    with open(fixtures_path, "wb") as fp:
        pickle.dump(data, fp)


# --- Test Helper ---


def create_attachment_dto(id: Optional[str] = None) -> AttachmentDTO:
    """Helper to create a test Attachment DTO."""
    return AttachmentDTO(
        id=id or str(uuid.uuid4()),
        description=faker.sentence() if random() > 0.2 else None,
        filename=faker.file_name(extension="pdf"),
        mimeType="application/pdf",
        checksum=faker.sha256(),
    )


def create_amount_dto(
    amount: Optional[float] = None, currency: str = "EUR"
) -> AmountDTO:
    """Helper to create a test Amount DTO."""
    return AmountDTO(
        amount=amount if amount is not None else round(random() * 10000, 2),
        currency=currency,
    )


def create_amount_with_kae_dto(
    kae: Optional[str] = None, amount: Optional[float] = None
) -> AmountWithKAEDTO:
    """Helper to create a test AmountWithKAE DTO."""
    return AmountWithKAEDTO(
        kae=kae or f"{randint(1000,9999)}.{randint(100,999)}",
        amountWithVAT=amount if amount is not None else round(random() * 1000, 2),
    )


def create_extra_field_values_dto(
    financial_year: Optional[int] = None,
    has_amount: bool = True,
    num_kae: int = 0,
    specific_kae: Optional[List[str]] = None,
) -> Optional[ExtraFieldValuesDTO]:
    """Helper to create test ExtraFieldValues DTO."""
    if not has_amount and num_kae == 0 and financial_year is None:
        return None  # Don't create if no relevant data

    year = (
        financial_year
        if financial_year is not None
        else datetime.now().year - randint(0, 5)
    )
    amount_vat = None
    award_amount = None
    kae_amounts = []

    if has_amount:
        # Randomly choose between amountWithVAT and awardAmount or both
        if random() > 0.3:
            amount_vat = create_amount_dto()
        if random() > 0.3:
            award_amount = create_amount_dto()
        # Ensure at least one amount exists if has_amount is True
        if not amount_vat and not award_amount:
            amount_vat = create_amount_dto()

    if num_kae > 0:
        kae_list = specific_kae or [None] * num_kae
        kae_amounts = [
            create_amount_with_kae_dto(kae=kae_list[i]) for i in range(num_kae)
        ]
        # Often, if KAE exists, amountWithVAT reflects the total KAE sum
        if kae_amounts and not amount_vat:
            total_kae_amount = sum(k.amountWithVAT for k in kae_amounts)
            amount_vat = create_amount_dto(amount=total_kae_amount)

    return ExtraFieldValuesDTO(
        financialYear=year,
        amountWithVAT=amount_vat,
        awardAmount=award_amount,  # Can be None
        amountWithKae=kae_amounts or None,  # API might expect null/omit if empty
        # Add other optional fields if needed for testing
        budgettype=faker.word() if random() > 0.7 else None,
    )


def create_decision_dto(
    ada: Optional[str] = None,
    org_id: str = "org_test_1",  # Use predictable IDs for tests
    signer_ids: Optional[List[str]] = None,
    unit_ids: Optional[List[str]] = None,
    num_attachments: int = 1,
    extra_fields_config: Optional[Dict[str, Any]] = None,
    extra_attributes: Optional[Dict[str, Any]] = None,
) -> DecisionDTO:
    """
    Helper method to create a more structured Decision DTO for testing.

    Args:
        ada: Specific ADA or random UUID if None.
        org_id: The organization ID string (must exist in test DB).
        signer_ids: List of signer ID strings (must exist in test DB).
        unit_ids: List of unit ID strings (must exist in test DB).
        num_attachments: How many attachment DTOs to generate.
        extra_fields_config: Dict to configure ExtraFieldValuesDTO generation
                             (e.g., {'has_amount': True, 'num_kae': 2}).
        extra_attributes: Optional dictionary of top-level DTO attributes to override.
    """
    if ada is None:
        ada = f"TESTADA-{uuid.uuid4()}"

    now = datetime.now(timezone.utc)
    issue_date = now - timedelta(days=randint(1, 365))
    submission_ts = issue_date + timedelta(hours=randint(1, 24))
    publish_ts = (
        submission_ts + timedelta(hours=randint(1, 10)) if random() > 0.2 else None
    )

    # Defaults for related IDs if not provided
    if signer_ids is None:
        signer_ids = [f"signer_test_{i+1}" for i in range(randint(1, 2))]
    if unit_ids is None:
        unit_ids = [f"unit_test_{i+1}" for i in range(randint(1, 2))]

    # Create extra fields based on config
    efv_config = extra_fields_config or {}
    extra_values = create_extra_field_values_dto(**efv_config)

    # Create attachment DTOs
    attachments = [create_attachment_dto() for _ in range(num_attachments)]

    # Create base decision DTO
    decision_data = {
        "protocolNumber": f"PROTO-{randint(1000, 9999)}",
        "subject": faker.sentence(nb_words=10),
        "issueDate": issue_date,
        "organizationId": org_id,
        "signerIds": signer_ids,
        "unitIds": unit_ids,
        "decisionTypeId": f"dtype_{randint(1, 5)}",
        "thematicCategoryIds": [
            f"theme_{randint(10, 20)}.{randint(1,5)}" for _ in range(randint(1, 3))
        ],
        "privateData": bool(randint(0, 1)),
        "submissionTimestamp": submission_ts,
        "publishTimestamp": publish_ts,
        "status": choice([s for s in DecisionStatus if s != DecisionStatus.ALL]),
        "ada": ada,
        "versionId": str(uuid.uuid4()),
        "correctedVersionId": str(uuid.uuid4()) if random() > 0.8 else None,
        "documentUrl": faker.url() if random() > 0.3 else None,
        "documentChecksum": faker.sha256() if random() > 0.3 else None,
        "url": f"https://diavgeia.gov.gr/decision/view/{ada}" if ada else None,
        "attachments": attachments,
        "warnings": faker.sentence() if random() > 0.7 else None,
        "extraFieldValues": extra_values,
    }

    # Override attributes if provided
    if extra_attributes:
        decision_data.update(extra_attributes)

    # Use Pydantic validation
    decision_dto = DecisionDTO(**decision_data)

    return decision_dto


def create_db_decision(ada=None, as_model=False, **kwargs):
    """
    Create a mock Decision for testing

    Args:
        ada: Optional ADA identifier
        as_model: If True, return a Django model instance instead of DTO
        **kwargs: Additional attributes to override

    Returns:
        Either a DTO object or a Django model instance
    """
    # Create the DTO first (your existing implementation)
    decision_dto = create_decision_dto(ada, **kwargs)

    # If model not requested, return the DTO
    if not as_model:
        return decision_dto

    # Convert DTO to model
    from core.importers.decisions import DecisionImporter

    # Either use your importer if it supports single-object imports
    importer = DecisionImporter()
    return importer.import_many([decision_dto])


def create_search_response(total=10, page=0, size=500, actualSize=None, decisions=None):
    """Helper method to create a SearchResponse object for testing"""
    from diavgeia_api.models.search import SearchInfo, SearchResponse

    if actualSize is None:
        actualSize = min(size, total - (page * size))

    if decisions is None:
        decisions = [create_decision_dto(ada=f"ada{i}") for i in range(actualSize)]

    info = SearchInfo(
        query=faker.sentence(nb_words=3),  # <- generate a fake query
        page=page,
        size=size,
        actualSize=actualSize,
        total=total,
        order="asc",  # <- or "desc", or random.choice(["asc", "desc"])
    )

    return SearchResponse(info=info, decisions=decisions)
