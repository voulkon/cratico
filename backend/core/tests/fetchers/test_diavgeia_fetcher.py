import io
from unittest.mock import patch

import pytest
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.tests.utils import create_search_response
from diavgeia_api.models.organizations import Unit
from diavgeia_api.models.search import SearchResponse
from loguru import logger


@pytest.fixture
def loguru_capture():
    """Capture loguru output via an in-memory sink.

    loguru writes directly to stderr and bypasses pytest's caplog/capfd
    capture, so we attach our own sink to collect messages.
    """
    stream = io.StringIO()
    handler_id = logger.add(stream, format="{message}")
    yield stream
    logger.remove(handler_id)


@pytest.fixture
def mock_client():
    """Mock the DiavgeiaClient so no HTTP calls are made."""
    with patch.object(DiavgeiaFetcher, "_get_client") as mock_get_client:
        yield mock_get_client.return_value


def test_unit_is_fetched():
    a_fetcher = DiavgeiaFetcher()
    wanted_unit = "100006945"
    wanted_unit: Unit = a_fetcher.fetch_a_unit(wanted_unit)
    assert isinstance(wanted_unit, Unit)
    # Check all properties of the Unit object
    assert (
        wanted_unit.label
        == "ΔΙΕΥΘΥΝΣΗ ΕΝΕΡΓΕΙΑΚΩΝ ΠΟΛΙΤΙΚΩΝ ΚΑΙ ΕΝΕΡΓΕΙΑΚΗΣ ΑΠΟΔΟΤΙΚΟΤΗΤΑΣ"
    )

    assert wanted_unit.category == "ADMINISTRATION"
    assert wanted_unit.active is True
    assert wanted_unit.parentId == "100006937"


def test_fetch_decisions_advanced_passes_params(mock_client):
    mock_client.search_advanced.return_value = create_search_response(total=5)

    result = DiavgeiaFetcher().fetch_decisions_advanced(q="issue_date:[...] AND org", page=2, size=100)

    assert isinstance(result, SearchResponse)
    mock_client.search_advanced.assert_called_once_with(
        q="issue_date:[...] AND org", page=2, size=100
    )


def test_fetch_decisions_advanced_defaults(mock_client):
    mock_client.search_advanced.return_value = create_search_response(total=5)

    DiavgeiaFetcher().fetch_decisions_advanced(q="some query")

    mock_client.search_advanced.assert_called_once_with(q="some query", page=0, size=500)


def test_fetch_decisions_advanced_returns_response_with_empty_decisions(mock_client):
    empty_response = create_search_response(total=0, actualSize=0, decisions=[])
    mock_client.search_advanced.return_value = empty_response

    result = DiavgeiaFetcher().fetch_decisions_advanced(q="empty window")

    assert result is empty_response
    assert result.decisions == []
    assert result.info.total == 0
    assert result.info.actualSize == 0


def test_fetch_decisions_advanced_returns_none_on_exception(mock_client, loguru_capture):
    mock_client.search_advanced.side_effect = RuntimeError("boom")

    result = DiavgeiaFetcher().fetch_decisions_advanced(q="breaking query")

    assert result is None
    log_output = loguru_capture.getvalue()
    assert "Exception during advanced decision fetch for query breaking query" in log_output
