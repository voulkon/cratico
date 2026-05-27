from collections import defaultdict

# Add a decorator to prevent recursive signal calls
from functools import wraps
from threading import Lock

from core.models.decisions import Decision
from core.models.document_analysis import DocumentExtraction
from core.models.import_jobs import DateCoverage
from core.services.opensearch_service import OpenSearchService
from django.conf import settings
from django.db import transaction
from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver
from loguru import logger

# Configure signal logging
SIGNAL_METRICS_ENABLED = getattr(settings, "SIGNAL_METRICS_ENABLED", True)
SIGNAL_LOG_LEVEL = getattr(settings, "SIGNAL_LOG_LEVEL", "DEBUG")
SIGNAL_LOG_BATCH_SIZE = getattr(settings, "SIGNAL_LOG_BATCH_SIZE", 100)

# Signal metrics for aggregated logging
_signal_metrics = {
    "counters": defaultdict(int),
    "lock": Lock(),
    "batch_counters": defaultdict(int),
}


def record_signal_metric(operation, entity_type, date_obj=None):
    """Record a signal operation for metrics reporting"""
    if not SIGNAL_METRICS_ENABLED:
        return

    date_str = date_obj.isoformat() if date_obj else "all"

    with _signal_metrics["lock"]:
        # Record in overall metrics
        key = f"{operation}:{entity_type}:{date_str}"
        _signal_metrics["counters"][key] += 1

        # Record in batch metrics for periodic logging
        batch_key = f"{operation}:{entity_type}"
        _signal_metrics["batch_counters"][batch_key] += 1

        # Log batch metrics periodically
        if _signal_metrics["batch_counters"][batch_key] % SIGNAL_LOG_BATCH_SIZE == 0:
            count = _signal_metrics["batch_counters"][batch_key]
            logger.debug(f"Signal batch: {batch_key} processed {count} operations")


def prevent_recursion(signal_handler):
    """Decorator to prevent recursive signal calls"""

    @wraps(signal_handler)
    def wrapper(sender, instance, **kwargs):
        if hasattr(instance, "_signal_is_handling") and instance._signal_is_handling:
            return
        try:
            instance._signal_is_handling = True
            return signal_handler(sender, instance, **kwargs)
        finally:
            instance._signal_is_handling = False

    return wrapper


@receiver(post_save, sender=Decision)
@prevent_recursion
def update_organization_coverage(sender, instance, **kwargs):
    """Update DateCoverage when a Decision is created or modified"""
    if not instance.organization or not instance.issue_date:
        return

    date_obj = instance.issue_date.date()
    record_signal_metric("save", "organization", date_obj)

    # Use transaction to ensure database consistency
    with transaction.atomic():
        # Get organization count
        current_count = Decision.objects.filter(
            organization=instance.organization, issue_date_day=date_obj
        ).count()

        # Handle race condition: multiple workers may try to create simultaneously
        try:
            coverage, created = DateCoverage.objects.get_or_create(
                date=date_obj,
                organization=instance.organization,
                unit=None,
                signer=None,
                defaults={"decision_count": current_count},
            )
            if not created and coverage.decision_count != current_count:
                coverage.decision_count = current_count
                coverage.save(update_fields=["decision_count", "last_updated"])
        except DateCoverage.MultipleObjectsReturned:
            # Race condition created duplicates - clean them up
            logger.warning(
                f"Multiple DateCoverage found for org {instance.organization.uid} on {date_obj}, cleaning up duplicates"
            )
            duplicates = DateCoverage.objects.filter(
                date=date_obj,
                organization=instance.organization,
                unit=None,
                signer=None,
            ).order_by("id")
            # Keep the first one, update its count
            keeper = duplicates.first()
            keeper.decision_count = current_count
            keeper.save(update_fields=["decision_count", "last_updated"])
            # Delete the rest
            duplicates.exclude(id=keeper.id).delete()

    # Detailed logging only at debug level
    # logger.debug(f"Updated org coverage for {instance.organization.uid} on {date_obj}: {current_count}")


@receiver(m2m_changed, sender=Decision.signers.through)
@prevent_recursion
def update_signer_coverage(sender, instance, action, pk_set, **kwargs):
    """Update DateCoverage for signers when relationships change"""
    if action not in ("post_add", "post_remove"):
        return

    if not instance.issue_date:
        return

    date_obj = instance.issue_date.date()
    record_signal_metric("m2m", "signer", date_obj)

    # Use one transaction for all updates
    with transaction.atomic():
        if action == "post_add" and pk_set:
            for signer_id in pk_set:
                current_count = Decision.objects.filter(
                    signers__uid=signer_id, issue_date_day=date_obj
                ).count()

                try:
                    coverage, created = DateCoverage.objects.get_or_create(
                        date=date_obj,
                        organization=None,
                        unit=None,
                        signer_id=signer_id,
                        defaults={"decision_count": current_count},
                    )
                    if not created and coverage.decision_count != current_count:
                        coverage.decision_count = current_count
                        coverage.save(update_fields=["decision_count", "last_updated"])
                except DateCoverage.MultipleObjectsReturned:
                    # Race condition created duplicates - clean them up
                    logger.warning(
                        f"Multiple DateCoverage found for signer {signer_id} on {date_obj}, cleaning up duplicates"
                    )
                    duplicates = DateCoverage.objects.filter(
                        date=date_obj, organization=None, unit=None, signer_id=signer_id
                    ).order_by("id")
                    keeper = duplicates.first()
                    keeper.decision_count = current_count
                    keeper.save(update_fields=["decision_count", "last_updated"])
                    duplicates.exclude(id=keeper.id).delete()
                # logger.debug(f"Updated signer coverage for {signer_id} on {date_obj}: {current_count}")


@receiver(post_delete, sender=Decision)
@prevent_recursion
def update_coverage_on_delete(sender, instance, **kwargs):
    """Update DateCoverage when a Decision is deleted"""
    if not instance.issue_date:
        return

    date_obj = instance.issue_date.date()
    record_signal_metric("delete", "decision", date_obj)

    # Update organization coverage in a single transaction
    with transaction.atomic():
        if instance.organization:
            current_count = Decision.objects.filter(
                organization=instance.organization, issue_date_day=date_obj
            ).count()

            if current_count > 0:
                try:
                    coverage, created = DateCoverage.objects.get_or_create(
                        date=date_obj,
                        organization=instance.organization,
                        unit=None,
                        signer=None,
                        defaults={"decision_count": current_count},
                    )
                    if not created and coverage.decision_count != current_count:
                        coverage.decision_count = current_count
                        coverage.save(update_fields=["decision_count", "last_updated"])
                except DateCoverage.MultipleObjectsReturned:
                    # Race condition created duplicates - clean them up
                    logger.warning(
                        f"Multiple DateCoverage found for org {instance.organization.uid} on {date_obj}, cleaning up duplicates"
                    )
                    duplicates = DateCoverage.objects.filter(
                        date=date_obj,
                        organization=instance.organization,
                        unit=None,
                        signer=None,
                    ).order_by("id")
                    keeper = duplicates.first()
                    keeper.decision_count = current_count
                    keeper.save(update_fields=["decision_count", "last_updated"])
                    duplicates.exclude(id=keeper.id).delete()
                # logger.debug(f"Updated org coverage for {instance.organization.uid} on {date_obj}: {current_count}")
            else:
                DateCoverage.objects.filter(
                    date=date_obj,
                    organization=instance.organization,
                    unit=None,
                    signer=None,
                ).delete()
                # logger.debug(f"Removed empty org coverage for {instance.organization.uid} on {date_obj}")


@receiver(post_save, sender=Decision)
@prevent_recursion
def queue_document_processing(sender, instance, created, **kwargs):
    """Automatically queue document processing for new decisions with documents

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Use run_decision_pipeline_task instead for orchestrated processing.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        # logger.debug(
        #     f"⏭️ Skipping legacy document queue for {instance.ada} "
        #     f"(orchestrator mode enabled - use run_decision_pipeline_task instead)"
        # )
        return

    if created and instance.document_url:
        # Import here to avoid circular imports
        from core.tasks import process_document_task

        transaction.on_commit(lambda: process_document_task.delay(instance.ada))
        logger.debug(
            f"Queued document processing for decision {instance.ada} (will run after transaction commit)"
        )


@receiver(post_save, sender=DocumentExtraction)
def index_document_in_opensearch(sender, instance, created, **kwargs):
    """Index document in OpenSearch when extraction completes

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Orchestrator's _step_index_opensearch() handles indexing explicitly.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        # logger.debug(
        #     f"⏭️ Skipping legacy OpenSearch indexing for {instance.decision.ada} "
        #     f"(orchestrator mode enabled - orchestrator handles indexing)"
        # )
        return

    # Add comprehensive logging to understand signal behavior
    logger.debug(
        f"[REMOTECALL] Signal triggered for {instance.decision.ada}: "
        f"status={instance.extraction_status}, created={created}, "
        f"has_text={bool(instance.raw_text)}"
    )

    if instance.extraction_status == "COMPLETED" and instance.raw_text:
        logger.debug(f"[SCAN] Starting OpenSearch indexing for {instance.decision.ada}")

        try:
            opensearch_service = OpenSearchService()

            # Prepare document for indexing
            document_data = {
                "decision_id": instance.decision.id,  # Fixed: use .id not .uid
                "ada": instance.decision.ada,
                "title": instance.decision.subject or "",
                "content": instance.raw_text,  # Let service handle truncation
                "organization": (
                    str(instance.decision.organization)
                    if instance.decision.organization
                    else ""
                ),  # Fixed!
                "decision_type": (
                    str(instance.decision.decision_type)
                    if instance.decision.decision_type
                    else ""
                ),  # Fixed!
                "issue_date": (
                    instance.decision.issue_date.isoformat()
                    if instance.decision.issue_date
                    else None
                ),
                "extraction_date": (
                    instance.extraction_date.isoformat()
                    if instance.extraction_date
                    else None
                ),
                "character_count": instance.character_count,
                "page_count": instance.page_count,
            }

            logger.debug(
                f"[FILE] Document data prepared for {instance.decision.ada}: {len(document_data['content'])} chars"
            )

            success = opensearch_service.index_document(document_data)
            if success:
                logger.debug(
                    f"[OK] Auto-indexed document for decision {instance.decision.ada} in OpenSearch"
                )
            else:
                logger.error(
                    f"[ERROR] Failed to auto-index document for decision {instance.decision.ada}"
                )

        except Exception as e:
            logger.error(
                f"[CRASH] Error auto-indexing document for decision {instance.decision.ada}: {e}",
                exc_info=True,
            )
    else:
        # Log why signal didn't proceed
        reasons = []
        if instance.extraction_status != "COMPLETED":
            reasons.append(f"status={instance.extraction_status}")
        if not instance.raw_text:
            reasons.append("no raw_text")

        if reasons:
            logger.debug(
                f"⏭️ Skipping indexing for {instance.decision.ada}: {', '.join(reasons)}"
            )


# Health Check Signals
# These signals ensure health checks are automatically updated when decisions change


@receiver(post_save, sender=Decision)
def decision_saved_health_check_signal(sender, instance, created, **kwargs):
    """Mark health check for refresh when decision is saved

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Orchestrator creates/updates health checks explicitly.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        return

    from datetime import timedelta

    from core.models.decision_health import DecisionHealthCheck
    from django.utils import timezone

    try:
        health_check = instance.health_check
        # Mark for refresh by setting old timestamp
        old_time = timezone.now() - timedelta(hours=2)
        health_check.last_checked_at = old_time
        health_check.save(update_fields=["last_checked_at"])

        if created:
            logger.debug(
                f"New decision {instance.ada} - marked health check for refresh"
            )
        else:
            logger.debug(
                f"Decision {instance.ada} updated - marked health check for refresh"
            )

    except DecisionHealthCheck.DoesNotExist:
        # No health check exists yet - will be created on next automated run
        pass
    except Exception as e:
        logger.warning(
            f"Failed to update health check timestamp for {instance.ada}: {e}"
        )


@receiver(post_save, sender=DocumentExtraction)
def document_extraction_health_check_signal(sender, instance, created, **kwargs):
    """Schedule health check when document extraction status changes

    [WARN]️ DISABLED when USE_ORCHESTRATOR_MODE=True
    Orchestrator updates DecisionHealthCheck after each pipeline step.
    """
    # Skip if orchestrator mode is enabled
    if getattr(settings, "USE_ORCHESTRATOR_MODE", False):
        return

    from core.models.document_analysis import ProcessingStatus

    if not instance.decision:
        return

    # Only trigger for significant status changes
    significant_statuses = [
        ProcessingStatus.COMPLETED,
        ProcessingStatus.FAILED,
        ProcessingStatus.NEEDS_VISION,
    ]

    if instance.extraction_status in significant_statuses:
        logger.debug(
            f"Document extraction {instance.extraction_status} for {instance.decision.ada} - scheduling health check"
        )

        # Queue immediate health check
        try:
            from core.tasks.health_check_tasks import check_single_decision_health

            check_single_decision_health.delay(instance.decision.ada)
        except Exception as e:
            logger.warning(
                f"Failed to queue health check for {instance.decision.ada}: {e}"
            )
