from datetime import date, datetime, timezone
from unittest.mock import MagicMock, call, patch

import pytest
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_ingestion_service import DecisionIngestionService
from core.tests.utils import create_decision_dto as create_mock_decision
from core.tests.utils import create_search_response as create_mock_search_response

# Models from the SDK library might be needed for creating mock responses

# --- Helper Fixtures ---


@pytest.fixture
def mock_diavgeia_fetcher() -> MagicMock:
    """Provides a MagicMock for the DiavgeiaFetcher."""
    return MagicMock(spec=DiavgeiaFetcher)


@pytest.fixture
def decision_service(mock_diavgeia_fetcher: MagicMock) -> DecisionIngestionService:
    """Provides an instance of the service with a mocked fetcher and zero delay."""
    # Use delay=0 for tests to avoid actual sleeping
    return DecisionIngestionService(mock_diavgeia_fetcher, delay_seconds=0)


# --- Test Cases ---


@patch("time.sleep", return_value=None)  # Mock time.sleep globally for tests
def test_single_increment_single_page(
    mock_sleep,
    decision_service: DecisionIngestionService,
    mock_diavgeia_fetcher: MagicMock,
):
    """Test fetching data within one date increment that fits on a single page."""
    start_date = date(2024, 1, 1)
    end_date = date(2024, 1, 5)
    increment_days = 7
    page_size = DecisionIngestionService.DEFAULT_PAGE_SIZE
    how_manydecisions = 10
    mock_decisions = [
        create_mock_decision(
            f"ADA{i}", extra_attributes={"issueDate": datetime.now(timezone.utc)}
        )
        for i in range(how_manydecisions)
    ]
    mock_response = create_mock_search_response(
        page=0, size=page_size, total=how_manydecisions, decisions=mock_decisions
    )

    mock_diavgeia_fetcher.fetch_decisions.return_value = mock_response

    results = decision_service.fetch_decisions_for_period(
        start_date, end_date, date_increment_days=increment_days
    )

    assert len(results) == how_manydecisions
    assert results[0].ada == "ADA0"
    assert results[-1].ada == "ADA9"

    # Verify fetch_decisions was called once with correct params
    mock_diavgeia_fetcher.fetch_decisions.assert_called_once_with(
        from_issue_date=start_date.isoformat(),
        to_issue_date=end_date.isoformat(),  # end_date is within the first increment
        page=0,
        size=page_size,
    )
    # Verify sleep was called (even with delay=0, the call happens)
    mock_sleep.assert_called_once()


@patch("time.sleep", return_value=None)
def test_single_increment_multiple_pages(
    mock_sleep,
    decision_service: DecisionIngestionService,
    mock_diavgeia_fetcher: MagicMock,
):
    """Test fetching data within one date increment spanning multiple pages."""
    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 5)
    increment_days = 7
    page_size = 3  # Use small page size for testing pagination
    decision_service.DEFAULT_PAGE_SIZE = page_size  # Override for test

    total_decisions = 7
    decisions_p0 = [
        create_mock_decision(f"ADA{i}", extra_attributes={"issueDate": start_date})
        for i in range(3)
    ]
    decisions_p1 = [
        create_mock_decision(f"ADA{i}", extra_attributes={"issueDate": start_date})
        for i in range(3, 6)
    ]
    decisions_p2 = [
        create_mock_decision(f"ADA{i}", extra_attributes={"issueDate": start_date})
        for i in range(6, 7)
    ]  # Last page has 1

    response_p0 = create_mock_search_response(
        decisions=decisions_p0, page=0, size=page_size, total=total_decisions
    )
    response_p1 = create_mock_search_response(
        decisions=decisions_p1, page=1, size=page_size, total=total_decisions
    )
    response_p2 = create_mock_search_response(
        decisions=decisions_p2, page=2, size=page_size, total=total_decisions
    )

    # Configure the mock to return different responses based on the page number
    def side_effect(*args, **kwargs):
        page = kwargs.get("page", 0)
        if page == 0:
            return response_p0
        if page == 1:
            return response_p1
        if page == 2:
            return response_p2
        return create_mock_search_response(
            [], page=page, size=page_size, total=total_decisions
        )  # Should not happen

    mock_diavgeia_fetcher.fetch_decisions.side_effect = side_effect

    results = decision_service.fetch_decisions_for_period(
        start_date, end_date, date_increment_days=increment_days
    )

    assert len(results) == total_decisions
    assert results[0].ada == "ADA0"
    assert results[-1].ada == "ADA6"

    # Verify fetch_decisions was called 3 times with correct page numbers
    expected_calls = [
        call(
            from_issue_date=start_date.isoformat(),
            to_issue_date=end_date.isoformat(),
            page=0,
            size=page_size,
        ),
        call(
            from_issue_date=start_date.isoformat(),
            to_issue_date=end_date.isoformat(),
            page=1,
            size=page_size,
        ),
        call(
            from_issue_date=start_date.isoformat(),
            to_issue_date=end_date.isoformat(),
            page=2,
            size=page_size,
        ),
    ]
    mock_diavgeia_fetcher.fetch_decisions.assert_has_calls(expected_calls)
    assert mock_diavgeia_fetcher.fetch_decisions.call_count == 3
    assert mock_sleep.call_count == 3  # Sleep called before each fetch


# --- Placeholder for more tests ---
# test_multiple_date_increments
# test_pagination_stops_early_actual_size
# test_empty_results_for_increment
# test_fetcher_returns_none_or_invalid
# test_duplicate_decisions_across_increments
# test_rate_limiting_delay_value (might need more complex time mocking)
# test_end_date_exact_match
# test_invalid_increment_value_raises_error


@pytest.mark.django_db(transaction=True)
def test_fetch_daily_decisions_normal_weekday(
    a_test_decision_service: DecisionIngestionService, daily_decisions_vcr_cassette
):
    with daily_decisions_vcr_cassette("test_fetch_daily_decisions_normal_weekday.yaml"):
        target_date = date(2025, 9, 8)
        a_test_decision_service.fetch_daily_decisions(
            target_date=target_date, save_to_db=True, want_it_distributed=False
        )
        ...
