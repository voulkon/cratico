"""
Targeted AFMEntityStats recomputation used by counterpart recovery.

``compute_entities`` must refresh only the affected entities (old + new) and
reflect the moved relationship without re-gathering the whole table.
"""

from decimal import Decimal

import pytest
from conftest import (
    AFMEntityFactory,
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
)
from core.models.afm_entity_stats import AFMEntityStats
from core.models.types import ActType
from core.services.afm_entity_stats_service import AFMEntityStatsService

pytestmark = pytest.mark.django_db


@pytest.fixture
def payment_type():
    act, _ = ActType.objects.get_or_create(
        uid="Β.2.2", defaults={"label": "Πληρωμή"}
    )
    return act


def test_recompute_after_relationship_move(payment_type):
    old_entity = AFMEntityFactory(afm="090064864", name="SELF")
    new_entity = AFMEntityFactory(afm="899972873", name="REAL")

    decision = DecisionFactory(decision_type=payment_type)
    relationship = DecisionEntityRelationshipFactory(
        decision=decision,
        entity=old_entity,
        role="person",
        parent_key_path="person[0]",
    )
    DecisionAmountFieldFactory(
        decision=decision,
        parent_key_path="",
        source_field_name="awardAmount",
        amount=Decimal("30000.00"),
        associated_relationship=relationship,
    )

    # Simulate the recovery in-place repoint.
    relationship.entity = new_entity
    relationship.is_inferred = True
    relationship.metadata_source = "OCR_AFM"
    relationship.save(update_fields=["entity", "is_inferred", "metadata_source"])

    AFMEntityStatsService().compute_entities([old_entity.id, new_entity.id])

    new_stats = AFMEntityStats.objects.get(entity_id=new_entity.id)
    old_stats = AFMEntityStats.objects.get(entity_id=old_entity.id)

    assert new_stats.total_decisions == 1
    assert new_stats.total_amount == Decimal("30000.00")
    assert new_stats.max_single_amount == Decimal("30000.00")
    assert new_stats.average_amount_per_decision == Decimal("30000.00")
    assert new_stats.total_received_amount == Decimal("30000.00")
    assert new_stats.payment_30k_38k == 1

    assert old_stats.total_decisions == 0
    assert old_stats.total_amount == Decimal("0.00")
    assert old_stats.total_received_amount == Decimal("0.00")
