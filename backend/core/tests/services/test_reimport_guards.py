"""
Re-import guards for every relationship writer.

The raw Diavgeia JSON keeps the old self-as-counterpart AFM forever, so each
writer must skip AFMs replaced by an APPLIED recovery attempt.  The unified
``EntityAmountExtractionService`` path is covered in
test_counterpart_recovery.py; these are the two legacy writers.
"""

import pytest
from conftest import AFMEntityFactory, DecisionFactory
from core.models.counterpart_recovery import CounterpartRecoveryAttempt
from core.models.entities import DecisionEntityRelationship

pytestmark = pytest.mark.django_db

SELF_AFM = "090064864"


def _decision_with_applied_attempt():
    decision = DecisionFactory(
        extra_field_values_json={
            "person": [{"afm": SELF_AFM, "afmType": "EL", "name": "SELF"}]
        }
    )
    CounterpartRecoveryAttempt.objects.create(
        decision=decision,
        method="REGEX_OCR",
        status="APPLIED",
        chosen_afm="899972873",
        original_afm=SELF_AFM,
    )
    return decision


def test_entity_extraction_service_skips_superseded_afm():
    from core.services.entity_extraction_service import EntityExtractionService

    decision = _decision_with_applied_attempt()
    entity = AFMEntityFactory(afm=SELF_AFM)

    result = EntityExtractionService()._create_decision_entity_relationship(
        decision, entity, "person", "person[0]", {"afm": SELF_AFM}
    )

    assert result is None
    assert not DecisionEntityRelationship.objects.filter(
        decision=decision, entity__afm=SELF_AFM
    ).exists()


def test_afm_extractor_skips_superseded_afm():
    from core.services.afm_extractor import AFMExtractionService

    decision = _decision_with_applied_attempt()

    AFMExtractionService()._save_entities_to_database(
        decision,
        [
            {
                "afm": SELF_AFM,
                "entity_type": "person",
                "name": "SELF",
                "role": "person",
                "parent_key_path": "person[0]",
                "raw_context": {"afm": SELF_AFM, "afmType": "EL"},
                "confidence": 1.0,
                "source_field_name": "person",
            }
        ],
    )

    assert not DecisionEntityRelationship.objects.filter(
        decision=decision, entity__afm=SELF_AFM
    ).exists()
