"""
Tests for ``build_one_liners_by_decision`` and the list-payload wiring
(``paginate_decisions`` renders the one-liner at the top level of each item
dict, batch-fetched with no N+1).
"""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.models.decision_one_liner import DecisionOneLiner, OneLinerStatus
from core.models.one_liner_config import OneLinerConfig
from core.services.decision_projections import (
    build_one_liners_by_decision,
    paginate_decisions,
)

pytestmark = pytest.mark.django_db

CONFIG_KWARGS = dict(
    prompt_kind="batch_one_liner",
    system_prompt="Be brief.",
    prompt_template="Summarize: {{ text }}",
    provider="OPENROUTER",
    model="test/model",
    temperature=0.3,
    max_tokens=3000,
)


def _completed_one_liner(decision, extraction, text="Η σύνοψη.", attempt=1):
    config = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)
    return DecisionOneLiner.objects.create(
        decision=decision,
        extraction=extraction,
        config=config,
        attempt=attempt,
        status=OneLinerStatus.COMPLETED,
        one_liner=text,
        completed_at=timezone.now() + timedelta(minutes=attempt),
    )


class TestBuildOneLinersByDecision:
    def test_empty_ids_return_empty_dict(self):
        assert build_one_liners_by_decision([]) == {}

    def test_returns_default_attempt_shape(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_OL1", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        _completed_one_liner(decision, extraction, text="Εγκρίθηκε δαπάνη.")

        result = build_one_liners_by_decision([decision.id])

        assert decision.id in result
        entry = result[decision.id]
        assert entry["one_liner"] == "Εγκρίθηκε δαπάνη."
        assert entry["model"] == "test/model"
        assert entry["prompt_kind"] == "batch_one_liner"
        assert entry["attempt"] == 1
        assert entry["extraction_provider"] == extraction.extraction_provider
        assert entry["completed_at"] is not None

    def test_prefers_latest_completed(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_OL2", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")

        older = _completed_one_liner(decision, extraction, text="Older.", attempt=1)
        _completed_one_liner(decision, extraction, text="Newer.", attempt=2)

        result = build_one_liners_by_decision([decision.id])
        assert result[decision.id]["one_liner"] == "Newer."
        assert result[decision.id]["attempt"] == 2
        assert older.pk

    def test_ignores_failed_and_empty_rows(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_OL3", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        config = OneLinerConfig.get_or_create_for(**CONFIG_KWARGS)

        DecisionOneLiner.objects.create(
            decision=decision,
            extraction=extraction,
            config=config,
            attempt=1,
            status=OneLinerStatus.FAILED,
            error_message="boom",
        )
        DecisionOneLiner.objects.create(
            decision=decision,
            extraction=extraction,
            config=config,
            attempt=2,
            status=OneLinerStatus.COMPLETED,
            one_liner="",
        )

        assert build_one_liners_by_decision([decision.id]) == {}

    def test_absent_decisions_are_missing_not_null(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        with_row = DecisionFactory(ada="ADA_OL4", decision_type=decision_type)
        without_row = DecisionFactory(ada="ADA_OL5", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=with_row, raw_text="T.")
        _completed_one_liner(with_row, extraction)

        result = build_one_liners_by_decision([with_row.id, without_row.id])
        assert with_row.id in result
        assert without_row.id not in result


class TestPaginateDecisionsOneLiner:
    def test_one_liner_in_paginated_payload(self, decision_type):
        from conftest import DecisionFactory, DocumentExtractionFactory

        decision = DecisionFactory(ada="ADA_PG1", decision_type=decision_type)
        other = DecisionFactory(ada="ADA_PG2", decision_type=decision_type)
        extraction = DocumentExtractionFactory(decision=decision, raw_text="T.")
        _completed_one_liner(decision, extraction, text="Εγκρίθηκε δαπάνη.")

        from core.models.decisions import Decision

        qs = Decision.objects.all()
        payload = paginate_decisions(qs, page=1, page_size=10)

        by_id = {item["id"]: item for item in payload["results"]}
        assert by_id[decision.id]["one_liner"] == "Εγκρίθηκε δαπάνη."
        assert by_id[other.id]["one_liner"] is None

    def test_query_count_does_not_scale_with_page_size(self, decision_type):
        """The one-liner fetch is ONE query for the whole page — no per-item
        N+1 (the pre-existing ai_analyses N+1 in the serializer is out of
        scope and hits both runs equally)."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decisions import Decision

        for i in range(8):
            d = DecisionFactory(ada=f"ADA_PGQ{i}", decision_type=decision_type)
            extraction = DocumentExtractionFactory(decision=d, raw_text=f"T{i}.")
            _completed_one_liner(d, extraction, text=f"Σύνοψη {i}.")

        qs = Decision.objects.all()
        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(qs, page=1, page_size=8)

        one_liner_queries = [
            q for q in ctx.captured_queries if "decisiononeliner" in q["sql"].lower()
        ]
        assert len(one_liner_queries) == 1

    def test_rows_present_add_no_queries_vs_absent(self, decision_type):
        """A page with one-liner rows costs the same as one without — the
        builder is a single bounded query either way."""
        from conftest import DecisionFactory, DocumentExtractionFactory
        from core.models.decisions import Decision

        with_rows = []
        for i in range(4):
            d = DecisionFactory(ada=f"ADA_QA{i}", decision_type=decision_type)
            extraction = DocumentExtractionFactory(decision=d, raw_text=f"T{i}.")
            _completed_one_liner(d, extraction, text=f"Σύνοψη {i}.")
            with_rows.append(d.id)

        without_ids = []
        for i in range(4):
            d = DecisionFactory(ada=f"ADA_QB{i}", decision_type=decision_type)
            without_ids.append(d.id)

        qs = Decision.objects.filter(id__in=with_rows)
        with CaptureQueriesContext(connection) as ctx_with:
            paginate_decisions(qs, page=1, page_size=4)

        qs = Decision.objects.filter(id__in=without_ids)
        with CaptureQueriesContext(connection) as ctx_without:
            paginate_decisions(qs, page=1, page_size=4)

        assert len(ctx_with.captured_queries) == len(ctx_without.captured_queries)
