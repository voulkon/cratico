"""
Step 3 list-payload tests.

The organization page list used to:
  - join ``text_extraction`` for every row just to compute
    ``bool(raw_text)`` (pulling the wide ``raw_text`` / ``search_vector``
    TOAST columns), and
  - run one ``ai_analyses`` query per row.

These tests lock in the replacement: an ``Exists`` annotation for
``has_document_content``, one bounded ``ai_analyses`` prefetch, ``.only()``
column pruning, and a query count that does not grow with page size.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models.decision_ai_analysis import AnalysisStatus, DecisionAIAnalysis
from core.models.decisions import Decision
from core.services.decision_projections import (
    DEFAULT_LIST_ONLY_FIELDS,
    paginate_decisions,
)

pytestmark = pytest.mark.django_db


def _make_decision(ada, decision_type, **kwargs):
    from conftest import DecisionFactory

    return DecisionFactory(ada=ada, decision_type=decision_type, **kwargs)


def _make_extraction(decision, status="COMPLETED", raw_text="Some text."):
    from conftest import DocumentExtractionFactory

    return DocumentExtractionFactory(
        decision=decision,
        extraction_status=status,
        raw_text=raw_text,
    )


def _make_analysis(decision, status=AnalysisStatus.COMPLETED, summary="Summary."):
    return DecisionAIAnalysis.objects.create(
        decision=decision,
        status=status,
        summary=summary,
        model_used="test/model",
    )


def _result_by_id(payload):
    return {item["id"]: item for item in payload["results"]}


def _page_queries(ctx):
    """The paginator's page SELECT (not the COUNT(*), not prefetches)."""
    return [
        q["sql"]
        for q in ctx.captured_queries
        if 'FROM "core_decision"' in q["sql"] and "LIMIT" in q["sql"]
    ]


class TestHasDocumentContent:

    def test_completed_with_text_is_true(self, decision_type):
        decision = _make_decision("DOC-TRUE", decision_type)
        _make_extraction(decision, "COMPLETED", "Extracted body.")

        payload = paginate_decisions(Decision.objects.all(), page_size=10)

        assert _result_by_id(payload)[decision.id]["has_document_content"] is True

    @pytest.mark.parametrize(
        "ada,status,raw_text",
        [
            ("DOCF-EMPTY", "COMPLETED", ""),
            ("DOCF-NULL", "COMPLETED", None),
            ("DOCF-PENDING", "PENDING", "Some text."),
            ("DOCF-FAILED", "FAILED", "Some text."),
            ("DOCF-PROC", "PROCESSING", "Some text."),
        ],
    )
    def test_no_usable_content_is_false(self, decision_type, ada, status, raw_text):
        decision = _make_decision(ada, decision_type)
        _make_extraction(decision, status, raw_text)

        payload = paginate_decisions(Decision.objects.all(), page_size=10)

        assert _result_by_id(payload)[decision.id]["has_document_content"] is False

    def test_missing_extraction_is_false(self, decision_type):
        decision = _make_decision("DOC-MISSING", decision_type)

        payload = paginate_decisions(Decision.objects.all(), page_size=10)

        assert _result_by_id(payload)[decision.id]["has_document_content"] is False

    def test_matches_legacy_serializer_value(self, decision_type):
        """The annotation and the old text_extraction check agree."""
        from api.views.search.base import serialize_decision_with_content_info

        decision = _make_decision("DOC-LEGACY", decision_type)
        _make_extraction(decision, "COMPLETED", "Body.")

        legacy = serialize_decision_with_content_info(
            Decision.objects.select_related("text_extraction")
            .prefetch_related("kae_amounts", "signers", "ai_analyses")
            .get(pk=decision.pk)
        )
        payload = paginate_decisions(Decision.objects.all(), page_size=10)

        assert (
            _result_by_id(payload)[decision.id]["has_document_content"]
            == legacy["has_document_content"]
        )


class TestListQueryPruning:

    def test_page_query_does_not_join_extraction_table(self, decision_type):
        decision = _make_decision("PRUNE-JOIN", decision_type)
        _make_extraction(decision)

        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(Decision.objects.all(), page_size=10)

        page_sql = _page_queries(ctx)
        assert len(page_sql) == 1
        # The Exists subquery may still reference the table, but the page
        # query must not LEFT JOIN the wide extraction row into every row.
        assert 'LEFT OUTER JOIN "core_documentextraction"' not in page_sql[0]
        assert 'JOIN "core_documentextraction"' not in page_sql[0]
        assert '"has_document_content"' in page_sql[0]

    def test_page_query_selects_only_serializer_fields(self, decision_type):
        decision = _make_decision("PRUNE-ONLY", decision_type)
        _make_extraction(decision)

        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(Decision.objects.all(), page_size=10)

        page_sql = _page_queries(ctx)[0]
        # ``version_id`` is a normal Decision column the card never reads.
        assert '"core_decision"."version_id"' not in page_sql
        for field in (
            "ada",
            "subject",
            "issue_date_day",
            "amount",
            "status",
            "document_url",
        ):
            assert f'"core_decision"."{field}"' in page_sql

    def test_paginator_count_excludes_document_annotation(self, decision_type):
        for i in range(3):
            decision = _make_decision(f"COUNT-{i}", decision_type)
            _make_extraction(decision)

        with CaptureQueriesContext(connection) as ctx:
            payload = paginate_decisions(Decision.objects.all(), page_size=2)

        count_sql = [
            q["sql"]
            for q in ctx.captured_queries
            if q["sql"].lstrip().upper().startswith("SELECT COUNT(")
        ]
        assert len(count_sql) == 1
        assert "has_document_content" not in count_sql[0]
        assert "core_documentextraction" not in count_sql[0]
        assert payload["pagination"]["total_count"] == 3

    def test_custom_serializer_is_not_pruned(self, decision_type):
        """A custom serialize_fn keeps the full row (only_fields opt-in)."""
        _make_decision("PRUNE-CUSTOM", decision_type, version_id="custom-version")
        seen = {}

        def serialize_fn(obj, entity_rels):
            seen["version_id"] = obj.version_id
            return {"id": obj.id}

        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(
                Decision.objects.all(),
                page_size=10,
                serialize_fn=serialize_fn,
            )

        assert seen["version_id"] == "custom-version"
        deferred_loads = [
            q["sql"]
            for q in ctx.captured_queries
            if 'WHERE "core_decision"."id" =' in q["sql"]
        ]
        assert deferred_loads == []

    def test_explicit_only_fields_equals_default(self):
        assert DEFAULT_LIST_ONLY_FIELDS[0] == "id"
        assert "organization__label" in DEFAULT_LIST_ONLY_FIELDS
        assert "decision_type__uid" in DEFAULT_LIST_ONLY_FIELDS


class TestAIAnimationsBatch:

    def test_analyses_are_fetched_in_one_query(self, decision_type):
        decisions = []
        for i in range(6):
            d = _make_decision(f"AI-{i}", decision_type)
            _make_analysis(d, summary=f"Summary {i}.")
            decisions.append(d)

        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(Decision.objects.all(), page_size=10)

        analyses_queries = [
            q for q in ctx.captured_queries if "core_decisionaianalysis" in q["sql"]
        ]
        assert len(analyses_queries) == 1

    def test_payload_matches_completed_with_summary_contract(self, decision_type):
        decision = _make_decision("AI-CONTRACT", decision_type)
        _make_analysis(decision, AnalysisStatus.COMPLETED, "Kept summary.")
        _make_analysis(decision, AnalysisStatus.COMPLETED, "")
        _make_analysis(decision, AnalysisStatus.RUNNING, "Still running.")
        _make_analysis(decision, AnalysisStatus.FAILED, "Failed.")

        payload = paginate_decisions(Decision.objects.all(), page_size=10)
        analyses = _result_by_id(payload)[decision.id]["ai_analyses"]

        assert [a["summary"] for a in analyses] == ["Kept summary."]
        assert analyses[0]["status"] == AnalysisStatus.COMPLETED

    def test_analyses_query_is_bounded_even_with_many_rows(self, decision_type):
        for i in range(20):
            d = _make_decision(f"AI-MANY-{i}", decision_type)
            _make_analysis(d, summary=f"S{i}.")

        with CaptureQueriesContext(connection) as ctx:
            paginate_decisions(Decision.objects.all(), page_size=20)

        analyses_queries = [
            q for q in ctx.captured_queries if "core_decisionaianalysis" in q["sql"]
        ]
        assert len(analyses_queries) == 1


class TestQueryCountConstant:

    def _seed(self, decision_type, count):
        from conftest import (
            DecisionAmountFieldFactory,
            DecisionEntityRelationshipFactory,
            SignerFactory,
            UnitFactory,
        )

        for i in range(count):
            d = _make_decision(f"QC-{count}-{i}", decision_type)
            d.signers.add(SignerFactory())
            d.units.add(UnitFactory())
            _make_extraction(d)
            _make_analysis(d, summary=f"Summary {i}.")
            DecisionAmountFieldFactory(decision=d, amount=100 + i)
            DecisionEntityRelationshipFactory(decision=d)

    def test_query_count_does_not_scale_with_page_size(self, decision_type):
        """A page of 20 costs the same number of queries as a page of 1."""
        self._seed(decision_type, count=20)

        with CaptureQueriesContext(connection) as small:
            paginate_decisions(Decision.objects.order_by("id"), page=1, page_size=1)
        with CaptureQueriesContext(connection) as large:
            paginate_decisions(Decision.objects.order_by("id"), page=1, page_size=20)

        assert len(large.captured_queries) == len(small.captured_queries)

    def test_second_page_costs_the_same(self, decision_type):
        self._seed(decision_type, count=20)

        with CaptureQueriesContext(connection) as first:
            paginate_decisions(Decision.objects.order_by("id"), page=1, page_size=10)
        with CaptureQueriesContext(connection) as second:
            paginate_decisions(Decision.objects.order_by("id"), page=2, page_size=10)

        assert len(second.captured_queries) == len(first.captured_queries)
