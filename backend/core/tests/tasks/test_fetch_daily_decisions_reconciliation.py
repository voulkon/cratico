"""
Task-Level Integration Test for fetch_daily_decisions_to_redis with Reconciliation

This test verifies that the import task actually calls the reconciliation logic
in production code paths (not just testing the service in isolation).

Key tests:
1. Task calls fetch_and_reconcile (not just fetch_decisions_for_day)
2. Reconciliation results are logged properly
3. ImportJob is updated with correct counts
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.tasks.tasks_decisions_import import fetch_daily_decisions_to_redis
from diavgeia_api.models.decisions import Decision


@pytest.mark.django_db(transaction=True)
class TestFetchDailyDecisionsReconciliation:
    """
    Task-level tests verifying reconciliation is integrated into the import pipeline.
    """

    @pytest.fixture
    def target_date(self):
        """Test date for all tests"""
        return date(2026, 5, 1)

    @pytest.fixture
    def sample_decisions(self):
        """Create sample Decision DTOs for mocking (API response objects, not DB models)"""
        from datetime import datetime
        from diavgeia_api.models.decisions import DecisionStatus
        
        return [
            Decision(
                ada=f"TEST{i:04d}ADA",
                subject=f"Test Decision {i}",
                decisionTypeId="Β.1.1",
                organizationId="99999999",
                unitIds=["1111111"],
                signerIds=["SIGNER001"],
                issueDate=datetime(2026, 5, 1, 10, 0, 0),
                submissionTimestamp=datetime(2026, 5, 1, 10, 0, 0),
                versionId=f"v{i}",
                thematicCategoryIds=[],
                privateData=False,
                status=DecisionStatus.PUBLISHED,
            )
            for i in range(1, 11)  # 10 decisions
        ]

    @pytest.fixture
    def mock_reconciliation_result(self):
        """Sample reconciliation result with three-way comparison"""
        return {
            "date": "2026-05-01",
            "official_count": 313,
            "api_reported_total": 313,  # API's pagination info
            "our_count": 10,
            "difference": -303,
            "percentage_diff": -96.81,
            "api_vs_official_diff": 0,  # API matches official
            "our_vs_api_diff": -303,  # But we fetched fewer (filtered)
            "status": "discrepancy",
        }

    @pytest.fixture
    def import_job(self, target_date):
        """Create ImportJob for testing"""
        return ImportJob.objects.create(
            start_date=target_date,
            end_date=target_date,
            status=ImportJobStatus.PENDING,
        )

    def test_task_calls_fetch_and_reconcile(
        self, target_date, sample_decisions, mock_reconciliation_result, import_job
    ):
        """
        Verify that the task uses fetch_and_reconcile (not just fetch_decisions_for_day).
        
        This is the critical test that caught the bug - previously the task was calling
        fetch_decisions_for_day which doesn't reconcile with official counts.
        """
        # Mock the fetch service to return our sample data
        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            # Setup mock service instance
            mock_service = MagicMock()
            MockService.return_value = mock_service

            # Mock fetch_and_reconcile to return decisions + reconciliation
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                mock_reconciliation_result,
            )

            # Mock Redis cache to prevent actual Redis operations
            with patch(
                "core.tasks.tasks_decisions_import.RedisDecisionCache"
            ) as MockRedis:
                mock_redis = MagicMock()
                MockRedis.return_value = mock_redis
                mock_redis.create_chunk.return_value = "test-chunk-id"

                # Run the task
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # CRITICAL ASSERTION: Verify fetch_and_reconcile was called
                mock_service.fetch_and_reconcile.assert_called_once_with(
                    target_date=target_date,
                    additional_params=None,
                    include_feature_flags=True,
                )

                # Verify the task succeeded
                assert result["status"] == "success"
                assert result["decisions_count"] == len(sample_decisions)
                assert result["job_id"] == import_job.id

                # Verify ImportJob was updated with correct count
                import_job.refresh_from_db()
                assert import_job.total_decisions == len(sample_decisions)
                assert import_job.status == ImportJobStatus.PROCESSING

    def test_task_logs_reconciliation_results(
        self, target_date, sample_decisions, mock_reconciliation_result, import_job, capfd
    ):
        """
        Verify that reconciliation results are properly logged.
        
        This ensures operators can monitor reconciliation status in production logs.
        
        Note: Uses capfd instead of caplog because the code uses loguru (not stdlib logging).
        Loguru writes directly to stderr, bypassing pytest's caplog fixture.
        """
        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                mock_reconciliation_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Capture loguru's stderr output
                captured = capfd.readouterr()
                log_output = captured.err + captured.out
                assert "Official=313" in log_output
                assert "Ours=10" in log_output
                assert "Status=discrepancy" in log_output

    def test_reconciliation_with_matching_counts(self, target_date, sample_decisions, import_job):
        """
        Test happy path where our count matches official count.
        """
        # Mock reconciliation showing perfect match
        perfect_match_result = {
            "date": target_date.isoformat(),
            "official_count": 10,
            "our_count": 10,
            "difference": 0,
            "percentage_diff": 0.0,
            "status": "match",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                perfect_match_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Verify reconciliation was still called
                mock_service.fetch_and_reconcile.assert_called_once()

    def test_reconciliation_with_search_params(self, target_date, sample_decisions, import_job):
        """
        Test that search params are properly passed to reconciliation.
        
        When filtering by org/unit/signer, reconciliation won't match official
        totals (which are for all decisions), but it should still be called.
        """
        search_params = {
            "org": "99999999",
            "unit": "1111111",
        }

        reconciliation_result = {
            "date": target_date.isoformat(),
            "official_count": 313,  # Total for all orgs
            "our_count": 10,  # Filtered subset
            "difference": -303,
            "percentage_diff": -96.81,
            "status": "discrepancy",  # Expected when filtering
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                reconciliation_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    search_params=search_params,
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Verify fetch_and_reconcile was called with search params
                mock_service.fetch_and_reconcile.assert_called_once_with(
                    target_date=target_date,
                    additional_params=search_params,
                    include_feature_flags=True,
                )

    # @pytest.mark.skipif(
    #     "not config.getoption('--run-live', default=False)",
    #     reason="Skipping live API test. Use --run-live to enable.",
    # )
    def test_full_pipeline_with_real_reconciliation(self):
        """
        End-to-end test with real API calls (only runs with --run-live flag).
        
        This is expensive but validates the entire integration works in practice.
        """
        # Find a low-volume date to keep test fast
        from core.services.decision_fetch_reconcile_service import (
            DecisionFetchReconcileService,
        )

        low_volume_date = DecisionFetchReconcileService.find_lowest_volume_date(
            min_count=50, max_count=500
        )

        if not low_volume_date:
            pytest.skip("Could not find suitable low-volume date for testing")

        # Create ImportJob
        import_job = ImportJob.objects.create(
            start_date=low_volume_date,
            end_date=low_volume_date,
            status=ImportJobStatus.PENDING,
        )

        # Mock Redis to prevent actual storage (we just want to test reconciliation)
        with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
            result = fetch_daily_decisions_to_redis.run(
                target_date_str=low_volume_date.isoformat(),
                chunk_size=10,
                job_id=import_job.id,
            )

            # Should have reconciliation results
            assert result["status"] == "success"
            assert result["decisions_count"] > 0

            print(
                f"\n✓ Live test completed for {low_volume_date}: "
                f"{result['decisions_count']} decisions fetched and reconciled"
            )

    def test_three_way_reconciliation_all_match(self, target_date, sample_decisions, import_job):
        """
        Test happy path: all three counts match.
        Official = API reported = Our fetched
        """
        perfect_match_result = {
            "date": target_date.isoformat(),
            "official_count": 10,
            "api_reported_total": 10,
            "our_count": 10,
            "difference": 0,
            "percentage_diff": 0.0,
            "api_vs_official_diff": 0,
            "our_vs_api_diff": 0,
            "status": "match",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                perfect_match_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                assert result["status"] == "success"
                # All three should match
                assert perfect_match_result["official_count"] == 10
                assert perfect_match_result["api_reported_total"] == 10
                assert perfect_match_result["our_count"] == 10

    def test_three_way_reconciliation_pagination_mismatch(
        self, target_date, import_job
    ):
        """
        Test pagination mismatch: API reported total doesn't match what we fetched.
        This catches bugs in pagination logic (duplicates, missing items, etc.)
        
        Scenario: API says 10 items, but we only fetched 8 (missing 2 during pagination)
        """
        # Create 8 decisions (API reported 10 but we only got 8)
        from datetime import datetime
        from diavgeia_api.models.decisions import Decision, DecisionStatus
        
        decisions_fetched = [
            Decision(
                ada=f"TEST{i:04d}ADA",
                subject=f"Test Decision {i}",
                decisionTypeId="Β.1.1",
                organizationId="99999999",
                unitIds=["1111111"],
                signerIds=["SIGNER001"],
                issueDate=datetime(2026, 5, 1, 10, 0, 0),
                submissionTimestamp=datetime(2026, 5, 1, 10, 0, 0),
                versionId=f"v{i}",
                thematicCategoryIds=[],
                privateData=False,
                status=DecisionStatus.PUBLISHED,
            )
            for i in range(1, 9)  # Only 8 decisions
        ]

        pagination_mismatch_result = {
            "date": target_date.isoformat(),
            "official_count": 10,
            "api_reported_total": 10,  # API said 10
            "our_count": 8,  # But we only fetched 8
            "difference": -2,  # 2 short of official
            "percentage_diff": -20.0,
            "api_vs_official_diff": 0,  # API matches official
            "our_vs_api_diff": -2,  # We're missing 2 items during pagination
            "status": "pagination_mismatch",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                decisions_fetched,
                pagination_mismatch_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Should detect pagination mismatch
                assert pagination_mismatch_result["status"] == "pagination_mismatch"
                assert pagination_mismatch_result["our_vs_api_diff"] == -2

    def test_three_way_reconciliation_api_wrong(self, target_date, sample_decisions, import_job):
        """
        Test case: API's pagination info is wrong.
        Official count = 10, Our count = 10, but API reported 12
        
        This catches bugs in the API's pagination metadata.
        """
        api_metadata_wrong_result = {
            "date": target_date.isoformat(),
            "official_count": 10,
            "api_reported_total": 12,  # API pagination info is wrong
            "our_count": 10,  # We correctly fetched all 10
            "difference": 0,  # We match official
            "percentage_diff": 0.0,
            "api_vs_official_diff": 2,  # API metadata is off by 2
            "our_vs_api_diff": -2,  # We fetched 2 fewer than API claimed
            "status": "pagination_mismatch",  # Mismatch even though we match official
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                api_metadata_wrong_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Even though we match official, pagination metadata is wrong
                assert api_metadata_wrong_result["api_vs_official_diff"] == 2
                assert api_metadata_wrong_result["our_count"] == 10
                assert api_metadata_wrong_result["official_count"] == 10

    def test_logs_include_three_way_reconciliation(
        self, target_date, sample_decisions, import_job, capfd
    ):
        """
        Verify that logs include all three counts: official, API reported, and ours.
        """
        three_way_result = {
            "date": target_date.isoformat(),
            "official_count": 313,
            "api_reported_total": 315,  # Slightly off
            "our_count": 313,
            "difference": 0,
            "percentage_diff": 0.0,
            "api_vs_official_diff": 2,
            "our_vs_api_diff": -2,
            "status": "pagination_mismatch",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions,
                three_way_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Capture logs
                captured = capfd.readouterr()
                log_output = captured.err + captured.out
                
                # Should log all three counts
                assert "Official=313" in log_output
                assert "API_reported=315" in log_output
                assert "Ours=" in log_output  # Should show our count
                assert "Pagination_mismatch" in log_output  # Should show mismatch

    def test_filtered_query_skips_official_count(
        self, target_date, sample_decisions, import_job, capfd
    ):
        """
        When FILTER_DECISION_TYPES is active, official count comparison should be skipped.
        
        This is critical: official counts are for ALL decisions, while our query
        is filtered to specific types. Comparing them would be meaningless.
        """
        filtered_query_result = {
            "date": target_date.isoformat(),
            "official_count": None,  # Not fetched for filtered query
            "api_reported_total": 50,  # Filtered count
            "our_count": 50,
            "difference": None,
            "percentage_diff": None,
            "api_vs_official_diff": None,
            "our_vs_api_diff": 0,
            "filters_applied": True,
            "status": "filtered_query",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                sample_decisions[:5],  # Only 5 decisions (filtered)
                filtered_query_result,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Capture logs
                captured = capfd.readouterr()
                log_output = captured.err + captured.out
                
                # Should indicate filtered query
                assert "filtered query" in log_output
                assert "Status=filtered_query" in log_output
                
                # Should show pagination OK, not official count comparison
                assert "Pagination=OK" in log_output
                assert "API_reported=50" in log_output
                
                # Should NOT show official count (it's None for filtered queries)
                # The log format should be different

    def test_filtered_query_with_pagination_issue(
        self, target_date, import_job, capfd
    ):
        """
        Filtered query can still detect pagination bugs even without official count.
        """
        from datetime import datetime
        from diavgeia_api.models.decisions import Decision, DecisionStatus
        
        # Create sample decisions
        decisions = [
            Decision(
                ada=f"FILT{i:04d}ADA",
                subject=f"Filtered Decision {i}",
                decisionTypeId="Β.1.1",
                organizationId="99999999",
                unitIds=["1111111"],
                signerIds=["SIGNER001"],
                issueDate=datetime(2026, 5, 1, 10, 0, 0),
                submissionTimestamp=datetime(2026, 5, 1, 10, 0, 0),
                versionId=f"v{i}",
                thematicCategoryIds=[],
                privateData=False,
                status=DecisionStatus.PUBLISHED,
            )
            for i in range(1, 6)  # Only 5 decisions
        ]

        filtered_pagination_issue = {
            "date": target_date.isoformat(),
            "official_count": None,
            "api_reported_total": 50,  # API said 50
            "our_count": 5,  # But we only got 5 (pagination bug)
            "difference": None,
            "percentage_diff": None,
            "api_vs_official_diff": None,
            "our_vs_api_diff": -45,  # Missing 45 items
            "filters_applied": True,
            "status": "filtered_query_pagination_mismatch",
        }

        with patch(
            "core.services.decision_fetch_reconcile_service.DecisionFetchReconcileService"
        ) as MockService:
            mock_service = MagicMock()
            MockService.return_value = mock_service
            mock_service.fetch_and_reconcile.return_value = (
                decisions,
                filtered_pagination_issue,
            )

            with patch("core.tasks.tasks_decisions_import.RedisDecisionCache"):
                result = fetch_daily_decisions_to_redis.run(
                    target_date_str=target_date.isoformat(),
                    chunk_size=5,
                    job_id=import_job.id,
                )

                # Capture logs
                captured = capfd.readouterr()
                log_output = captured.err + captured.out
                
                # Should detect pagination mismatch even in filtered query
                assert "Pagination_mismatch=-45" in log_output
                assert "Status=filtered_query_pagination_mismatch" in log_output
