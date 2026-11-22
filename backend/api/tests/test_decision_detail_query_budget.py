"""
Query-budget regression tests for the expanded decision card.

The card now fetches ``GET /api/decisions/<id>/`` only when a section is
expanded.  That single request must stay within a fixed query budget: its
related collections (signers, units, KAEs, attachments, entity
relationships, amount fields, AI analyses) are prefetched once per request,
so the cost does not grow with the number of related rows.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models.decision_ai_analysis import AnalysisStatus, DecisionAIAnalysis


def _detail_queries(api_client, decision):
    with CaptureQueriesContext(connection) as ctx:
        response = api_client.get(f"/api/decisions/{decision.id}/")
    assert response.status_code == 200
    return [q["sql"] for q in ctx.captured_queries]


def _count_table(queries, table):
    marker = f'FROM "{table}"'
    return len([sql for sql in queries if marker in sql])


def _add_relations(decision, *, signers=0, units=0, analyses=0, amount_fields=0):
    from conftest import (
        AFMEntityFactory,
        DecisionAmountFieldFactory,
        DecisionEntityRelationshipFactory,
        SignerFactory,
        UnitFactory,
    )

    for _ in range(signers):
        decision.signers.add(SignerFactory())
    for _ in range(units):
        decision.units.add(UnitFactory())
    for i in range(analyses):
        DecisionAIAnalysis.objects.create(
            decision=decision,
            status=AnalysisStatus.COMPLETED,
            summary=f"Summary {i}.",
            model_used="test/model",
        )
    for i in range(amount_fields):
        DecisionAmountFieldFactory(decision=decision, amount=100 + i)
        DecisionEntityRelationshipFactory(decision=decision, entity=AFMEntityFactory())


@pytest.mark.django_db
class TestDecisionDetailQueryBudget:
    def test_related_collections_use_one_query_each(self, api_client, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="QBUDGET-ONE", decision_type=decision_type)
        DocumentExtractionFactory(decision=decision, raw_text="Body.")
        _add_relations(decision, signers=6, units=6, analyses=4, amount_fields=4)

        queries = _detail_queries(api_client, decision)

        assert _count_table(queries, "core_signer") == 1
        assert _count_table(queries, "core_unit") == 1
        assert _count_table(queries, "core_decisionamountkae") == 1
        assert _count_table(queries, "core_attachment") == 1
        assert _count_table(queries, "core_decisionentityrelationship") == 1
        assert _count_table(queries, "core_afmentity") == 1
        assert _count_table(queries, "core_decisionaianalysis") == 1
        assert _count_table(queries, "core_decisionamountfield") == 1

    def test_detail_stays_within_a_fixed_budget(self, api_client, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="QBUDGET-CAP", decision_type=decision_type)
        DocumentExtractionFactory(decision=decision, raw_text="Body.")
        _add_relations(decision, signers=6, units=6, analyses=4, amount_fields=4)

        assert len(_detail_queries(api_client, decision)) <= 20
