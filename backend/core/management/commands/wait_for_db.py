import os
import time
from urllib.parse import urlparse

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection
from django.db.utils import OperationalError


class Command(BaseCommand):
    help = "Wait for database to be available"

    def handle(self, *args, **options):
        # Print environment variables being used
        self.stdout.write(self.style.WARNING("Database connection info:"))

        # Check if using DATABASE_URL or individual components
        database_url = os.environ.get("DATABASE_URL")

        if database_url:
            # Parse DATABASE_URL
            try:
                parsed = urlparse(database_url)
                db_name = parsed.path.lstrip("/")
                db_user = parsed.username
                db_host = parsed.hostname
                db_port = parsed.port

                self.stdout.write(f"Using DATABASE_URL:")
                self.stdout.write(f"  DB_NAME: {db_name}")
                self.stdout.write(f"  DB_USER: {db_user}")
                self.stdout.write(f"  DB_HOST: {db_host}")
                self.stdout.write(f"  DB_PORT: {db_port}")

                # Mask the password in the URL
                if parsed.password:
                    masked_password = (
                        parsed.password[:2] + "****" + parsed.password[-2:]
                        if len(parsed.password) > 4
                        else "****"
                    )
                    masked_url = database_url.replace(parsed.password, masked_password)
                else:
                    masked_url = database_url

                self.stdout.write(f"  DATABASE_URL (masked): {masked_url}")

            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error parsing DATABASE_URL: {e}"))
                self.stdout.write(f"DATABASE_URL: {database_url}")
        else:
            # Using individual environment variables
            self.stdout.write(f"Using individual environment variables:")
            self.stdout.write(
                f"DB_NAME: {os.environ.get('POSTGRES_DB', '(not set)')}"
                f" (default: {settings.DATABASES['default']['NAME']})"
            )
            self.stdout.write(
                f"DB_USER: {os.environ.get('POSTGRES_USER', '(not set)')} (default: {settings.DATABASES['default']['USER']})"
            )
            self.stdout.write(
                f"DB_HOST: {os.environ.get('DB_HOST', '(not set)')} (default: {settings.DATABASES['default']['HOST']})"
            )
            self.stdout.write(
                f"DB_PORT: {os.environ.get('DB_PORT', '(not set)')} (default: {settings.DATABASES['default']['PORT']})"
            )

        self.stdout.write("Waiting for database...")
        db_up = False
        retry_count = 0
        max_retries = 30

        while not db_up and retry_count < max_retries:
            try:
                connection.ensure_connection()
                db_up = True
            except OperationalError as e:
                retry_count += 1
                self.stdout.write(
                    f"Database connection error ({retry_count}/{max_retries}): {str(e)}"
                )
                self.stdout.write("Database unavailable, waiting 1 second...")
                time.sleep(1)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Unexpected error: {str(e)}"))
                break

        if db_up:
            self.stdout.write(self.style.SUCCESS("Database available!"))
        else:
            self.stdout.write(
                self.style.ERROR(
                    f"Failed to connect to database after {max_retries} attempts"
                )
            )
