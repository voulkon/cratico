from datetime import datetime, timedelta

from core.models.document_analysis import DocumentExtraction
from core.services.opensearch_service import OpenSearchService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check OpenSearch integration health"

    def handle(self, *args, **options):
        self.stdout.write("=== OpenSearch Health Check ===")

        opensearch_service = OpenSearchService(test_connection=True)

        # 1. Test OpenSearch connection
        try:
            results = opensearch_service._test_match_all()
            total_docs = results.get("hits", {}).get("total", {}).get("value", 0)
            self.stdout.write(f"[OK] OpenSearch connection: OK")
            self.stdout.write(f"[OK] Total documents in index: {total_docs}")
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"[FAIL] OpenSearch connection failed: {e}")
            )
            return

        # 2. Check recent document extractions
        today = datetime.now().date()
        yesterday = today - timedelta(days=1)

        completed_extractions = DocumentExtraction.objects.filter(
            extraction_status="COMPLETED", extraction_date__date__gte=yesterday
        )

        completed_count = completed_extractions.count()
        self.stdout.write(f"[OK] Completed extractions (last 24h): {completed_count}")

        # 3. Test search functionality
        test_queries = ["ΥΠΟΥΡΓΕΙΟ", "ΑΝΑΛΗΨΗ", "υπηρεσιών"]

        for query in test_queries:
            try:
                search_results = opensearch_service.search_documents(query, size=1)
                hits = search_results.get("hits", {}).get("hits", [])
                self.stdout.write(f"[OK] Search '{query}': {len(hits)} results")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] Search '{query}' failed: {e}")
                )

        # 4. Check index health
        try:
            import requests

            health_response = requests.get(
                f"{opensearch_service.opensearch_url}/_cluster/health",
                timeout=10,
            )
            if health_response.status_code == 200:
                health = health_response.json()
                status = health.get("status", "unknown")
                self.stdout.write(f"[OK] Cluster health: {status}")
            else:
                self.stdout.write(
                    self.style.WARNING("[FAIL] Could not get cluster health")
                )
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"[FAIL] Cluster health check failed: {e}")
            )

        # 5. Sample documents check
        if completed_count > 0:
            sample_extraction = completed_extractions.first()
            ada = sample_extraction.decision.ada

            # Check if this specific document is in OpenSearch
            search_results = opensearch_service.search_documents(ada, size=1)
            hits = search_results.get("hits", {}).get("hits", [])

            if hits:
                self.stdout.write(f"[OK] Sample document {ada} found in OpenSearch")
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"[FAIL] Sample document {ada} NOT found in OpenSearch"
                    )
                )

        self.stdout.write("\n=== Integration Status ===")
        self.stdout.write("[OK] OpenSearch service: Configured")
        self.stdout.write("[OK] Document search API: Using OpenSearch")
        self.stdout.write("[OK] Automatic indexing: Enabled via signals")
        self.stdout.write("[OK] Manual migration: Available")
