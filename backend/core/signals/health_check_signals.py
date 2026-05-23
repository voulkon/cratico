"""
Django signals for automatic health check updates.

These signals ensure health checks are automatically refreshed
when decisions are modified, providing real-time visibility.
"""

from datetime import timedelta

from core.models.decision_health import DecisionHealthCheck
from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from loguru import logger


@receiver(post_save, sender=Decision)
def decision_saved_signal(sender, instance, created, **kwargs):
    """Mark health check for refresh when decision is saved

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Orchestrator creates/updates health checks explicitly during processing.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        return

    if created:
        logger.info(
            f"New decision {instance.ada} created - will check health on next automated run"
        )
    else:
        logger.debug(f"Decision {instance.ada} updated - marking for health refresh")

    # If a health check exists, mark it as needing refresh by updating timestamp
    try:
        health_check = instance.health_check
        # Set last_checked_at to an older time to trigger refresh on next automated run
        old_time = timezone.now() - timedelta(hours=2)
        health_check.last_checked_at = old_time
        health_check.save(update_fields=["last_checked_at"])

    except DecisionHealthCheck.DoesNotExist:
        # No health check exists yet - will be created on next automated run
        pass


@receiver(post_save, sender=DocumentExtraction)
def document_extraction_updated_signal(sender, instance, created, **kwargs):
    """Schedule health check when document extraction status changes

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Orchestrator updates DecisionHealthCheck after each pipeline step.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        return

    if not instance.decision:
        return

    decision = instance.decision

    # Check if extraction status changed to something significant
    significant_statuses = [
        ProcessingStatus.COMPLETED,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEEDS_VISION,
    ]

    if instance.extraction_status in significant_statuses:
        logger.info(
            f"Document extraction status changed to {instance.extraction_status} for {decision.ada}"
        )

        # Schedule immediate health check for this decision
        from core.tasks.health_check_tasks import check_single_decision_health

        check_single_decision_health.delay(decision.ada)


# Add this task to the health check tasks file
def add_single_decision_health_task():
    """This function will be added to the health_check_tasks.py file"""

    single_decision_task_code = '''
@shared_task
def check_single_decision_health(ada: str):
    """
    Check health of a single decision by ADA.
    Used for immediate updates when decisions are modified.
    """
    from core.services.decision_health_service import DecisionHealthService

    try:
        decision = Decision.objects.get(ada=ada)
        health_service = DecisionHealthService()

        health_check = health_service.check_decision_health(decision, force_refresh=True)

        logger.info(f"Updated health check for {ada}: {health_check.overall_status}")

        return {
            "status": "completed",
            "ada": ada,
            "overall_status": health_check.overall_status,
            "has_errors": health_check.has_errors,
            "has_warnings": health_check.has_warnings
        }

    except Decision.DoesNotExist:
        logger.error(f"Decision {ada} not found for health check")
        return {"status": "error", "message": f"Decision {ada} not found"}

    except Exception as e:
        logger.error(f"Failed to check health for {ada}: {e}")
        return {"status": "error", "message": str(e)}
'''

    return single_decision_task_code
