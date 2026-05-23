"""
Celery tasks for health guarantee operations.

These tasks can be run manually, scheduled periodically, or triggered
after batch imports to ensure data consistency.
"""

from typing import List, Optional

from celery import shared_task
from core.services.decision_health_guarantee_service import (
    DecisionHealthGuaranteeService,
)
from loguru import logger


@shared_task(bind=True, max_retries=3)
def ensure_all_decisions_health_task(
    self,
    max_workers: int = 5,
    dry_run: bool = False,
    decision_adas: Optional[List[str]] = None,
):
    """
    Celery task wrapper for comprehensive health guarantee check.

    Can be scheduled to run periodically (e.g., weekly) or triggered manually
    from Django admin or management commands.

    Args:
        max_workers: Number of parallel workers for processing
        dry_run: If True, only report what would be done
        decision_adas: Optional list of specific ADAs to check

    Returns:
        Dictionary with processing results
    """
    try:
        service = DecisionHealthGuaranteeService()
        results = service.ensure_all_decisions_health(
            max_workers=max_workers, dry_run=dry_run, decision_adas=decision_adas
        )

        logger.info(f"Health guarantee task completed: {results}")
        return results

    except Exception as e:
        logger.error(f"Health guarantee task failed: {e}")
        raise self.retry(exc=e, countdown=60 * 5)  # Retry in 5 minutes


@shared_task(bind=True, max_retries=3)
def ensure_organization_resolution_task(
    self,
    batch_size: int = 100,
    max_workers: int = 5,
    decision_adas: Optional[List[str]] = None,
):
    """
    Run organization resolution guarantee as background task.

    Useful after importing decisions with incomplete organization data.
    """
    try:
        service = DecisionHealthGuaranteeService()
        results = service.ensure_organization_resolution(
            batch_size=batch_size, max_workers=max_workers, decision_adas=decision_adas
        )
        return results
    except Exception as e:
        logger.error(f"Organization resolution task failed: {e}")
        raise self.retry(exc=e, countdown=60 * 5)


@shared_task(bind=True, max_retries=3)
def ensure_entity_extraction_task(
    self,
    batch_size: int = 100,
    max_workers: int = 5,
    decision_adas: Optional[List[str]] = None,
):
    """
    Run entity extraction guarantee as background task.

    This also handles amount extraction since they're interdependent.
    """
    try:
        service = DecisionHealthGuaranteeService()
        results = service.ensure_entity_extraction(
            batch_size=batch_size, max_workers=max_workers, decision_adas=decision_adas
        )
        return results
    except Exception as e:
        logger.error(f"Entity extraction task failed: {e}")
        raise self.retry(exc=e, countdown=60 * 5)


@shared_task(bind=True, max_retries=3)
def ensure_company_enrichment_task(
    self, batch_size: int = 100, afm_list: Optional[List[str]] = None
):
    """
    Run company enrichment guarantee as background task.

    Queues AFMs that haven't been looked up yet. Useful after
    entity extraction or when HAVE_AFM_FETCH_JOB is newly enabled.
    """
    try:
        service = DecisionHealthGuaranteeService()
        results = service.ensure_company_enrichment(
            batch_size=batch_size, afm_list=afm_list
        )
        return results
    except Exception as e:
        logger.error(f"Company enrichment task failed: {e}")
        raise self.retry(exc=e, countdown=60 * 5)


@shared_task(bind=True, max_retries=3)
def ensure_opensearch_indexing_task(
    self,
    batch_size: int = 50,
    max_workers: int = 3,
    decision_adas: Optional[List[str]] = None,
):
    """
    Run OpenSearch indexing guarantee as background task.

    Useful after INDEX_THE_OPENSEARCH is newly enabled or after
    OpenSearch infrastructure issues.
    """
    try:
        service = DecisionHealthGuaranteeService()
        results = service.ensure_opensearch_indexing(
            batch_size=batch_size, max_workers=max_workers, decision_adas=decision_adas
        )
        return results
    except Exception as e:
        logger.error(f"OpenSearch indexing task failed: {e}")
        raise self.retry(exc=e, countdown=60 * 5)


@shared_task
def schedule_weekly_health_check():
    """
    Weekly health check that can be added to Celery beat schedule.

    Add to settings.py CELERY_BEAT_SCHEDULE:

    'weekly-health-check': {
        'task': 'core.tasks.health_guarantee_tasks.schedule_weekly_health_check',
        'schedule': crontab(hour=2, minute=0, day_of_week=1),  # Monday 2 AM
    }
    """
    logger.info("[SCHED]️ Running scheduled weekly health check")

    # Run in dry-run mode first to see what needs fixing
    ensure_all_decisions_health_task.delay(max_workers=3, dry_run=True)

    return {"status": "scheduled", "mode": "dry_run"}
