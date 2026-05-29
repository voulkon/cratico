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
        """Sample reconciliation result"""
        return {
            "date": "2026-05-01",
            "official_count": 313,
            "our_count": 10,
            "difference": -303,
            "percentage_diff": -96.81,
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
