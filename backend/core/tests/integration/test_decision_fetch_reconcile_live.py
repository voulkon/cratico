"""
Live Integration Test for Decision Fetch and Reconciliation Service

This test validates the fetch-and-reconcile logic against the real Diavgeia API.
It's designed to run against low-volume days to keep test execution fast.

Usage:
    # Run as a regular test (will be skipped in CI)
    pytest backend/core/tests/integration/test_decision_fetch_reconcile_live.py -v

    # Run with live API calls enabled
    pytest backend/core/tests/integration/test_decision_fetch_reconcile_live.py -v --run-live

    # Run specific test
    pytest backend/core/tests/integration/test_decision_fetch_reconcile_live.py::TestDecisionFetchReconcileLive::test_fetch_low_volume_day -v --run-live
"""

from datetime import date

import pytest
from core.services.decision_fetch_reconcile_service import (
    DecisionFetchReconcileService,
)


# Mark all tests in this module as integration tests
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_api,  # Custom marker for tests that hit live APIs
]


class TestDecisionFetchReconcileLive:
    """
    Live integration tests for DecisionFetchReconcileService.
    
    These tests make real API calls to Diavgeia and verify reconciliation logic.
    They're designed to use low-volume dates to keep execution time reasonable.
    """

    @pytest.fixture
    def service(self):
        """Create service instance configured for submission date (matches official counts)"""
        return DecisionFetchReconcileService(use_submission_date=True)

    @pytest.fixture(scope="class")
    def low_volume_date(self):
        """
        Fixture providing a dynamically-discovered low-volume date for testing.
        
        Instead of hard-coding a date (which becomes unreliable over time),
        this queries the official Diavgeia API to find the actual lowest-volume
        day from the last 30 days.
        
        Criteria:
        - Between 100-1000 decisions (avoid anomalies, but still low-volume)
        - Excludes weekends (often have lower counts for non-work reasons)
        - Uses real API data (reliable regardless of when test runs)
        
        Falls back to a reasonable default if API is unavailable.
        """
        # Try to find actual lowest volume date
        found_date = DecisionFetchReconcileService.find_lowest_volume_date(
            min_count=50,
            max_count=1000,
            exclude_weekends=True,
        )
        
        if found_date:
            return found_date
        
        # Fallback: use a date from 2 days ago (likely to have data)
        from datetime import timedelta
        fallback = date.today() - timedelta(days=2)
        
        import warnings
        warnings.warn(
            f"Could not find low-volume date from API, using fallback: {fallback}",
            UserWarning
        )
        
        return fallback

    def test_build_search_params_submission_date(self, service, low_volume_date):
        """Test that search params use correct field names for submission date"""
        params = service.build_search_params(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Should use from_date/to_date, not from_issue_date/to_issue_date
        assert "from_date" in params
        assert "to_date" in params
        assert "from_issue_date" not in params
        assert "to_issue_date" not in params

        # Date range should be one day
        from datetime import timedelta
        expected_from = low_volume_date.isoformat()
        expected_to = (low_volume_date + timedelta(days=1)).isoformat()
        assert params["from_date"] == expected_from
        assert params["to_date"] == expected_to  # Exclusive end date

        # Should have pagination defaults
        assert params["page"] == 0
        assert params["size"] == 500

    def test_build_search_params_issue_date(self, low_volume_date):
        """Test that search params use correct field names for issue date"""
        service = DecisionFetchReconcileService(use_submission_date=False)

        params = service.build_search_params(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Should use from_issue_date/to_issue_date
        assert "from_issue_date" in params
        assert "to_issue_date" in params
        assert "from_date" not in params
        assert "to_date" not in params

    def test_build_search_params_with_additional_filters(self, service, low_volume_date):
        """Test that additional parameters are properly merged"""
        additional_params = {
            "org": "12345",
            "unit": "67890",
            "signer": "ABCDE",
            # Internal params that should be filtered out
            "force": True,
            "chunk_size": 10,
            "job_id": 123,
        }

        params = service.build_search_params(
            target_date=low_volume_date,
            additional_params=additional_params,
            include_feature_flags=False,
        )

        # Entity filters should be included
        assert params["org"] == "12345"
        assert params["unit"] == "67890"
        assert params["signer"] == "ABCDE"

        # Internal params should be filtered out
        assert "force" not in params
        assert "chunk_size" not in params
        assert "job_id" not in params

    # @pytest.mark.skipif(
    #     "not config.getoption('--run-live', default=False)",
    #     reason="Skipping live API test. Use --run-live to enable.",
    # )
    def test_fetch_low_volume_day(self, service, low_volume_date):
        """
        Test fetching a dynamically-discovered low-volume day from the live API.
        
        This test:
        1. Uses a date automatically selected from recent data (100-1000 decisions)
        2. Fetches all decisions for that date
        3. Validates pagination worked correctly
        4. Verifies we got Decision DTOs back
        """
        decisions, api_total = service.fetch_decisions_for_day(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Should have fetched decisions
        assert len(decisions) > 0, "Should have fetched at least some decisions"

        # All items should be Decision objects
        from diavgeia_api.models.decisions import Decision

        assert all(isinstance(d, Decision) for d in decisions)

        # API total should match or be very close to fetched count
        # (small discrepancies can occur due to timing)
        assert (
            abs(len(decisions) - api_total) <= 5
        ), f"Fetched {len(decisions)} but API reported {api_total}"

        # Since we dynamically select a low-volume date (100-1000 decisions),
        # verify it's actually in that range
        assert (
            100 <= len(decisions) <= 1000
        ), f"Expected low-volume (100-1000) for {low_volume_date}, got {len(decisions)}"

        print(f"\n✓ Successfully fetched {len(decisions)} decisions for {low_volume_date}")
        print(f"  API reported total: {api_total}")

    @pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    )
    def test_get_official_count(self, service, low_volume_date):
        """
        Test getting official count from Diavgeia API.
        
        This validates that we can query the official count endpoint
        and get a result for our test date.
        """
        official_count = service.get_official_count_for_date(low_volume_date)

        # Should get a count back
        assert official_count is not None, "Should get official count from API"
        assert isinstance(official_count, int)
        assert official_count > 0

        # Since we dynamically select a low-volume date, verify it's in expected range
        assert (
            100 <= official_count <= 1000
        ), f"Expected low-volume (100-1000) for {low_volume_date}, got {official_count}"

        print(f"\n✓ Official count for {low_volume_date}: {official_count}")

    @pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    )
    def test_reconcile_counts(self, service, low_volume_date):
        """
        Test the reconciliation logic with real data.
        
        This is the key integration test that validates:
        1. We can fetch decisions
        2. We can get official counts
        3. The reconciliation logic works
        4. Counts match (or we detect discrepancies)
        """
        # First fetch decisions
        decisions, _ = service.fetch_decisions_for_day(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Then reconcile
        reconciliation = service.reconcile_counts(
            target_date=low_volume_date, our_count=len(decisions)
        )

        # Validate reconciliation result structure
        assert "date" in reconciliation
        assert "official_count" in reconciliation
        assert "our_count" in reconciliation
        assert "difference" in reconciliation
        assert "percentage_diff" in reconciliation
        assert "status" in reconciliation

        # Should have gotten official data
        assert reconciliation["status"] != "no_official_data"

        # Our count should match what we fetched
        assert reconciliation["our_count"] == len(decisions)

        # Official count should be positive
        assert reconciliation["official_count"] > 0

        # Print detailed reconciliation info
        print(f"\n✓ Reconciliation for {low_volume_date}:")
        print(f"  Official count: {reconciliation['official_count']}")
        print(f"  Our count: {reconciliation['our_count']}")
        print(f"  Difference: {reconciliation['difference']}")
        print(f"  Percentage diff: {reconciliation['percentage_diff']:.2f}%")
        print(f"  Status: {reconciliation['status']}")

        # Ideally counts should match perfectly
        # But allow small discrepancy (within 5%) due to timing or API inconsistencies
        assert (
            abs(reconciliation["percentage_diff"]) <= 5.0
        ), f"Counts differ by more than 5%: {reconciliation}"

    @pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    )
    def test_fetch_and_reconcile_combined(self, service, low_volume_date):
        """
        Test the convenience method that fetches and reconciles in one call.
        
        This validates the end-to-end workflow that most code will use.
        """
        decisions, reconciliation = service.fetch_and_reconcile(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Should have decisions
        assert len(decisions) > 0

        # Should have valid reconciliation
        assert reconciliation["status"] != "no_official_data"
        assert reconciliation["our_count"] == len(decisions)

        print(f"\n✓ Fetch and reconcile completed:")
        print(f"  Fetched: {len(decisions)} decisions")
        print(f"  Official: {reconciliation['official_count']}")
        print(f"  Match: {reconciliation['percentage_diff']:.2f}% difference")

    def test_feature_flag_filtering_applied(self, service, low_volume_date, mocker):
        """
        Test that feature flag filtering is properly applied to search params.
        
        This is a unit test (doesn't hit live API) that validates feature flag integration.
        """
        # Mock the feature flags service (patched at source since it's locally imported)
        mock_feature_flags = mocker.patch(
            "core.services.feature_flag_service.feature_flags"
        )
        mock_feature_flags.get_value.return_value = ["Β.1.1", "Β.1.2", "Β.2.1"]

        params = service.build_search_params(
            target_date=low_volume_date, include_feature_flags=True
        )

        # Should have called feature flags
        mock_feature_flags.get_value.assert_called_once_with("FILTER_DECISION_TYPES")

        # Should have joined types with semicolon
        assert params["type"] == "Β.1.1;Β.1.2;Β.2.1"

    def test_feature_flag_filtering_disabled(self, service, low_volume_date, mocker):
        """Test that feature flag filtering can be disabled"""
        mock_feature_flags = mocker.patch(
            "core.services.feature_flag_service.feature_flags"
        )

        params = service.build_search_params(
            target_date=low_volume_date, include_feature_flags=False
        )

        # Should NOT have called feature flags
        mock_feature_flags.get_value.assert_not_called()

        # Should NOT have type filter
        assert "type" not in params

    @pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    )
    def test_get_all_official_daily_counts(self):
        """Test fetching all daily counts from official API"""
        counts = DecisionFetchReconcileService.get_all_official_daily_counts()

        # Should get results
        assert len(counts) > 0, "Should get daily counts from API"

        # Check structure of results
        for item in counts:
            assert "date" in item
            assert "count" in item
            assert isinstance(item["date"], date)
            assert isinstance(item["count"], int)
            assert item["count"] >= 0

        # Results should be sorted by date descending
        dates = [item["date"] for item in counts]
        assert dates == sorted(dates, reverse=True), "Results should be sorted by date descending"

        print(f"\n✓ Got {len(counts)} days of official counts")
        print(f"  Most recent: {counts[0]['date']} with {counts[0]['count']} decisions")
        print(f"  Oldest: {counts[-1]['date']} with {counts[-1]['count']} decisions")

    @pytest.mark.skipif(
        "not config.getoption('--run-live', default=False)",
        reason="Skipping live API test. Use --run-live to enable.",
    )
    def test_find_lowest_volume_date(self):
        """Test dynamic discovery of lowest-volume date"""
        lowest_date = DecisionFetchReconcileService.find_lowest_volume_date(
            min_count=100,
            max_count=1000,
            exclude_weekends=True,
        )

        # Should find a date
        assert lowest_date is not None, "Should find a low-volume date"
        assert isinstance(lowest_date, date)

        # Should not be a weekend
        assert lowest_date.weekday() < 5, f"Should not be a weekend, got {lowest_date.strftime('%A')}"

        # Get the actual count for validation
        service = DecisionFetchReconcileService(use_submission_date=True)
        official_count = service.get_official_count_for_date(lowest_date)

        # Should be in the requested range
        assert 100 <= official_count <= 1000, (
            f"Date {lowest_date} has {official_count} decisions, "
            f"expected between 100 and 1000"
        )

        print(f"\n✓ Found lowest volume date: {lowest_date}")
        print(f"  Official count: {official_count} decisions")
        print(f"  Day of week: {lowest_date.strftime('%A')}")


def pytest_addoption(parser):
    """Add custom command line option for running live tests"""
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="Run tests that make live API calls",
    )
