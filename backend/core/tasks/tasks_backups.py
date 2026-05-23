from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded, WorkerLostError
from core.models import Backup
from core.services.backup_service import BackupService
from loguru import logger


@shared_task(bind=True)
def create_backup_task(self, backup_id):
    """Create a backup (PostgreSQL or OpenSearch)

    Args:
        backup_id: The ID of the Backup model instance

    Raises:
        Exception: If backup fails, to signal Celery task failure
    """
    backup = None

    try:
        backup = Backup.objects.get(id=backup_id)

        # Initialize service - this validates credentials and bucket access
        try:
            service = BackupService()
        except ValueError as e:
            # Credential or configuration error - update backup status
            logger.error(f"Failed to initialize BackupService: {e}")
            backup.status = Backup.Status.FAILED
            backup.logs += f"Configuration Error: {str(e)}\n"
            backup.save()
            raise

        if backup.backup_type == Backup.BackupType.POSTGRES:
            logger.info(f"Starting PostgreSQL backup {backup_id}")
            # Use streaming setting from the backup instance
            service.create_postgres_backup(
                backup_id, use_streaming=backup.use_streaming
            )
        elif backup.backup_type == Backup.BackupType.OPENSEARCH:
            logger.info(f"Starting OpenSearch backup {backup_id}")
            service.create_opensearch_snapshot(backup_id)
        else:
            raise ValueError(f"Unknown backup type: {backup.backup_type}")

        logger.info(f"Backup {backup_id} completed successfully")

    except (SoftTimeLimitExceeded, WorkerLostError) as e:
        # Task was terminated or worker lost
        logger.warning(f"Backup task {backup_id} was terminated: {e}")
        if backup:
            backup.status = Backup.Status.FAILED
            backup.logs += f"\n[DENIED] Task was terminated/cancelled\n"
            backup.save()
        raise
    except Backup.DoesNotExist:
        logger.error(f"Backup {backup_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Backup task {backup_id} failed: {e}")
        # Exception is already logged in the Backup model by the service
        # Re-raise to mark Celery task as failed
        raise


@shared_task(bind=True)
def restore_backup_task(self, backup_id):
    """Restore a backup (PostgreSQL or OpenSearch)

    Args:
        backup_id: The ID of the Backup model instance to restore

    Raises:
        Exception: If restore fails, to signal Celery task failure
    """
    service = BackupService()

    try:
        backup = Backup.objects.get(id=backup_id)

        # Update status to indicate restore is starting
        backup.logs += "Starting restore process...\n"
        backup.save()

        success = False
        message = ""

        if backup.backup_type == Backup.BackupType.POSTGRES:
            logger.info(f"Starting PostgreSQL restore {backup_id}")
            success, message = service.restore_postgres_backup(backup_id)
        elif backup.backup_type == Backup.BackupType.OPENSEARCH:
            logger.info(f"Starting OpenSearch restore {backup_id}")
            success, message = service.restore_opensearch_snapshot(backup_id)
        else:
            raise ValueError(f"Unknown backup type: {backup.backup_type}")

        backup.logs += f"Restore finished. Success: {success}. Message: {message}\n"
        backup.save()

        if not success:
            logger.error(f"Restore {backup_id} failed: {message}")
            raise Exception(f"Restore failed: {message}")
        else:
            logger.info(f"Restore {backup_id} completed successfully")

    except (SoftTimeLimitExceeded, WorkerLostError) as e:
        # Task was terminated or worker lost
        logger.warning(f"Restore task {backup_id} was terminated: {e}")
        raise
    except Backup.DoesNotExist:
        logger.error(f"Backup {backup_id} does not exist")
        raise
    except Exception as e:
        logger.error(f"Restore task {backup_id} failed: {e}")
        raise
