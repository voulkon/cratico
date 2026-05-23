from datetime import date
from unittest.mock import patch

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_ingestion_service import DecisionIngestionService
from core.tests.utils import create_decision_dto as create_decision
from core.tests.utils import create_search_response


@patch("core.fetchers.diavgeia_fetcher.DiavgeiaFetcher.fetch_decisions")
@patch("time.sleep", return_value=None)
def test_pagination_multi_page(mock_sleep, mock_fetch_decisions):
    # Setup mock responses for pagination
    page1_response = create_search_response(
        total=1200,  # Will require 3 pages (500 per page)
        size=500,
        actualSize=500,
        decisions=[create_decision(f"ada{i}") for i in range(500)],
    )

    page2_response = create_search_response(
        total=1200,
        size=500,
        actualSize=500,
        decisions=[create_decision(f"ada{i}") for i in range(500, 1000)],
    )

    page3_response = create_search_response(
        total=1200,
        size=500,
        actualSize=200,  # Last page has fewer
        decisions=[create_decision(f"ada{i}") for i in range(1000, 1200)],
    )

    mock_fetch_decisions.side_effect = [page1_response, page2_response, page3_response]

    # Create service and fetch decisions
    fetcher = DiavgeiaFetcher()
    service = DecisionIngestionService(fetcher, delay_seconds=0)

    start_date = date(2024, 1, 1)
    end_date = date(2024, 1, 7)

    decisions = service._fetch_for_single_increment(start_date, end_date, {})

    # Assertions
    assert len(decisions) == 1200
    assert mock_fetch_decisions.call_count == 3

    # Verify pagination parameters
    assert mock_fetch_decisions.call_args_list[0][1]["page"] == 0
    assert mock_fetch_decisions.call_args_list[1][1]["page"] == 1
    assert mock_fetch_decisions.call_args_list[2][1]["page"] == 2
