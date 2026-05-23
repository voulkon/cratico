from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Import a single decision by ADA"

    def add_arguments(self, parser):
        parser.add_argument("ada", type=str, help="ADA to import")

    def handle(self, *args, **options):
        ada = options["ada"]

        self.stdout.write(f"[IMPORT] Importing decision: {ada}")

        fetcher = DiavgeiaFetcher()
        importer = DecisionImporter()

        # Fetch from API
        dto = fetcher.fetch_a_decision(ada)
        if not dto:
            self.stdout.write(f"[ERROR] Could not fetch {ada}")
            return

        # Import it using the existing infrastructure
        try:
            decisions = importer.import_decisions([dto])  # Pass as list
            self.stdout.write(f"[OK] Successfully imported {ada}")
            self.stdout.write(f"   Created {decisions} new decisions in database")

            # Show what was captured
            from core.models.decisions import Decision

            db_decision = Decision.objects.get(ada=ada)
            extra_fields = db_decision.extra_field_values_json or {}
            self.stdout.write(f"   Extra fields in DB: {len(extra_fields)}")

            # Show AFM data if found
            afm_data = []
            for key, value in extra_fields.items():
                if "afm" in str(value).lower() or "sponsor" in key.lower():
                    afm_data.append(f"{key}: {value}")

            if afm_data:
                self.stdout.write("[TARGET] AFM data found:")
                for data in afm_data:
                    self.stdout.write(f"   • {data}")

        except Exception as e:
            self.stdout.write(f"[ERROR] Import failed: {e}")
