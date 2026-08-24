"""
Tests for AI Job implementations.

Run with: pytest backend/core/jobs/tests/test_jobs.py
"""

from decimal import Decimal
from unittest.mock import Mock, patch

import pytest
from core.jobs.base import JobValidationError, load_job_class
from core.jobs.daily_summary import DailySummaryJob
from core.models.ai_pricing import AIJobDefinition
from django.test import TestCase


class TestDailySummaryJob(TestCase):
    """Test suite for DailySummaryJob"""

    def setUp(self):
        """Set up test fixtures"""
        self.job_def = AIJobDefinition.objects.create(
            job_name="daily_summary",
            display_name="Daily Document Summary",
            description="Test job",
            default_provider="AWS_BEDROCK",
            default_model="anthropic.claude-3-haiku-20240307-v1:0",
            analysis_type="summary",
            system_prompt="Test prompt",
            prompt_overhead_percentage=Decimal("0.05"),
            output_estimation_mode="RATIO",
            output_ratio=Decimal("0.20"),
            batch_size=1,
            algorithm_module="core.jobs.daily_summary",
            algorithm_class="DailySummaryJob",
        )

        self.job = DailySummaryJob(self.job_def)

    def test_job_metadata(self):
        """Test that job has required metadata"""
        assert self.job.JOB_NAME == "daily_summary"
        assert self.job.JOB_DISPLAY_NAME is not None
        assert self.job.JOB_DESCRIPTION is not None

    def test_validate_implementation(self):
        """Test that job implementation passes validation"""
        try:
            # This will fail if get_items_to_process or process_item are broken
            self.job.validate_implementation()
        except JobValidationError as e:
            pytest.fail(f"Validation failed: {e}")

    def test_prompt_templates(self):
        """Test that prompt templates exist"""
        assert "default" in DailySummaryJob.PROMPT_TEMPLATES
        assert "Β.2.1" in DailySummaryJob.PROMPT_TEMPLATES  # Hiring
        assert "Β.2.2" in DailySummaryJob.PROMPT_TEMPLATES  # Expenses
        assert "Β.2.3" in DailySummaryJob.PROMPT_TEMPLATES  # Contracts

    def test_prepare_prompt_with_decision_type(self):
        """Test that prompt is customized based on decision type"""
        # Mock item with hiring decision
        mock_decision = Mock()
        mock_decision.decision_type.uid = "Β.2.1"

        mock_extraction = Mock()
        mock_extraction.decision = mock_decision

        item = {"extraction": mock_extraction}

        prompt = self.job.prepare_prompt(item)
        assert "πρόσληψη" in prompt.lower()  # "hiring" in Greek

    def test_should_process_item_filters_short_content(self):
        """Test that items with too little content are filtered"""
        item = {"content": "Too short", "extraction": Mock()}

        assert self.job.should_process_item(item) is False

    def test_should_process_item_filters_long_content(self):
        """Test that items with too much content are filtered"""
        item = {"content": "x" * 900000, "extraction": Mock()}  # Way too long

        assert self.job.should_process_item(item) is False

    def test_should_process_item_accepts_normal_content(self):
        """Test that normal items pass filtering"""
        item = {
            "content": "Normal content " * 100,  # Reasonable length
            "extraction": Mock(),
        }

        assert self.job.should_process_item(item) is True

    @patch("core.jobs.daily_summary.get_provider")
    def test_process_item_dry_run(self, mock_get_provider):
        """Test process_item in dry run mode (no API call)"""
        item = {
            "content": "Test content " * 100,
            "item_type": "DocumentExtraction",
            "item_id": 1,
            "item_identifier": "TEST123",
            "extraction": Mock(),
        }

        result = self.job.process_item(
            item=item,
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            dry_run=True,
        )

        # Should not call the provider in dry run
        mock_get_provider.assert_not_called()

        # Should return valid result structure
        assert result["success"] is True
        assert "input_tokens" in result
        assert "output_tokens" in result
        assert "estimated_cost_usd" in result

    @patch("core.jobs.daily_summary.DocumentAnalysis.objects.create")
    @patch("core.jobs.daily_summary.get_provider")
    def test_process_item_actual_run(self, mock_get_provider, mock_create):
        """Test process_item with actual API call (mocked)"""
        # Mock provider and API response
        mock_provider = Mock()
        mock_provider.invoke.return_value = {
            "success": True,
            "text": "Generated summary",
            "input_tokens": 1000,
            "output_tokens": 200,
            "actual_cost_usd": Decimal("0.001"),
        }
        mock_get_provider.return_value = mock_provider
        mock_create.return_value = Mock()

        mock_extraction = Mock()
        mock_extraction.decision = Mock()

        item = {
            "content": "Test content " * 100,
            "item_type": "DocumentExtraction",
            "item_id": 1,
            "item_identifier": "TEST123",
            "extraction": mock_extraction,
        }

        result = self.job.process_item(
            item=item,
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            dry_run=False,
        )

        # Should call API
        mock_provider.invoke.assert_called_once()

        # Should return valid result
        assert result["success"] is True
        assert result["output_tokens"] == 200
        assert "actual_cost_usd" in result


class TestJobLoading(TestCase):
    """Test dynamic job loading"""

    def test_load_job_class(self):
        """Test that we can load a job class dynamically"""
        job_def = AIJobDefinition.objects.create(
            job_name="test_job",
            display_name="Test",
            description="Test",
            default_provider="AWS_BEDROCK",
            default_model="test",
            analysis_type="summary",
            algorithm_module="core.jobs.daily_summary",
            algorithm_class="DailySummaryJob",
        )

        job_class = load_job_class(job_def)
        assert job_class == DailySummaryJob

    def test_load_job_class_invalid_module(self):
        """Test error handling for invalid module"""
        job_def = AIJobDefinition.objects.create(
            job_name="test_job",
            display_name="Test",
            description="Test",
            default_provider="AWS_BEDROCK",
            default_model="test",
            analysis_type="summary",
            algorithm_module="nonexistent.module",
            algorithm_class="NonexistentClass",
        )

        with pytest.raises(ImportError):
            load_job_class(job_def)

    def test_load_job_class_missing_fields(self):
        """Test error when algorithm fields not set"""
        job_def = AIJobDefinition.objects.create(
            job_name="test_job",
            display_name="Test",
            description="Test",
            default_provider="AWS_BEDROCK",
            default_model="test",
            analysis_type="summary",
            algorithm_module=None,
            algorithm_class=None,
        )

        with pytest.raises(ValueError):
            load_job_class(job_def)


class TestJobValidation(TestCase):
    """Test job validation framework"""

    def test_job_must_have_name(self):
        """Test that jobs must define JOB_NAME"""
        from core.jobs.base import BaseAIJob

        class BadJob(BaseAIJob):
            # Missing JOB_NAME
            def get_items_to_process(self, **kwargs):
                return []

            def process_item(self, item, provider, model, dry_run=False):
                return {
                    "success": True,
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "estimated_cost_usd": Decimal("0"),
                }

        job_def = Mock()
        job = BadJob(job_def)

        with pytest.raises(JobValidationError, match="must set JOB_NAME"):
            job.validate_implementation()


@pytest.mark.integration
class TestJobExecution(TestCase):
    """Integration tests for job execution"""

    @pytest.mark.django_db
    def test_full_job_execution_dry_run(self):
        """Test complete job execution in dry run mode"""
        # This would require actual DocumentExtraction fixtures
        # Skipped for now - implement when you have test data

    @pytest.mark.django_db
    @patch("core.jobs.daily_summary.get_provider")
    def test_full_job_execution_with_mock(self, mock_get_provider):
        """Test complete job execution with mocked API"""
        # This would test the full execute() method
        # Skipped for now - implement when you have test data
