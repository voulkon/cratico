from core.services.entity_extraction_service import EntityExtractionService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Fetch company data for AFM entities that need it"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of entities to process",
        )
        parser.add_argument(
            "--rate-limit", type=int, default=6, help="Maximum API requests per minute"
        )

    def handle(self, *args, **options):
        service = EntityExtractionService()

        # Get entities that need processing
        entities = service.get_entities_needing_company_data(limit=options["limit"])

        if not entities:
            self.stdout.write("No entities need company data fetching.")
            return

        self.stdout.write(f"Processing {len(entities)} entities...")

        # Fetch company data
        stats = service.fetch_company_data_for_entities(
            entities, max_requests_per_minute=options["rate_limit"]
        )

        self.stdout.write(self.style.SUCCESS(f"Completed: {stats}"))

        if stats["errors"]:
            self.stdout.write(self.style.WARNING("Errors encountered:"))
            for error in stats["errors"]:
                self.stdout.write(f"  {error}")
