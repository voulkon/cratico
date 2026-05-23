"""
Test command to process a single decision through the full pipeline.
Use this to verify that DecisionPipelineOrchestrator works correctly.
"""

from core.models.decision_health import DecisionHealthCheck
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "Test processing a single decision through the full pipeline"

    def add_arguments(self, parser):
        parser.add_argument("ada", type=str, help="The ADA of the decision to process")
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reprocessing even if already processed",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            dest="use_async",
            help="Run as Celery task instead of synchronously",
        )

    def handle(self, *args, **options):
        ada = options["ada"]
        force = options["force"]
        use_async = options["use_async"]

        self.stdout.write("=" * 80)
        self.stdout.write(
            self.style.SUCCESS(f"[CONFIG] Testing Pipeline for Decision: {ada}")
        )
        self.stdout.write(f"   Force reprocess: {force}")
        self.stdout.write(f"   Async mode: {use_async}")
        self.stdout.write("=" * 80)

        if use_async:
            # Use Celery task
            from core.tasks.tasks_documents import run_decision_pipeline_task

            result = run_decision_pipeline_task.delay(ada, force_reprocess=force)

            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] Queued pipeline task for {ada}\n"
                    f"   Task ID: {result.id}\n"
                    f"   Check Celery logs for progress\n"
                    f"   View results in: Admin → Decision Health Checks"
                )
            )

        else:
            # Run synchronously
            try:
                orchestrator = DecisionPipelineOrchestrator()
                health_check = orchestrator.run_pipeline(
                    decision_ada=ada, force_reprocess=force
                )

                self.stdout.write("\n" + "=" * 80)
                self.stdout.write(self.style.SUCCESS("[OK] Pipeline Completed"))
                self.stdout.write("=" * 80)

                self._print_health_check(health_check)

                self.stdout.write("\n" + "=" * 80)
                self.stdout.write(
                    f"View full details in Admin:\n"
                    f"   → Decision Health Checks → filter by ADA: {ada}"
                )
                self.stdout.write("=" * 80)

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"[ERROR] Pipeline failed: {str(e)}")
                )
                logger.exception(f"Pipeline error for {ada}")
                raise

    def _print_health_check(self, health_check: DecisionHealthCheck):
        """Pretty print health check results"""

        status_icon = {
            "HEALTHY": "[OK]",
            "WARNING": "[WARN]️",
            "ERROR": "[ERROR]",
            "UNKNOWN": "[UNKNOWN]",
        }

        self.stdout.write(
            f"\n[CHART] Overall Status: {status_icon.get(health_check.overall_status, '?')} {health_check.overall_status}"
        )
        self.stdout.write("\nComponent Status:")
        self.stdout.write("-" * 80)

        components = [
            (
                "Ingestion",
                health_check.ingestion_status,
                health_check.ingestion_error_message,
            ),
            (
                "Entity Extraction",
                health_check.entities_status,
                health_check.entities_error_message,
            ),
            (
                "Company Enrichment",
                health_check.relations_status,
                health_check.relations_error_message,
            ),
            (
                "Document Processing",
                health_check.document_extraction_status,
                health_check.document_extraction_error_message,
            ),
            (
                "OpenSearch Indexing",
                health_check.opensearch_status,
                health_check.opensearch_error_message,
            ),
            (
                "Coverage Metrics",
                health_check.coverage_status,
                health_check.coverage_error_message,
            ),
        ]

        for name, status, error in components:
            icon = status_icon.get(status, "?")
            self.stdout.write(f"   {icon} {name:<25} {status}")
            if error:
                self.stdout.write(f"      └─ Error: {error[:100]}")

        self.stdout.write("-" * 80)
