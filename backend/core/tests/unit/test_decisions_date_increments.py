from datetime import date
from unittest.mock import patch

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_ingestion_service import DecisionIngestionService
from core.tests.utils import create_decision_dto as create_decision


@patch(
    "core.services.decision_ingestion_service.DecisionIngestionService._fetch_for_single_increment"
)
def test_date_increments(mock_fetch_increment):
    # Mock the internal method to return a known number of decisions
    mock_fetch_increment.side_effect = [
        [create_decision(f"ada1_{i}") for i in range(10)],  # First week
        [create_decision(f"ada2_{i}") for i in range(15)],  # Second week
        [create_decision(f"ada3_{i}") for i in range(5)],  # Third week
    ]

    # Create service
    fetcher = DiavgeiaFetcher()
    service = DecisionIngestionService(fetcher)

    # Use 7-day increments to get 3 calls
    decisions = service.fetch_decisions_for_period(
        date(2024, 1, 1), date(2024, 1, 21), date_increment_days=7
    )

    # Assertions
    assert len(decisions) == 30  # Total from all increments
    assert mock_fetch_increment.call_count == 3

    # Verify date ranges for each call
    assert mock_fetch_increment.call_args_list[0][0][0] == date(2024, 1, 1)  # start
    assert mock_fetch_increment.call_args_list[0][0][1] == date(2024, 1, 7)  # end

    assert mock_fetch_increment.call_args_list[1][0][0] == date(2024, 1, 8)  # start
    assert mock_fetch_increment.call_args_list[1][0][1] == date(2024, 1, 14)  # end

    assert mock_fetch_increment.call_args_list[2][0][0] == date(2024, 1, 15)  # start
    assert mock_fetch_increment.call_args_list[2][0][1] == date(2024, 1, 21)  # end
