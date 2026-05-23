from pathlib import Path

import requests
import yaml
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Setup OpenSearch with Greek language support and stemming"

    def handle(self, *args, **options):
        opensearch_url = getattr(settings, "OPENSEARCH_URL", "http://opensearch:9200")

        self.stdout.write(
            self.style.SUCCESS("=== Setting up OpenSearch for Greek Documents ===")
        )

        # 1. Create index template for Greek documents
        self.create_greek_index_template(opensearch_url)

        # 2. Create the main Greek documents index
        self.create_greek_documents_index(opensearch_url)

        # 3. Test the setup
        self.test_greek_analysis(opensearch_url)

        self.stdout.write(
            self.style.SUCCESS("=== OpenSearch Greek setup completed ===")
        )

    def load_template_config(self):
        """
        Load index template configuration from YAML file.
        Falls back to hardcoded config if file doesn't exist.
        """
        config_path = (
            Path(__file__).parent.parent.parent.parent.parent
            / "docker"
            / "opensearch-config"
            / "index-template-config.yml"
        )

        if config_path.exists():
            self.stdout.write(f"[FILE] Loading template config from: {config_path}")
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    config = yaml.safe_load(f)
                    return {
                        "index_patterns": config.get(
                            "index_patterns", ["greek-*", "diavgeia-*"]
                        ),
                        "template": {
                            "settings": config.get("settings", {}),
                            "mappings": config.get("mappings", {}),
                        },
                    }
            except Exception as e:
                self.stdout.write(
                    self.style.WARNING(f"[WARN]️  Failed to load YAML config: {e}")
                )
                self.stdout.write("   Falling back to hardcoded configuration...")
        else:
            self.stdout.write("ℹ️  No YAML config found, using hardcoded configuration")

        # Fallback to hardcoded config
        return {
            "index_patterns": ["greek-*", "diavgeia-*"],
            "template": {
                "settings": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "index.max_result_window": 100000,
                    "analysis": {
                        "analyzer": {
                            "greek_text_analyzer": {
                                "type": "custom",
                                "tokenizer": "standard",
                                "filter": ["icu_folding", "lowercase", "greek_stemmer"],
                            }
                        },
                        "filter": {
                            "greek_stemmer": {"type": "stemmer", "language": "greek"}
                        },
                    },
                },
                "mappings": {
                    "properties": {
                        "decision_id": {"type": "integer"},
                        "ada": {"type": "keyword"},
                        "title": {"type": "text", "analyzer": "greek_text_analyzer"},
                        "content": {"type": "text", "analyzer": "greek_text_analyzer"},
                    }
                },
            },
        }

    def create_greek_index_template(self, opensearch_url):
        self.stdout.write("\n--- Creating Greek Index Template ---")

        # Load template configuration from YAML or use hardcoded fallback
        template_config = self.load_template_config()

        try:
            response = requests.put(
                f"{opensearch_url}/_index_template/greek-documents-template",
                json=template_config,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.stdout.write(
                    self.style.SUCCESS("[OK] Greek index template created")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"[FAIL] Template creation failed: {response.status_code}"
                    )
                )
                self.stdout.write(f"Response: {response.text}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Template creation error: {e}"))

    def create_greek_documents_index(self, opensearch_url):
        self.stdout.write("\n--- Creating Main Greek Documents Index ---")

        try:
            # Check if index already exists
            check_response = requests.head(
                f"{opensearch_url}/diavgeia-documents",
                timeout=10,
            )

            if check_response.status_code == 200:
                self.stdout.write(
                    self.style.SUCCESS(
                        "[OK] Main documents index already exists - skipping creation"
                    )
                )
                self.stdout.write(
                    "  [INFO] To recreate the index, delete it first manually or use --force flag"
                )
                return

            # Index doesn't exist, create it
            response = requests.put(
                f"{opensearch_url}/diavgeia-documents",
                timeout=10,
            )

            if response.status_code in [200, 201]:
                self.stdout.write(
                    self.style.SUCCESS("[OK] Main documents index created")
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"[FAIL] Index creation failed: {response.status_code}"
                    )
                )
                self.stdout.write(f"Response: {response.text}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] Index creation error: {e}"))

    def test_greek_analysis(self, opensearch_url):
        self.stdout.write("\n--- Testing Greek Analysis Setup ---")

        test_cases = ["κριτήρια", "αποφάσεις", "ΠΟΣΟΤΗΤΑ"]

        for text in test_cases:
            try:
                analyze_request = {"analyzer": "greek_text_analyzer", "text": text}

                response = requests.post(
                    f"{opensearch_url}/diavgeia-documents/_analyze",
                    json=analyze_request,
                    timeout=10,
                )

                if response.status_code == 200:
                    result = response.json()
                    tokens = [token["token"] for token in result.get("tokens", [])]
                    self.stdout.write(f"  '{text}' → {tokens}")
                else:
                    self.stdout.write(
                        f"  Analysis failed for '{text}': {response.status_code}"
                    )
                    self.stdout.write(f"  Response: {response.text}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Test error: {e}"))
