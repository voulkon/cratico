from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Check if essential database tables exist and create them if needed"

    def handle(self, *args, **options):
        tables = connection.introspection.table_names()

        # Check core models
        core_models = ["core_organization", "core_decisiontype", "core_decision"]

        for table in core_models:
            if table in tables:
                self.stdout.write(self.style.SUCCESS(f"[OK] Table '{table}' exists"))
            else:
                self.stdout.write(
                    self.style.WARNING(f"[ERROR] Table '{table}' does not exist")
                )

        # Additional db setup tasks can go here
        self.stdout.write(self.style.SUCCESS("Database check completed"))
