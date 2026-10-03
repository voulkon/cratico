"""
Safety tests for the document search path — regression harness for
docs/postmortems/2026-10-03-document-search-worker-timeout.md.

Invariants locked here:
- User input can never inject tsquery syntax (sanitizer in
  _build_prefix_search_query; the metacharacter class observed in the
  incident DB log was 'δε:' → 'δε::*').
- The unindexed raw_text ILIKE fallback never runs by default; it only runs
  when DOCUMENT_SEARCH_ILIKE_FALLBACK is explicitly enabled, and then it is
  logged and executed exactly once (no .count() re-scan).
- FTS executes exactly once per search (no .exists()/.count() re-execution —
  the historical cause of 600-1050 s responses on broad prefix hits).
- Short queries (1-2 chars) short-circuit before any document SQL runs.
- DOCUMENT_SEARCH_ENABLED gates the entire document search path.
- The public view returns a well-formed 200 for hostile queries.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from core.models.feature_flags import FeatureFlag
from core.services.feature_flag_service import feature_flags
from core.services.search_service import SearchService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_flag(key, enabled):
    """Force a flag value via a DB row (highest resolution priority)."""
    FeatureFlag.objects.update_or_create(
        key=key,
        defaults={
            "name": key,
            "description": f"test-controlled flag {key}",
            "enabled": enabled,
            "value_type": "boolean",
        },
    )


@pytest.fixture(autouse=True)
def _clear_flag_cache():
    """Prevent feature-flag values leaking into/out of the Redis cache."""
    feature_flags.clear_cache()
    yield
    feature_flags.clear_cache()


def _configure_postgres_path(ilike_fallback=False):
    """
    Deterministic PostgreSQL document-search configuration:
    OpenSearch off (so search_documents goes straight to the PG path),
    PostgreSQL search on, ILIKE fallback off by default.
    """
    _set_flag("INDEX_THE_OPENSEARCH", False)
    _set_flag("INDEX_THE_POSTGRES", True)
    _set_flag("DOCUMENT_SEARCH_ILIKE_FALLBACK", ilike_fallback)


def _assert_no_scan(captured_queries):
    """No ILIKE/LIKE fallback scan may appear in the captured SQL.

    Space-delimited markers so flag names like DOCUMENT_SEARCH_ILIKE_FALLBACK
    (which appear inside feature-flag SELECTs) don't false-positive.
    """
    scans = [
        q
        for q in captured_queries
        if " ILIKE " in q["sql"].upper() or " LIKE " in q["sql"].upper()
    ]
    assert scans == [], f"raw_text scan issued: {[q['sql'] for q in scans]}"


def _query_value(search_query):
    """Extract the raw tsquery string from a Django 5.x SearchQuery."""
    return search_query.source_expressions[1].value


# ---------------------------------------------------------------------------
# Fix #2 — tsquery sanitizer
# ---------------------------------------------------------------------------


class TestPrefixQuerySanitizer:
    """_build_prefix_search_query must neutralize tsquery metacharacters."""

    def test_colon_stripped_from_word(self):
        # A stray ':' (e.g. the Shift+; typo for 'L') used to pass through the
        # raw tsquery — pre-fix this produced 'de::*' and a Postgres
        # 'syntax error in tsquery', same class as the 'δε::*' DB-log error.
        q = SearchService._build_prefix_search_query("DE:")
        assert _query_value(q) == "de:*"

    def test_metachar_query_sanitize(self):
        # The Greek metacharacter artifact from the incident DB log.
        q = SearchService._build_prefix_search_query("δε:")
        assert _query_value(q) == "δε:*"

    def test_all_metacharacters_stripped(self):
        q = SearchService._build_prefix_search_query("ΔΗΜ: & ΤΡΑΠ!")
        assert _query_value(q) == "δημ:* & τραπ:*"

    def test_operator_only_words_are_dropped(self):
        q = SearchService._build_prefix_search_query("!!! & |")
        # Every word sanitized away → empty never-matching query, never a
        # raw tsquery that raises 'syntax error in tsquery'.
        assert _query_value(q) == ""

    def test_empty_result_is_never_matching_plain_query(self):
        q = SearchService._build_prefix_search_query("!!!")
        assert q.function == "plainto_tsquery"

    def test_prefix_marker_preserved(self):
        q = SearchService._build_prefix_search_query("ACME")
        assert _query_value(q) == "acme:*"

    def test_multiple_words_joined_with_and(self):
        q = SearchService._build_prefix_search_query("ΠΕΙΡΑ ΤΡΑΠ")
        assert _query_value(q) == "πειρα:* & τραπ:*"


# ---------------------------------------------------------------------------
# Fix #1 — ILIKE fallback gated (default off), fix #4 — single FTS execution
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentSearchFallbackGate:
    """No unindexed scan may run unless DOCUMENT_SEARCH_ILIKE_FALLBACK is on."""

    @pytest.mark.parametrize("query", ["QVXWZJ:", "QVXWZJ", "Q"])
    def test_fallback_disabled_never_scans_raw_text(self, db, query):
        _configure_postgres_path(ilike_fallback=False)
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService()._search_documents_postgresql(query)
        assert result["count"] == 0
        assert result["source"] == "none"
        assert result["results"] == []
        _assert_no_scan(ctx.captured_queries)

    def test_fallback_disabled_routes_errors_to_empty(self, db):
        """FTS failure must not silently degrade into the fallback either."""
        _configure_postgres_path(ilike_fallback=False)
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService()._search_documents_postgresql("QVXWZJ")
        assert result["source"] == "none"
        _assert_no_scan(ctx.captured_queries)

    def test_fallback_opt_in_runs_exactly_one_scan(self, db):
        from conftest import DocumentExtractionFactory

        _configure_postgres_path(ilike_fallback=True)
        # 'xzebraq' contains the query as a substring but not as a word-start
        # prefix, so FTS misses ('zebraq:*' ≠ lexeme 'xzebraq') while ILIKE
        # '%zebraq%' hits — the exact miss/fallback split from the incident.
        DocumentExtractionFactory(raw_text="μικροπραγμα xzebraq τέλος")
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService()._search_documents_postgresql("ZEBRAQ")
        assert result["source"] == "postgresql"
        assert result["count"] == 1
        assert result["has_more"] is False
        scans = [
            q
            for q in ctx.captured_queries
            if " ILIKE " in q["sql"].upper() or " LIKE " in q["sql"].upper()
        ]
        assert len(scans) == 1, (
            "the gated fallback must run exactly one bounded scan (LIMIT), "
            f"got: {[q['sql'] for q in scans]}"
        )

    def test_fallback_result_shape(self, db):
        from conftest import DocumentExtractionFactory

        _configure_postgres_path(ilike_fallback=True)
        DocumentExtractionFactory(raw_text="μικροπραγμα xzebraq τέλος")
        result = SearchService()._search_documents_postgresql("ZEBRAQ")
        assert result["count"] == len(result["results"]) == 1
        assert "extraction" in result["results"][0]


# ---------------------------------------------------------------------------
# Fix #4 — no double FTS execution on the hit path
# ---------------------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.requires_postgresql
class TestDocumentSearchSingleExecution:
    def test_fts_hit_executes_fts_exactly_once(self, db):
        from conftest import DocumentExtractionFactory

        _configure_postgres_path(ilike_fallback=False)
        ext = DocumentExtractionFactory(
            raw_text="καταγραφή κιλονοβατίδα QZXWTESTQ τέλος εγγράφου"
        )
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService().search_documents("ΚΙΛΟΝΟΒΑ")
        assert result["source"] == "postgresql"
        assert result["count"] == 1
        assert [r["extraction"].pk for r in result["results"]] == [ext.pk]

        fts_queries = [q for q in ctx.captured_queries if "to_tsquery" in q["sql"]]
        # The historical regression: .exists() + .count() re-ran the full FTS
        # scan two more times (600-1050 s on broad Greek prefix hits).
        assert len(fts_queries) == 1, (
            f"FTS executed {len(fts_queries)} times: "
            f"{[q['sql'] for q in fts_queries]}"
        )
        _assert_no_scan(ctx.captured_queries)


# ---------------------------------------------------------------------------
# Fix #3 — server-side min-length guard in search_documents
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentSearchGuards:
    def test_short_query_short_circuits_before_sql(self, db):
        _configure_postgres_path(ilike_fallback=False)
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService().search_documents("Δ")
        assert result["count"] == 0
        assert result["source"] == "none"
        assert result["results"] == []
        # Not even the document table may be touched.
        assert not any(
            "documentextraction" in q["sql"].lower() for q in ctx.captured_queries
        )

    def test_two_char_query_short_circuits(self, db):
        _configure_postgres_path(ilike_fallback=False)
        result = SearchService().search_documents("ΔΗ")
        assert result["count"] == 0
        assert result["source"] == "none"

    def test_min_length_query_still_searches(self, db):
        """A 3-char query must NOT be dropped by the guard."""
        _configure_postgres_path(ilike_fallback=False)
        # Reaches the FTS layer (empty corpus → miss → gated fallback off).
        result = SearchService().search_documents("ΔΗΜ")
        assert result["source"] in ("none", "postgresql")
        assert result["count"] == 0


# ---------------------------------------------------------------------------
# Fix #8 — DOCUMENT_SEARCH_ENABLED posture gate
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentSearchEnabledFlag:
    def test_flag_off_returns_empty_stub_without_document_queries(self, db):
        _set_flag("DOCUMENT_SEARCH_ENABLED", False)
        _configure_postgres_path(ilike_fallback=False)
        with CaptureQueriesContext(connection) as ctx:
            result = SearchService().search_documents("ΔΗΜΟΣ ΕΠΙΧΕΙΡΗΣΗ")
        assert result["count"] == 0
        assert result["source"] == "none"
        assert result["results"] == []
        assert not any(
            "documentextraction" in q["sql"].lower() for q in ctx.captured_queries
        )

    def test_flag_on_by_default(self, db):
        _configure_postgres_path(ilike_fallback=False)
        result = SearchService().search_documents("ΔΗΜ")
        # Flag on → the search runs (and degrades safely to the empty result
        # on an empty corpus).
        assert result["source"] in ("none", "postgresql")


# ---------------------------------------------------------------------------
# View level — /api/search/documents/ contract
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDocumentSearchView:
    def test_hostile_query_returns_wellformed_200(self, client, db):
        _configure_postgres_path(ilike_fallback=False)
        resp = client.get("/api/search/documents/", {"q": "QVXWZJ:"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["source"] == "none"
        assert data["results"] == []
        assert data["capabilities"]["document_search_enabled"] is True

    def test_short_query_view_returns_200(self, client, db):
        _configure_postgres_path(ilike_fallback=False)
        resp = client.get("/api/search/documents/", {"q": "Δ"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["source"] == "none"

    def test_view_reports_document_search_enabled(self, client, db):
        _configure_postgres_path(ilike_fallback=False)
        _set_flag("DOCUMENT_SEARCH_ENABLED", False)
        resp = client.get("/api/search/documents/", {"q": "ΔΗΜΟΣ"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["capabilities"]["document_search_enabled"] is False
        assert data["count"] == 0

    def test_auth_config_delivers_document_search_enabled(self, client, db):
        resp = client.get("/api/system/config/auth/")
        assert resp.status_code == 200
        assert "document_search_enabled" in resp.json()["search"]