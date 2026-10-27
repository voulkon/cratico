"""
Tests for ImportJobQueue._trigger_post_import_if_global()

Verifies the wiring that fires post_daily_import_orchestrator after a
GLOBAL daily import completes, and stays silent for filtered imports.

The goal: be 100% certain the orchestrator is (or isn't) triggered
without needing a real broker or a live import run.
"""

from datetime import date
from unittest.mock import MagicMock, patch

import pytest
from core.models.import_jobs import ImportJob, ImportJobStatus, ImportJobType
from core.services.import_job_queue import ImportJobQueue
from django.utils import timezone


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


def _make_job(
    start_date=None,
    organization=None,
    unit=None,
    signer=None,
    import_type=ImportJobType.DAILY,
    search_params=None,
):
    return ImportJob.objects.create(
        start_date=start_date or date(2026, 5, 29),
        end_date=start_date or date(2026, 5, 29),
        status=ImportJobStatus.COMPLETED,
        organization=organization,
        unit=unit,
        signer=signer,
        import_type=import_type,
        search_params=search_params,
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
            call_kwargs = mock_task.apply_async.call_args.kwargs
            assert call_kwargs["countdown"] == 60
            sent = call_kwargs["kwargs"]
            assert sent["job_id"] == job.id
            assert sent["reference_date_str"] == "2026-05-29"
            # §4.2 fix: the DAILY run verifies its OWN import window, not the
            # reference calendar day.  The daily fetch has no
            # fetch_started_at, so the window starts at created_at.
            assert sent["imported_since_str"] == job.created_at.isoformat()
            assert sent["imported_until_str"]

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

    # ------------------------------------------------------------------
    # HOURLY branch (T08)
    # ------------------------------------------------------------------

    def test_hourly_completion_triggers_hourly_orchestrator(self, queue):
        """A global HOURLY job fires the hourly orchestrator with its window."""
        job = _make_job(
            import_type=ImportJobType.HOURLY,
            search_params={"fetch_started_at": "2026-05-29T10:00:00+00:00"},
        )

        with (
            patch(
                "core.tasks.tasks_post_import.post_hourly_import_orchestrator"
            ) as mock_hourly,
            patch(
                "core.tasks.tasks_post_import.post_daily_import_orchestrator"
            ) as mock_daily,
        ):
            mock_hourly.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            mock_daily.apply_async.assert_not_called()
            call_kwargs = mock_hourly.apply_async.call_args.kwargs
            assert call_kwargs["countdown"] == 300
            sent = call_kwargs["kwargs"]
            assert sent["job_id"] == job.id
            assert sent["imported_since_str"] == "2026-05-29T10:00:00+00:00"
            assert sent["reference_date_str"] == timezone.localdate().isoformat()
            assert sent["imported_until_str"]

    def test_hourly_orchestrator_falls_back_to_created_at(self, queue):
        """No fetch_started_at → imported_since_str falls back to created_at."""
        job = _make_job(import_type=ImportJobType.HOURLY, search_params={})

        with patch(
            "core.tasks.tasks_post_import.post_hourly_import_orchestrator"
        ) as mock_hourly:
            mock_hourly.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            sent = mock_hourly.apply_async.call_args.kwargs["kwargs"]
            assert sent["imported_since_str"] == job.created_at.isoformat()

    def test_daily_completion_triggers_daily_orchestrator(self, queue):
        """Regression: a global DAILY job still fires the daily orchestrator."""
        job = _make_job(import_type=ImportJobType.DAILY)

        with (
            patch(
                "core.tasks.tasks_post_import.post_daily_import_orchestrator"
            ) as mock_daily,
            patch(
                "core.tasks.tasks_post_import.post_hourly_import_orchestrator"
            ) as mock_hourly,
        ):
            mock_daily.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            mock_hourly.apply_async.assert_not_called()
            assert mock_daily.apply_async.call_args.kwargs["countdown"] == 60

    def test_backfill_completion_triggers_nothing(self, queue):
        """Regression: BACKFILL fires neither the daily nor the hourly orchestrator."""
        job = _make_job(import_type=ImportJobType.BACKFILL)

        with (
            patch(
                "core.tasks.tasks_post_import.post_daily_import_orchestrator"
            ) as mock_daily,
            patch(
                "core.tasks.tasks_post_import.post_hourly_import_orchestrator"
            ) as mock_hourly,
        ):
            mock_daily.apply_async = MagicMock()
            mock_hourly.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            mock_daily.apply_async.assert_not_called()
            mock_hourly.apply_async.assert_not_called()

    # ------------------------------------------------------------------
    # §5.2 — the completion path is flag-agnostic (pinned on purpose)
    # ------------------------------------------------------------------

    def test_daily_completion_enqueues_orchestrator_with_flag_off(self, queue):
        """With POST_IMPORT_ORCHESTRATOR_ENABLED off, a completed global DAILY
        job STILL enqueues the orchestrator.

        This is intentional (docs/en/AUTO_IMPORT_FLAG_MATRIX.md §2): the
        orchestrator's own gate is the single switch for the pipeline, and it
        reports the skip.  If someone later adds a gate here, this test must be
        updated on purpose — otherwise the two gates can silently disagree.
        """
        job = _make_job(import_type=ImportJobType.DAILY)

        with (
            patch(
                "core.tasks.tasks_post_import.post_daily_import_orchestrator"
            ) as mock_daily,
            patch(
                "core.services.feature_flag_service.feature_flags.is_enabled",
                return_value=False,
            ),
        ):
            mock_daily.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            mock_daily.apply_async.assert_called_once()

    def test_hourly_completion_enqueues_orchestrator_with_flag_off(self, queue):
        """Same as the daily case: the enqueue side has no flag check."""
        job = _make_job(
            import_type=ImportJobType.HOURLY,
            search_params={"fetch_started_at": "2026-05-29T10:00:00+00:00"},
        )

        with (
            patch(
                "core.tasks.tasks_post_import.post_hourly_import_orchestrator"
            ) as mock_hourly,
            patch(
                "core.services.feature_flag_service.feature_flags.is_enabled",
                return_value=False,
            ),
        ):
            mock_hourly.apply_async = MagicMock()
            queue._trigger_post_import_if_global(job.id)

            mock_hourly.apply_async.assert_called_once()
