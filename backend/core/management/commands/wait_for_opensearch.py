import os
import time

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Wait for OpenSearch to be available"

    def handle(self, *args, **options):
        opensearch_url = os.environ.get("OPENSEARCH_URL", "http://opensearch:9200")

        self.stdout.write(self.style.WARNING("OpenSearch connection info:"))
        self.stdout.write(f"OPENSEARCH_URL: {opensearch_url}")

        self.stdout.write("Waiting for OpenSearch...")
        opensearch_up = False
        retry_count = 0
        max_retries = 30

        while not opensearch_up and retry_count < max_retries:
            try:
                response = requests.get(f"{opensearch_url}/_cluster/health", timeout=5)
                if response.status_code == 200:
                    health_data = response.json()
                    if health_data.get("status") in ["green", "yellow"]:
                        opensearch_up = True
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"OpenSearch available! Status: {health_data.get('status')}"
                            )
                        )
                    else:
                        raise Exception(
                            f"OpenSearch status: {health_data.get('status')}"
                        )
                else:
                    raise Exception(f"HTTP {response.status_code}")

            except Exception as e:
                retry_count += 1
                self.stdout.write(
                    f"OpenSearch connection error ({retry_count}/{max_retries}): {str(e)}"
                )
                self.stdout.write("OpenSearch unavailable, waiting 2 seconds...")
                time.sleep(2)

        if not opensearch_up:
            self.stdout.write(
                self.style.WARNING(
                    f"OpenSearch not reachable after {max_retries} attempts. "
                    "Continuing anyway — OpenSearchService will degrade gracefully "
                    "to Postgres FTS (circuit breaker)."
                )
            )
            # Do NOT exit(1): the app must boot without OpenSearch. The
            # OpenSearchService circuit breaker handles the unreachable case.
            return
