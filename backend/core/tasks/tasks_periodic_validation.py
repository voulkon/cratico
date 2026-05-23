"""
Celery Beat periodic task for continuous import validation.

When the ImportThreshold is enabled, this runs daily to check and backfill
the last 7 days, continuously working backwards to fill gaps.
"""

from datetime import date, timedelta

from celery import shared_task
from core.models.import_thresholds import ImportThreshold
from core.tasks.tasks_import_validation import validate_and_backfill_imports
from loguru import logger


@shared_task(bind=True)
def periodic_validation_task(self):
    """
    Periodic task that runs when validation system is enabled.

    Checks last 7 days for incomplete imports and dispatches re-imports.
    Designed to run daily via Celery Beat.

    Returns:
        Dict with execution status and results
    """
    try:
        # Check if system is enabled
        config = ImportThreshold.get_instance()

        if not config.enabled:
            logger.info("Periodic validation: System is disabled, skipping")
            return {"status": "skipped", "reason": "system_disabled"}

        # Validate last 7 days
        end_date = date.today() - timedelta(days=1)  # Yesterday
        start_date = end_date - timedelta(days=7)  # Last 7 days

        logger.info(f"Periodic validation: Checking {start_date} to {end_date}")

        # Run validation (skip_enabled_check=True since we already checked)
        result = validate_and_backfill_imports(
            start_date_str=start_date.isoformat(),
            end_date_str=end_date.isoformat(),
            dry_run=False,
            force_reimport=False,
            chunk_size=10,
            skip_enabled_check=True,
        )

        logger.success(
            f"Periodic validation complete: {result.get('reimport_dispatched', 0)} "
            f"tasks dispatched for incomplete days"
        )

        return {"status": "completed", "result": result}

    except Exception as e:
        logger.error(f"Periodic validation failed: {str(e)}")
        return {"status": "failed", "error": str(e)}
