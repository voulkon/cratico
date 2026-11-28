"""
Regression tests for the per-entity amount aggregation in
``/api/decisions/<ref>/entities/``.

``effective_linked_amount_sum`` joins ``linked_amounts``, so a relationship
with several amount rows fans out.  ``occurrences`` must count relationship
rows, not relationship × amount rows, and the currency must not split the
group.
"""

import pytest
from conftest import (
    AFMEntityFactory,
    DecisionAmountFieldFactory,
    DecisionEntityRelationshipFactory,
    DecisionFactory,
)

pytestmark = pytest.mark.django_db


def _relationship(decision, entity, role="sponsorAFMName", path="sponsor[0]"):
    return DecisionEntityRelationshipFactory(
        decision=decision,
        entity=entity,
        role=role,
        parent_key_path=path,
    )


def test_occurrences_count_relationships_not_amount_rows(api_client):
    decision = DecisionFactory(ada="ENTITIES-1")
    entity = AFMEntityFactory(afm="911111111")
    relationship = _relationship(decision, entity)

    DecisionAmountFieldFactory(
        decision=decision,
        amount=100,
        parent_key_path="sponsor[0].expenseAmount",
        associated_relationship=relationship,
    )
    DecisionAmountFieldFactory(
        decision=decision,
        amount=50,
        parent_key_path="sponsor[0].awardAmount",
        associated_relationship=relationship,
    )

    response = api_client.get(f"/api/decisions/{decision.id}/entities/")

    assert response.status_code == 200
    rows = response.json()["relationships"]
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 1
    assert rows[0]["total_amount"] == 150.0
    assert rows[0]["currency"] == "EUR"


def test_same_role_and_entity_counts_each_relationship(api_client):
    decision = DecisionFactory(ada="ENTITIES-2")
    entity = AFMEntityFactory(afm="922222222")
    first = _relationship(decision, entity, path="sponsor[0]")
    second = _relationship(decision, entity, path="sponsor[1]")

    DecisionAmountFieldFactory(
        decision=decision,
        amount=100,
        parent_key_path="sponsor[0].expenseAmount",
        associated_relationship=first,
    )
    DecisionAmountFieldFactory(
        decision=decision,
        amount=50,
        parent_key_path="sponsor[1].expenseAmount",
        associated_relationship=second,
    )

    response = api_client.get(f"/api/decisions/{decision.id}/entities/")

    assert response.status_code == 200
    rows = response.json()["relationships"]
    assert len(rows) == 1
    assert rows[0]["occurrences"] == 2
    assert rows[0]["total_amount"] == 150.0
    assert sorted(rows[0]["parent_key_paths"]) == ["sponsor[0]", "sponsor[1]"]
