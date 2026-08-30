"""
Service-Level Tests for Three-Way Reconciliation Logic

Tests the reconcile_counts method to ensure it properly compares:
1. Official count (from daily stats endpoint)
2. API reported total (from response.info.total during pagination)
3. Our fetched count (len(all_decisions))

This is complementary to the task-level tests - here we test the reconciliation
logic itself in isolation.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from core.services.decision_fetch_reconcile_service import DecisionFetchReconcileService


class TestThreeWayReconciliation:
    """
    Unit tests for three-way reconciliation logic.
    """

    @pytest.fixture
    def service(self):
        """Create service instance for testing"""
        return DecisionFetchReconcileService()

    @pytest.fixture
    def test_date(self):
        """Test date"""
        return date(2026, 5, 1)

    def test_all_three_match(self, service, test_date):
        """
        Happy path: all three counts match perfectly.
        Official = API reported = Our count
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=100,
                api_reported_total=100,
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 100
            assert result["difference"] == 0
            assert result["percentage_diff"] == 0.0
            assert result["api_vs_official_diff"] == 0
            assert result["our_vs_api_diff"] == 0
            assert result["status"] == "match"

    def test_pagination_mismatch_but_matches_official(self, service, test_date):
        """
        Pagination issue: we match official, but API reported total is wrong.
        
        Scenario: Official = 100, Our = 100, but API claimed 105
        This indicates the API's pagination metadata is incorrect.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=100,  # Matches official
                api_reported_total=105,  # But API said more
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] == 105
            assert result["our_count"] == 100
            assert result["difference"] == 0  # We match official
            assert result["percentage_diff"] == 0.0
            assert result["api_vs_official_diff"] == 5  # API is off
            assert result["our_vs_api_diff"] == -5  # We fetched 5 fewer than API claimed
            assert result["status"] == "pagination_mismatch"

    def test_pagination_mismatch_missing_items(self, service, test_date):
        """
        Pagination bug: we fetched fewer items than API reported.
        
        Scenario: Official = 100, API = 100, but we only got 95
        This indicates items were lost during pagination.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=95,  # Missing 5 items
                api_reported_total=100,
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 95
            assert result["difference"] == -5
            assert result["percentage_diff"] == -5.0
            assert result["api_vs_official_diff"] == 0  # API metadata is correct
            assert result["our_vs_api_diff"] == -5  # We're missing 5
            assert result["status"] == "discrepancy_with_pagination_mismatch"

    def test_pagination_mismatch_duplicate_items(self, service, test_date):
        """
        Pagination bug: we fetched more items than API reported (duplicates).
        
        Scenario: Official = 100, API = 100, but we got 103
        This indicates duplicate items during pagination.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=103,  # 3 duplicates
                api_reported_total=100,
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 103
            assert result["difference"] == 3
            assert result["percentage_diff"] == 3.0
            assert result["api_vs_official_diff"] == 0
            assert result["our_vs_api_diff"] == 3  # We have 3 extra
            assert result["status"] == "discrepancy_with_pagination_mismatch"

    def test_discrepancy_without_api_total(self, service, test_date):
        """
        Backward compatibility: reconciliation works without API reported total.
        
        This is for cases where we don't have access to response.info.total
        (e.g., old code paths or single-page responses).
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=95,
                api_reported_total=None,  # Not provided
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] is None
            assert result["our_count"] == 95
            assert result["difference"] == -5
            assert result["percentage_diff"] == -5.0
            assert result["api_vs_official_diff"] is None
            assert result["our_vs_api_diff"] is None
            assert result["status"] == "discrepancy"

    def test_no_official_data_but_pagination_ok(self, service, test_date):
        """
        No official data available, but can still check pagination consistency.
        
        Even without official counts, we can verify that our fetched count
        matches what the API claimed to have.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=None
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=100,
                api_reported_total=100,
            )

            assert result["official_count"] is None
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 100
            assert result["difference"] is None
            assert result["percentage_diff"] is None
            assert result["api_vs_official_diff"] is None
            assert result["our_vs_api_diff"] == 0  # Pagination is consistent
            assert result["status"] == "no_official_data"

    def test_no_official_data_with_pagination_mismatch(self, service, test_date):
        """
        No official data, AND pagination is inconsistent.
        
        This is the worst case - we can't verify against official counts,
        and our pagination seems broken.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=None
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=95,
                api_reported_total=100,  # Mismatch
            )

            assert result["official_count"] is None
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 95
            assert result["difference"] is None
            assert result["percentage_diff"] is None
            assert result["api_vs_official_diff"] is None
            assert result["our_vs_api_diff"] == -5
            assert result["status"] == "pagination_mismatch"

    def test_within_tolerance_threshold(self, service, test_date):
        """
        Small discrepancies within 1% threshold are considered a match.
        
        Official = 10000, Our = 10005 (0.05% diff) → match
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=10000
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=10005,  # 0.05% difference
                api_reported_total=10005,
            )

            assert result["percentage_diff"] == pytest.approx(0.05)
            assert result["status"] == "match"  # Within 1% tolerance

    def test_just_outside_tolerance_threshold(self, service, test_date):
        """
        Discrepancies just outside 1% threshold trigger warnings.
        
        Official = 1000, Our = 1011 (1.1% diff) → discrepancy
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=1000
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=1011,  # 1.1% difference
                api_reported_total=1011,
            )

            assert result["percentage_diff"] == pytest.approx(1.1)
            assert result["status"] == "discrepancy"

    def test_complex_three_way_mismatch(self, service, test_date):
        """
        All three values are different (nightmare scenario).
        
        Official = 100, API = 105, Our = 98
        This indicates multiple issues: API metadata is wrong AND pagination has bugs.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=100
        ):
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=98,
                api_reported_total=105,
            )

            assert result["official_count"] == 100
            assert result["api_reported_total"] == 105
            assert result["our_count"] == 98
            assert result["difference"] == -2  # 2 short of official
            assert result["api_vs_official_diff"] == 5  # API thinks there are 5 more
            assert result["our_vs_api_diff"] == -7  # We're 7 short of what API claimed
            assert result["status"] == "discrepancy_with_pagination_mismatch"

    def test_filtered_query_skips_official_reconciliation(self, service, test_date):
        """
        When filters are applied, official count comparison should be skipped.
        
        Scenario: FILTER_DECISION_TYPES is active
        - Official count = 1000 (all decisions)
        - Our filtered query = 100 (specific types only)
        - Should NOT compare against official count
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=1000
        ) as mock_official:
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=100,
                api_reported_total=100,
                filters_applied=True,  # Filters are active
            )

            # Should NOT have called get_official_count_for_date
            mock_official.assert_not_called()
            
            assert result["official_count"] is None  # Not fetched
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 100
            assert result["difference"] is None  # No official comparison
            assert result["percentage_diff"] is None
            assert result["our_vs_api_diff"] == 0  # Pagination OK
            assert result["filters_applied"] is True
            assert result["status"] == "filtered_query"

    def test_filtered_query_with_pagination_mismatch(self, service, test_date):
        """
        Filtered query with pagination issue.
        
        Official reconciliation is skipped, but pagination check still catches bugs.
        """
        with patch.object(
            service, "get_official_count_for_date", return_value=1000
        ) as mock_official:
            result = service.reconcile_counts(
                target_date=test_date,
                our_count=95,
                api_reported_total=100,
                filters_applied=True,
            )

            # Should NOT have called official count
            mock_official.assert_not_called()
            
            assert result["official_count"] is None
            assert result["api_reported_total"] == 100
            assert result["our_count"] == 95
            assert result["our_vs_api_diff"] == -5
            assert result["filters_applied"] is True
            assert result["status"] == "filtered_query_pagination_mismatch"


class TestFilterDetection:
    """
    Tests for _check_if_filters_applied method.
    """

    @pytest.fixture
    def service(self):
        """Create service instance"""
        return DecisionFetchReconcileService()

    def test_no_filters(self, service):
        """No filters applied"""
        result = service._check_if_filters_applied(
            additional_params=None,
            include_feature_flags=False,
        )
        assert result is False

    def test_feature_flag_filter_active(self, service):
        """FILTER_DECISION_TYPES feature flag is active"""
        with patch("core.services.feature_flag_service.feature_flags") as mock_ff:
            mock_ff.get_value.return_value = ["Β.1.1", "Β.1.2"]
            
            result = service._check_if_filters_applied(
                additional_params=None,
                include_feature_flags=True,
            )
            assert result is True

    def test_feature_flag_empty_list(self, service):
        """FILTER_DECISION_TYPES exists but is empty list"""
        with patch("core.services.feature_flag_service.feature_flags") as mock_ff:
            mock_ff.get_value.return_value = []
            
            result = service._check_if_filters_applied(
                additional_params=None,
                include_feature_flags=True,
            )
            assert result is False

    def test_org_filter(self, service):
        """Organization filter is applied"""
        result = service._check_if_filters_applied(
            additional_params={"org": "99999999"},
            include_feature_flags=False,
        )
        assert result is True

    def test_unit_filter(self, service):
        """Unit filter is applied"""
        result = service._check_if_filters_applied(
            additional_params={"unit": "1111111"},
            include_feature_flags=False,
        )
        assert result is True

    def test_signer_filter(self, service):
        """Signer filter is applied"""
        result = service._check_if_filters_applied(
            additional_params={"signer": "SIGNER001"},
            include_feature_flags=False,
        )
        assert result is True

    def test_type_filter_in_params(self, service):
        """Decision type filter in additional params"""
        result = service._check_if_filters_applied(
            additional_params={"type": "Β.1.1"},
            include_feature_flags=False,
        )
        assert result is True

    def test_multiple_filters(self, service):
        """Multiple filters applied"""
        result = service._check_if_filters_applied(
            additional_params={"org": "99999999", "unit": "1111111"},
            include_feature_flags=False,
        )
        assert result is True

    def test_internal_params_ignored(self, service):
        """Internal params (job_id, chunk_size) don't count as filters"""
        result = service._check_if_filters_applied(
            additional_params={"job_id": 123, "chunk_size": 10, "force": True},
            include_feature_flags=False,
        )
        assert result is False
