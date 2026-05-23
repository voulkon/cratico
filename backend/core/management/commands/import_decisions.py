from datetime import datetime

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.services.decision_ingestion_service import DecisionIngestionService
from core.services.opensearch_service import OpenSearchService
from core.tasks import index_recent_documents
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Import decisions from Diavgeia API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            required=True,
            help="Start date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            required=True,
            help="End date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--increment-days",
            type=int,
            default=30,
            help="Number of days per increment",
        )
        parser.add_argument(
            "--distributed",
            action="store_true",
            help="Use Celery for distributed processing",
        )
        parser.add_argument("--org", type=str, help="Organization ID or latin name")
        parser.add_argument("--unit", type=str, help="Unit ID")
        parser.add_argument("--signer", type=str, help="Signer ID")
        parser.add_argument("--type", type=str, help="Decision type")
        parser.add_argument(
            "--check-opensearch",
            action="store_true",
            help="Check OpenSearch indexing status after import",
        )
        parser.add_argument(
            "--index-documents",
            action="store_true",
            help="Trigger document indexing to OpenSearch after import",
        )

    def handle(self, *args, **options):
        # Check OpenSearch status before import
        if options.get("check_opensearch"):
            opensearch_service = OpenSearchService()
            initial_count = self._get_opensearch_count(opensearch_service)
            self.stdout.write(f"OpenSearch documents before import: {initial_count}")

        # Create components
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter()
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        search_params = {}
        for param in ["org", "unit", "signer", "type"]:
            if options[param]:
                search_params[param] = options[param]

        # Run ingestion
        start_date = options["start_date"]
        end_date = options["end_date"]

        self.stdout.write(f"Fetching decisions from {start_date} to {end_date}...")

        decisions = service.fetch_decisions_for_period(
            start_date=start_date,
            end_date=end_date,
            date_increment_days=options["increment_days"],
            search_params=search_params,
            distributed=options["distributed"],
            save_to_db=True,
        )

        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed {len(decisions)} decisions")
        )

        # Trigger document indexing if requested
        if options.get("index_documents"):
            self.stdout.write("Triggering document indexing to OpenSearch...")
            task_result = index_recent_documents.delay(limit=len(decisions) + 100)
            self.stdout.write(f"Indexing task started: {task_result.id}")

        # Check OpenSearch status after import
        if options.get("check_opensearch"):
            opensearch_service = OpenSearchService()
            final_count = self._get_opensearch_count(opensearch_service)
            self.stdout.write(f"OpenSearch documents after import: {final_count}")
            self.stdout.write(
                f"Documents added to OpenSearch: {final_count - initial_count}"
            )

            # Check recent document extractions
            from core.models.document_analysis import DocumentExtraction

            recent_extractions = DocumentExtraction.objects.filter(
                extraction_status="COMPLETED",
                extraction_date__gte=datetime.now().replace(hour=0, minute=0, second=0),
            ).count()

            self.stdout.write(
                f"Document extractions completed today: {recent_extractions}"
            )

    def _get_opensearch_count(self, opensearch_service):
        """Get total document count in OpenSearch"""
        try:
            results = opensearch_service._test_match_all()
            return results.get("hits", {}).get("total", {}).get("value", 0)
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Could not get OpenSearch count: {e}")
            )
            return 0
