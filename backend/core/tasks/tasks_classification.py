"""
Celery task for periodic classification of decisions.

This task runs on a schedule (e.g., hourly) to classify any unclassified decisions.
It processes decisions in small batches to avoid overwhelming the database.
"""

from celery import shared_task
from core.services.direct_assignment_detection_service import classification_service
from loguru import logger


@shared_task(bind=True, name="classify_unclassified_decisions")
def classify_unclassified_decisions(self, batch_size: int = 500):
    """
    Classify decisions that haven't been classified yet.

    This task runs periodically (configured in Celery Beat) to ensure all decisions
    get classified. It processes recent decisions first (ordered by issue_date desc).

    Args:
        batch_size: Number of decisions to process in this run (default: 500)

    Returns:
        Dict with statistics
    """
    logger.info(
        f"Task {self.request.id}: Starting periodic classification (batch_size={batch_size})"
    )

    try:
        # Get unclassified decisions (most recent first)
        unclassified = classification_service.get_unclassified_decisions(
            limit=batch_size
        )

        count = unclassified.count()

        if count == 0:
            logger.info("No unclassified decisions found - all up to date!")
            return {
                "status": "success",
                "message": "No decisions to classify",
                "total_processed": 0,
            }

        logger.info(f"Found {count} unclassified decisions, processing...")

        # Classify in bulk
        stats = classification_service.bulk_classify(unclassified, batch_size=100)

        logger.success(
            f"Task {self.request.id}: Classified {stats['total_processed']} decisions, "
            f"found {stats['direct_assignments']} direct assignments"
        )

        return {"status": "success", "task_id": self.request.id, **stats}

    except Exception as e:
        logger.error(
            f"Task {self.request.id}: Classification task failed: {e}", exc_info=True
        )
        raise


@shared_task(bind=True, name="reclassify_outdated_decisions")
def reclassify_outdated_decisions(self, batch_size: int = 500):
    """
    Reclassify decisions with outdated classifier version.

    Use this task when the classification algorithm changes and you need to
    re-run classification on existing decisions.

    Args:
        batch_size: Number of decisions to process in this run

    Returns:
        Dict with statistics
    """
    logger.info(
        f"Task {self.request.id}: Starting re-classification of outdated decisions"
    )

    try:
        # Get decisions with outdated classifier version
        outdated = classification_service.get_outdated_classifications(limit=batch_size)

        count = outdated.count()

        if count == 0:
            logger.info("No outdated classifications found")
            return {
                "status": "success",
                "message": "No decisions need reclassification",
                "total_processed": 0,
            }

        logger.info(
            f"Found {count} decisions with outdated classifier, reprocessing..."
        )

        # Reclassify in bulk
        stats = classification_service.bulk_classify(outdated, batch_size=100)

        logger.success(
            f"Task {self.request.id}: Reclassified {stats['total_processed']} decisions"
        )

        return {"status": "success", "task_id": self.request.id, **stats}

    except Exception as e:
        logger.error(
            f"Task {self.request.id}: Reclassification task failed: {e}", exc_info=True
        )
        raise


@shared_task(bind=True, name="classify_decision_by_ada")
def classify_decision_by_ada(self, ada: str):
    """
    Classify a single decision by ADA.

    Useful for manual triggering or debugging.

    Args:
        ada: The ADA of the decision to classify

    Returns:
        Dict with classification result
    """
    logger.info(f"Task {self.request.id}: Classifying single decision {ada}")

    try:
        from core.models.decisions import Decision

        decision = Decision.objects.select_related("decision_type").get(ada=ada)
        classification = classification_service.classify_and_save(decision)

        result = {
            "status": "success",
            "ada": ada,
            "is_direct_assignment": classification.is_direct_assignment,
            "classifier_version": classification.classifier_version,
            "classified_at": classification.classified_at.isoformat(),
            "task_id": self.request.id,
        }

        logger.info(
            f"Task {self.request.id}: Decision {ada} classified: "
            f"is_direct_assignment={classification.is_direct_assignment}"
        )

        return result

    except Decision.DoesNotExist:
        error_msg = f"Decision {ada} not found"
        logger.error(error_msg)
        return {
            "status": "error",
            "ada": ada,
            "error": error_msg,
            "task_id": self.request.id,
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(
            f"Task {self.request.id}: Failed to classify {ada}: {error_msg}",
            exc_info=True,
        )
        return {
            "status": "error",
            "ada": ada,
            "error": error_msg,
            "task_id": self.request.id,
        }
