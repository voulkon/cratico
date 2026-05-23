import os
import time

from django.core.cache import cache
from django.core.management.base import BaseCommand
from redis.exceptions import ConnectionError


class Command(BaseCommand):
    help = "Wait for Redis to be available"

    def handle(self, *args, **options):
        # Print environment variables being used
        self.stdout.write(self.style.WARNING("Redis connection info:"))
        self.stdout.write(
            f"REDIS_HOST: {os.environ.get('REDIS_HOST', 'redis')} (default: redis)"
        )
        self.stdout.write(
            f"REDIS_PORT: {os.environ.get('REDIS_PORT', '6379')} (default: 6379)"
        )
        self.stdout.write(f"REDIS_DB: {os.environ.get('REDIS_DB', '1')} (default: 1)")

        self.stdout.write("Waiting for Redis...")
        redis_up = False
        retry_count = 0
        max_retries = 30

        while not redis_up and retry_count < max_retries:
            try:
                # Try to ping the Redis server
                cache.set("redis_test", "test_value", 1)
                test_value = cache.get("redis_test")
                if test_value == "test_value":
                    redis_up = True
                else:
                    raise ConnectionError("Cache test failed")
            except ConnectionError as e:
                retry_count += 1
                self.stdout.write(
                    f"Redis connection error ({retry_count}/{max_retries}): {str(e)}"
                )
                self.stdout.write("Redis unavailable, waiting 1 second...")
                time.sleep(1)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Unexpected error: {str(e)}"))
                break

        if redis_up:
            self.stdout.write(self.style.SUCCESS("Redis available!"))
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed to connect to Redis after {max_retries} attempts"
                )
            )
