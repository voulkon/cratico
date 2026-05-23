from core.models.decisions import Decision
from core.services.entity_extraction_service import EntityExtractionService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test entity extraction with a small sample"

    def add_arguments(self, parser):
        parser.add_argument("--ada", type=str, help="Test with specific ADA")
        parser.add_argument(
            "--dry-run", action="store_true", help="Don't save to database"
        )

    def handle(self, *args, **options):
        if options["ada"]:
            decision = Decision.objects.get(ada=options["ada"])
            decisions = [decision]
        else:
            # Get a small sample
            decisions = Decision.objects.filter(extra_field_values_json__isnull=False)[
                :5
            ]

        service = EntityExtractionService()

        for decision in decisions:
            self.stdout.write(f"\nTesting decision {decision.ada}")

            # Extract entities
            entities = service.extract_afm_entities_from_decision(
                decision, save_relationships=not options["dry_run"]
            )

            self.stdout.write(f"Found {len(entities)} entities:")
            for entity in entities:
                self.stdout.write(f"  - AFM: {entity.afm}")
