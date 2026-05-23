import os
import time

import requests
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Wait for Loki to be available"

    def handle(self, *args, **options):
        # Print environment variables being used
        self.stdout.write(self.style.WARNING("Loki connection info:"))
        loki_host = os.environ.get("LOKI_HOST", "loki")
        loki_port = os.environ.get("LOKI_PORT", "3100")

        self.stdout.write(f"LOKI_HOST: {loki_host} (default: loki)")
        self.stdout.write(f"LOKI_PORT: {loki_port} (default: 3100)")

        loki_url = f"http://{loki_host}:{loki_port}"
        ready_url = f"{loki_url}/ready"

        self.stdout.write(f"Checking Loki ready endpoint: {ready_url}")
        self.stdout.write("Waiting for Loki...")

        loki_up = False
        retry_count = 0
        max_retries = 30

        while not loki_up and retry_count < max_retries:
            try:
                # Try to hit Loki's ready endpoint
                response = requests.get(ready_url, timeout=5)
                if response.status_code == 200:
                    loki_up = True
                else:
                    raise requests.RequestException(
                        f"Loki returned status {response.status_code}"
                    )

            except requests.RequestException as e:
                retry_count += 1
                self.stdout.write(
                    f"Loki connection error ({retry_count}/{max_retries}): {str(e)}"
                )
                wait_time = 5
                self.stdout.write(f"Loki unavailable, waiting {wait_time} seconds...")
                time.sleep(wait_time)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Unexpected error: {str(e)}"))
                break

        if loki_up:
            self.stdout.write(self.style.SUCCESS("Loki available!"))
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed to connect to Loki after {max_retries} attempts"
                )
            )
