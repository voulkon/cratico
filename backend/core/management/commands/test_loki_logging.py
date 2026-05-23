"""
Django management command to test Loki logging integration
"""

import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger("diavgeia_project")


class Command(BaseCommand):
    help = "Test Loki logging integration with various log levels and messages"

    def handle(self, *args, **options):
        self.stdout.write("[TEST] Testing Loki integration via Django logging...")

        # Test different log levels
        logger.debug("[CONFIG] DEBUG: This is a debug message for troubleshooting")
        logger.info("[COPY] INFO: Application successfully connected to database")
        logger.warning("[WARN]️  WARNING: High memory usage detected - 85% utilization")
        logger.error("[ERROR] ERROR: Failed to process document with ID 12345")

        # Test structured logging with context
        logger.info(
            "[USER] User authentication successful",
            extra={
                "user_id": "user_123",
                "session_id": "sess_abc456",
                "ip_address": "192.168.1.100",
            },
        )

        # Application-specific test logs
        logger.info("[FILE] Processing new document: Contract_2024_001.pdf")
        logger.info("[SCAN] OpenSearch indexing completed for 50 documents")
        logger.info("[CRIT] Celery task 'index_recent_documents' executed successfully")
        logger.info("[CHART] Daily backup task completed - 2.3GB backed up")

        # Test error scenarios
        logger.error("[CRASH] Database connection timeout after 30 seconds")
        logger.error("[STOP] OpenSearch cluster health check failed")
        logger.warning("[WARN]️  Redis memory usage is at 90% capacity")

        # Performance logs
        logger.info("[END] API request completed in 245ms - GET /api/documents/")
        logger.info("[RETRY] Background sync task took 1.2s to process 100 records")

        logger.info("[OK] Django-based Loki integration test completed!")
        self.stdout.write(
            self.style.SUCCESS("[OK] Loki integration test completed successfully!")
        )
