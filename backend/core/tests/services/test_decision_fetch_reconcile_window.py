"""
Window fetch service tests — T05 (hourly-import fetch primitive).

Covers ``build_window_query``, ``fetch_decisions_for_window`` and
``reconcile_window`` on ``DecisionFetchReconcileService``. All fetcher calls
are mocked — no network. DST cases use fixed summer/winter dates, never "now".
"""

import io
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest
from core.services.decision_fetch_reconcile_service import (
    DecisionFetchReconcileService,
)
from diavgeia_api.models.decisions import Decision, DecisionStatus
from diavgeia_api.models.search import SearchInfo, SearchResponse
from django.conf import settings
from loguru import logger

ATHENS = ZoneInfo(settings.TIME_ZONE)

WINDOW_FROM = datetime(2026, 10, 5, 9, 0, tzinfo=timezone.utc)
WINDOW_TO = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def loguru_capture():
    """Capture loguru output via an in-memory sink.

    loguru writes directly to stderr and bypasses pytest's caplog capture,
    so we attach our own sink to collect messages.
    """
    stream = io.StringIO()
    handler_id = logger.add(stream, format="{message}")
    yield stream
    logger.remove(handler_id)


@pytest.fixture
def service():
    return DecisionFetchReconcileService()


def _decision_dto(idx: int, decision_type_id: str = "Β.1.1") -> Decision:
    """Minimal Decision DTO — only the fields the window logic reads."""
    return Decision(
        ada=f"ΤΕΣΤ-{idx:06d}",
        subject=f"Decision {idx}",
        issueDate=datetime(2026, 10, 5, 9, 30, tzinfo=timezone.utc),
        organizationId="org-1",
        signerIds=["signer-1"],
        unitIds=["unit-1"],
        decisionTypeId=decision_type_id,
        thematicCategoryIds=["cat-1"],
        privateData=False,
        submissionTimestamp=datetime(2026, 10, 5, 9, 45, tzinfo=timezone.utc),
        status=DecisionStatus.PUBLISHED,
        versionId=f"v-{idx}",
    )


def _page_response(
    decisions, total: int, page: int = 0, size: int = 500, query: str = "echoed"
) -> SearchResponse:
    """A SearchResponse page with an explicit info.query echo."""
    return SearchResponse(
        decisions=decisions,
        info=SearchInfo(
            query=query,
            page=page,
            size=size,
            actualSize=len(decisions),
            total=total,
            order="recent",
        ),
    )


class TestBuildWindowQuery:
    """build_window_query: Athens-tz conversion and byte-exact rendering."""

    def test_build_window_query_summer_utc_converts_to_eest(self, service):
        """UTC summer datetimes render with the Athens EEST (+03:00) offset."""
        q = service.build_window_query(
            datetime(2026, 7, 15, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 7, 15, 9, 0, tzinfo=timezone.utc),
        )
        assert "DT(2026-07-15T11:00:00+03:00)" in q
        assert "DT(2026-07-15T12:00:00+03:00)" in q

    def test_build_window_query_winter_eet(self, service):
        """UTC winter datetimes render with the Athens EET (+02:00) offset."""
        q = service.build_window_query(
            datetime(2026, 1, 15, 8, 0, tzinfo=timezone.utc),
            datetime(2026, 1, 15, 9, 0, tzinfo=timezone.utc),
        )
        assert "DT(2026-01-15T10:00:00+02:00)" in q
        assert "DT(2026-01-15T11:00:00+02:00)" in q

    def test_build_window_query_status_literal(self, service):
        """Full string equals the probe-verified format, Greek status literal
        included (byte-identical to the T00 cassettes)."""
        q = service.build_window_query(
            datetime(2026, 10, 5, 9, 0, tzinfo=ATHENS),
            datetime(2026, 10, 5, 10, 0, tzinfo=ATHENS),
        )
        assert q == (
            "submissionTimestamp:[DT(2026-10-05T09:00:00+03:00) "
            "TO DT(2026-10-05T10:00:00+03:00)] "
            'AND status:"Αναρτημένη"'
        )


class TestFetchDecisionsForWindow:
    """fetch_decisions_for_window: pagination + client-side type filter."""

    def test_fetch_window_single_page(self, service, loguru_capture):
        """total=7, actualSize=7 → 7 decisions, one fetcher call, no filtering."""
        decisions = [_decision_dto(i) for i in range(7)]
        echo = "submissionTimestamp:[DT(2026-10-05T12:00:00+03:00) echo]"
        with patch.object(
            service.fetcher,
            "fetch_decisions_advanced",
            return_value=_page_response(decisions, total=7, query=echo),
        ) as mock_fetch:
            fetched, api_total, types_filtered = service.fetch_decisions_for_window(
                WINDOW_FROM, WINDOW_TO, include_feature_flags=False
            )

        assert len(fetched) == 7
        assert api_total == 7
        assert types_filtered is False
        assert mock_fetch.call_count == 1
        # The fetcher receives the rendered window query
        assert mock_fetch.call_args.kwargs["q"] == service.build_window_query(
            WINDOW_FROM, WINDOW_TO
        )
        # The API's parsed-query echo is logged on page 0 (observability)
        assert echo in loguru_capture.getvalue()

    def test_fetch_window_paginates_all_pages(self, service):
        """total=1200 with size=500 → 3 pages, 1200 DTOs, first-page total."""
        pages = [
            _page_response([_decision_dto(i) for i in range(500)], total=1200, page=0),
            _page_response(
                [_decision_dto(500 + i) for i in range(500)], total=1200, page=1
            ),
            _page_response(
                [_decision_dto(1000 + i) for i in range(200)], total=1200, page=2
            ),
        ]
        with patch.object(
            service.fetcher, "fetch_decisions_advanced", side_effect=pages
        ) as mock_fetch:
            fetched, api_total, types_filtered = service.fetch_decisions_for_window(
                WINDOW_FROM, WINDOW_TO, include_feature_flags=False
            )

        assert mock_fetch.call_count == 3
        assert len(fetched) == 1200
        assert api_total == 1200
        assert types_filtered is False
        # Pages walked in order
        assert [c.kwargs["page"] for c in mock_fetch.call_args_list] == [0, 1, 2]

    def test_fetch_window_stops_on_short_page(self, service):
        """info.total promises 3 pages but page 0 is short → stop after it
        (mirror of the day-fetch loop's early exit)."""
        short_page = _page_response(
            [_decision_dto(i) for i in range(200)], total=1200, page=0
        )
        with patch.object(
            service.fetcher, "fetch_decisions_advanced", return_value=short_page
        ) as mock_fetch:
            fetched, api_total, _ = service.fetch_decisions_for_window(
                WINDOW_FROM, WINDOW_TO, include_feature_flags=False
            )

        assert mock_fetch.call_count == 1
        assert len(fetched) == 200
        assert api_total == 1200  # first-page info.total still recorded

    def test_fetch_window_client_side_type_filtering(self, service, loguru_capture):
        """6 DTOs, 3 with decisionTypeId in the flag list → 3 kept,
        types_filtered=True, api_total_count = UNFILTERED total, dropped
        count logged."""
        types = ["Β.1.1", "Β.1.2", "Β.1.3", "Β.2.4", "Β.2.5", "Β.1.3"]
        decisions = [_decision_dto(i, decision_type_id=t) for i, t in enumerate(types)]
        with patch(
            "core.services.feature_flag_service.feature_flags"
        ) as mock_ff, patch.object(
            service.fetcher,
            "fetch_decisions_advanced",
            return_value=_page_response(decisions, total=6),
        ):
            mock_ff.get_value.return_value = ["Β.1.1", "Β.1.3"]
            fetched, api_total, types_filtered = service.fetch_decisions_for_window(
                WINDOW_FROM, WINDOW_TO
            )

        assert len(fetched) == 3
        assert all(d.decisionTypeId in {"Β.1.1", "Β.1.3"} for d in fetched)
        assert api_total == 6  # unfiltered API total
        assert types_filtered is True
        assert "dropped 3" in loguru_capture.getvalue()

    def test_fetch_window_no_filter_when_flag_empty(self, service):
        """Flag [] → nothing dropped, types_filtered=False."""
        decisions = [_decision_dto(i, decision_type_id=f"Β.9.{i}") for i in range(4)]
        with patch(
            "core.services.feature_flag_service.feature_flags"
        ) as mock_ff, patch.object(
            service.fetcher,
            "fetch_decisions_advanced",
            return_value=_page_response(decisions, total=4),
        ):
            mock_ff.get_value.return_value = []
            fetched, api_total, types_filtered = service.fetch_decisions_for_window(
                WINDOW_FROM, WINDOW_TO
            )

        assert len(fetched) == 4
        assert api_total == 4
        assert types_filtered is False


class TestReconcileWindow:
    """reconcile_window: pagination-consistency only (official N/A intra-day)."""

    def test_reconcile_window_match(self, service):
        result = service.reconcile_window(
            WINDOW_FROM, WINDOW_TO, our_count=42, api_reported_total=42
        )

        assert result["status"] == "window_match"
        assert result["official_count"] is None  # per-day endpoint — N/A
        assert result["api_reported_total"] == 42
        assert result["our_count"] == 42
        assert result["our_vs_api_diff"] == 0
        assert result["types_filtered"] is False
        assert result["window_from"] == "2026-10-05T09:00:00+00:00"
        assert result["window_to"] == "2026-10-05T10:00:00+00:00"

    def test_reconcile_window_mismatch(self, service):
        result = service.reconcile_window(
            WINDOW_FROM,
            WINDOW_TO,
            our_count=40,
            api_reported_total=42,
            types_filtered=False,
        )

        assert result["status"] == "window_pagination_mismatch"
        assert result["our_vs_api_diff"] == -2

    def test_reconcile_window_filtered_shrink_is_match(self, service):
        """our < api with types_filtered=True → match (client-side filtering
        legitimately shrinks the count)."""
        result = service.reconcile_window(
            WINDOW_FROM,
            WINDOW_TO,
            our_count=30,
            api_reported_total=42,
            types_filtered=True,
        )

        assert result["status"] == "window_match"
        assert result["our_vs_api_diff"] == -12
        assert result["types_filtered"] is True

    def test_reconcile_window_filtered_impossible_growth_is_mismatch(self, service):
        """our > api with types_filtered=True → mismatch (impossible without a
        fetch bug)."""
        result = service.reconcile_window(
            WINDOW_FROM,
            WINDOW_TO,
            our_count=43,
            api_reported_total=42,
            types_filtered=True,
        )

        assert result["status"] == "window_pagination_mismatch"
        assert result["our_vs_api_diff"] == 1

    def test_reconcile_window_none_total(self, service):
        """api=None → match-shaped result, no crash."""
        result = service.reconcile_window(
            WINDOW_FROM, WINDOW_TO, our_count=7, api_reported_total=None
        )

        assert result["status"] == "window_match"
        assert result["api_reported_total"] is None
        assert result["our_vs_api_diff"] is None
        assert result["our_count"] == 7
