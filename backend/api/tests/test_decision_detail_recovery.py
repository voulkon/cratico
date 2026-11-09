"""
Decision detail payload for a recovered counterpart.

Once an APPLIED attempt exists, the detail API must stop reporting the raw
self-counterpart warning, expose the recovery metadata, and carry provenance
(`is_inferred`, `metadata_source`, `confidence_score`, attempt id) on the
entity grouping.
"""

from decimal import Decimal

import pytest
from conftest import (
    AFMEntityFactory,
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
    OrganizationFactory,
)
from core.models.counterpart_recovery import CounterpartRecoveryAttempt

pytestmark = pytest.mark.django_db

SELF_AFM = "090064864"
REAL_AFM = "899972873"


def _seed():
    org = OrganizationFactory(vat_number=SELF_AFM)
    decision = DecisionFactory(
        ada="6ΧΩΜ469ΗΣΥ-ΒΗ4",
        organization=org,
        extra_field_values_json={
            "person": [{"afm": SELF_AFM, "afmType": "EL"}],
            "awardAmount": {"amount": 30000.0, "currency": "EUR"},
        },
    )
    entity = AFMEntityFactory(afm=REAL_AFM, name="REAL CONTRACTOR")
    relationship = DecisionEntityRelationshipFactory(
        decision=decision,
        entity=entity,
        role="person",
        parent_key_path="person[0]",
        is_inferred=True,
        metadata_source="OCR_AFM",
        confidence_score=0.92,
    )
    DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="",
        source_field_name="awardAmount",
        amount=Decimal("30000.00"),
        associated_relationship=relationship,
    )
    attempt = CounterpartRecoveryAttempt.objects.create(
        decision=decision,
        method="REGEX_OCR",
        status="APPLIED",
        chosen_afm=REAL_AFM,
        confidence=0.92,
        original_afm=SELF_AFM,
        original_role="person",
        original_parent_key_path="person[0]",
        new_relationship=relationship,
        span_text="ΑΦΜ 899972873",
        evidence={"signals": ["near_afm_keyword"]},
    )
    return decision, relationship, attempt


def test_detail_suppresses_warning_and_exposes_recovery(api_client):
    decision, _, attempt = _seed()

    resp = api_client.get(f"/api/decisions/{decision.id}/")
    assert resp.status_code == 200
    data = resp.json()

    assert data["has_self_counterpart"] is False
    recovery = data["counterpart_recovery"]
    assert recovery["id"] == attempt.id
    assert recovery["status"] == "APPLIED"
    assert recovery["recovered_afm"] == REAL_AFM
    assert recovery["original_afm"] == SELF_AFM
    assert recovery["method"] == "REGEX_OCR"
    assert recovery["confidence"] == pytest.approx(0.92)
    assert recovery["evidence"] == "ΑΦΜ 899972873"


def test_entities_include_recovery_provenance(api_client):
    decision, relationship, attempt = _seed()

    resp = api_client.get(f"/api/decisions/{decision.id}/entities/")
    assert resp.status_code == 200
    rows = resp.json()["relationships"]
    assert len(rows) == 1

    row = rows[0]
    assert row["entity"]["afm"] == REAL_AFM
    assert row["is_inferred"] is True
    assert row["metadata_source"] == "OCR_AFM"
    assert row["confidence_score"] == pytest.approx(0.92)
    assert row["recovery_attempt_id"] == attempt.id
    assert row["total_amount"] == 30000.0
