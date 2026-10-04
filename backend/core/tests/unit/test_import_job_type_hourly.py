"""Unit tests for ImportJobType.HOURLY (T03)."""

from datetime import date

import pytest

from core.models.import_jobs import ImportJob, ImportJobType


def test_hourly_choice_registered():
    """HOURLY is registered as "hourly" alongside the existing kinds."""
    assert ImportJobType.HOURLY == "hourly"
    assert ImportJobType.HOURLY.label == "Hourly (fresh today)"
    assert ("hourly", ImportJobType.HOURLY.label) in ImportJobType.choices


@pytest.mark.django_db
def test_default_import_type_unchanged():
    """A new ImportJob still defaults to DAILY (HOURLY registration is inert)."""
    job = ImportJob.objects.create(
        start_date=date(2026, 10, 1), end_date=date(2026, 10, 1)
    )
    from_db = ImportJob.objects.get(pk=job.pk)
    assert from_db.import_type == ImportJobType.DAILY
    assert from_db.import_type == "daily"


@pytest.mark.django_db
def test_import_job_factory_hourly_roundtrip():
    """ImportJobFactory(import_type=HOURLY) round-trips from the DB and __str__ renders."""
    from conftest import ImportJobFactory

    job = ImportJobFactory(import_type=ImportJobType.HOURLY)
    from_db = ImportJob.objects.get(pk=job.pk)
    assert from_db.import_type == ImportJobType.HOURLY
    assert from_db.import_type == "hourly"
    assert str(from_db)
