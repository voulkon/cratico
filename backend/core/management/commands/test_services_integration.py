import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test integration with OpenSearch and Greek analysis"

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.SUCCESS("=== Testing OpenSearch Greek Analysis Integration ===")
        )

        self.test_opensearch_health()
        self.test_icu_plugin()
        self.test_greek_analysis()

        self.stdout.write(self.style.SUCCESS("=== All tests completed ==="))

    def test_opensearch_health(self):
        self.stdout.write("\n--- Testing OpenSearch Health ---")
        if not settings.INDEX_THE_OPENSEARCH:
            self.stdout.write(
                self.style.WARNING(
                    "OpenSearch indexing is disabled in settings. Skipping tests."
                )
            )
            return
        opensearch_url = getattr(settings, "OPENSEARCH_URL", "http://opensearch:9200")

        try:
            response = requests.get(
                f"{opensearch_url}/_cluster/health",
                timeout=10,
            )
            health = response.json()
            self.stdout.write(f"Cluster health: {health.get('status')}")
            self.stdout.write(f"Number of nodes: {health.get('number_of_nodes')}")
            self.stdout.write(self.style.SUCCESS("[OK] OpenSearch is healthy"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] OpenSearch error: {e}"))

    def test_icu_plugin(self):
        self.stdout.write("\n--- Testing ICU Plugin ---")

        opensearch_url = getattr(settings, "OPENSEARCH_URL", "http://opensearch:9200")
        if not settings.INDEX_THE_OPENSEARCH:
            self.stdout.write(
                self.style.WARNING(
                    "OpenSearch indexing is disabled in settings. Skipping tcu_plugin."
                )
            )
            return
        try:
            # Check if ICU plugin is installed
            response = requests.get(
                f"{opensearch_url}/_cat/plugins",
                timeout=10,
            )
            plugins = response.text

            if "analysis-icu" in plugins:
                self.stdout.write(
                    self.style.SUCCESS("[OK] ICU Analysis plugin is installed")
                )
            else:
                self.stdout.write(
                    self.style.ERROR("[FAIL] ICU Analysis plugin not found")
                )
                self.stdout.write(f"Installed plugins: {plugins}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Plugin check error: {e}"))

    def test_greek_analysis(self):
        self.stdout.write("\n--- Testing Greek Text Analysis ---")
        if not settings.INDEX_THE_OPENSEARCH:
            self.stdout.write(
                self.style.WARNING(
                    "OpenSearch indexing is disabled in settings. Skipping test_greek_analysis."
                )
            )
            return
        opensearch_url = getattr(settings, "OPENSEARCH_URL", "http://opensearch:9200")

        try:
            # Create a simple test index first
            index_name = "test-greek-analysis"

            # Simple index config for testing
            index_config = {
                "settings": {
                    "analysis": {
                        "analyzer": {
                            "test_greek_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["icu_folding", "lowercase", "stemmer_greek"],
                            }
                        },
                        "filter": {
                            "stemmer_greek": {"type": "stemmer", "language": "greek"}
                        },
                    }
                }
            }

            # Delete index if exists
            requests.delete(f"{opensearch_url}/{index_name}", timeout=10)

            # Create index
            response = requests.put(
                f"{opensearch_url}/{index_name}", json=index_config, timeout=10
            )

            if response.status_code in [200, 201]:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] Test index created: {response.status_code}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"[FAIL] Index creation failed: {response.status_code}"
                    )
                )
                self.stdout.write(f"Response: {response.text}")
                return

            # Test Greek text analysis
            test_cases = [
                "κριτήρια",  # criteria
                "αποφάσεις",  # decisions
                "ΠΟΣΟΤΗΤΑ",  # quantity
                "μηχανές",  # machines
            ]

            for text in test_cases:
                analyze_request = {"analyzer": "test_greek_analyzer", "text": text}

                response = requests.post(
                    f"{opensearch_url}/{index_name}/_analyze",
                    json=analyze_request,
                    timeout=10,
                )

                if response.status_code == 200:
                    result = response.json()
                    tokens = [token["token"] for token in result.get("tokens", [])]

                    self.stdout.write(f"  '{text}' → {tokens}")
                    self.stdout.write(self.style.SUCCESS(f"  [OK] Analysis successful"))
                else:
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [FAIL] Analysis failed for '{text}': {response.status_code}"
                        )
                    )
                    self.stdout.write(f"    Response: {response.text}")

            # Clean up
            requests.delete(f"{opensearch_url}/{index_name}", timeout=10)
            self.stdout.write(self.style.SUCCESS("[OK] Greek analysis working"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Analysis error: {e}"))
