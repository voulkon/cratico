"""
Tests for ImportJobQueue._trigger_post_import_if_global()

Verifies the wiring that fires post_daily_import_orchestrator after a
GLOBAL daily import completes, and stays silent for filtered imports.

The goal: be 100% certain the orchestrator is (or isn't) triggered
without needing a real broker or a live import run.
"""

from datetime import date
from unittest.mock import MagicMock, call, patch

import pytest
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.import_job_queue import ImportJobQueue


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_redis():
    """Minimal Redis mock so ImportJobQueue can be instantiated."""
    mock_client = MagicMock()
    mock_client.connection_pool = MagicMock()
    mock_client.connection_pool.connection_kwargs = {"db": 2}

    with patch(
        "core.services.import_job_queue.get_redis_connection",
        return_value=mock_client,
    ):
        yield mock_client


@pytest.fixture
def queue(mock_redis):
    return ImportJobQueue()


@pytest.fixture
def mock_orchestrator():
    """Mock post_daily_import_orchestrator.apply_async so nothing hits Celery."""
    with patch(
        "core.tasks.tasks_post_import.post_daily_import_orchestrator"
    ) as mock_task:
        mock_task.apply_async = MagicMock()
        yield mock_task


@pytest.fixture(autouse=True)
def clean_jobs():
    ImportJob.objects.all().delete()
    yield
    ImportJob.objects.all().delete()


# ---------------------------------------------------------------------------
# Helper: create a minimal ImportJob in the DB
# ---------------------------------------------------------------------------


def _make_job(start_date=None, organization=None, unit=None, signer=None):
    return ImportJob.objects.create(
        start_date=start_date or date(2026, 5, 29),
        end_date=start_date or date(2026, 5, 29),
        status=ImportJobStatus.COMPLETED,
        organization=organization,
        unit=unit,
        signer=signer,
    )


# ---------------------------------------------------------------------------
# Tests: global import fires orchestrator
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestTriggerPostImportIfGlobal:
    """Tests that the orchestrator is fired only for global (unfiltered) imports."""

    def test_global_import_fires_orchestrator(self, queue):
        """A job with no org/unit/signer filter should trigger the orchestrator."""
        job = _make_job(start_date=date(2026, 5, 29))

        # _trigger_post_import_if_global does a lazy `from ... import` inside
        # the function body, so we patch the attribute on the source module.
        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)
            mock_task.apply_async.assert_called_once_with(
                kwargs={
                    "job_id": job.id,
                    "reference_date_str": "2026-05-29",
                },
                countdown=60,
            )

    def test_org_filtered_import_skips_orchestrator(self, queue):
        """A job scoped to a specific org should NOT trigger the orchestrator."""
        from conftest import OrganizationFactory

        org = OrganizationFactory()
        job = _make_job(organization=org)

        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)
            mock_task.apply_async.assert_not_called()

    def test_signer_filtered_import_skips_orchestrator(self, queue):
        """A job scoped to a specific signer should NOT trigger the orchestrator."""
        from conftest import SignerFactory

        signer = SignerFactory()
        job = _make_job(signer=signer)

        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)
            mock_task.apply_async.assert_not_called()

    def test_nonexistent_job_does_not_crash(self, queue):
        """Passing a non-existent job_id should silently log and return, not raise."""
        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            # Should not raise ImportJob.DoesNotExist
            queue._trigger_post_import_if_global(job_id=999999)
            mock_task.apply_async.assert_not_called()

    def test_reference_date_matches_job_start_date(self, queue):
        """The orchestrator must receive the job's start_date as reference_date_str."""
        job = _make_job(start_date=date(2026, 1, 15))

        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            call_kwargs = mock_task.apply_async.call_args
            assert call_kwargs.kwargs["kwargs"]["reference_date_str"] == "2026-01-15"

    def test_countdown_is_60_seconds(self, queue):
        """The orchestrator must be dispatched with a 60-second countdown."""
        job = _make_job()

        with patch(
            "core.tasks.tasks_post_import.post_daily_import_orchestrator"
        ) as mock_task:
            mock_task.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            call_kwargs = mock_task.apply_async.call_args
            assert call_kwargs.kwargs["countdown"] == 60
