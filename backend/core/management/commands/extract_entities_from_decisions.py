from core.models.decisions import Decision
from core.models.entities import DecisionEntityRelationship
from core.services.entity_extraction_service import EntityExtractionService
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Extract AFM entities from existing decisions (retroactive processing)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Number of decisions to process in each batch",
        )
        parser.add_argument(
            "--start-ada",
            type=str,
            help="Start processing from this ADA (for resuming)",
        )
        parser.add_argument(
            "--limit", type=int, help="Maximum number of decisions to process"
        )
        parser.add_argument(
            "--fetch-companies",
            action="store_true",
            help="Also fetch company data for extracted entities",
        )

    def handle(self, *args, **options):
        service = EntityExtractionService()

        # Track progress for resume capability
        last_processed_ada = None

        # Build queryset
        queryset = (
            Decision.objects.filter(extra_field_values_json__isnull=False)
            .exclude(extra_field_values_json={})
            .order_by("ada")
        )

        # Check if we should resume from a previous run
        if not options["start_ada"]:
            # Find the last processed decision by checking which decisions have relationships
            last_relationship = DecisionEntityRelationship.objects.order_by(
                "-decision__ada"
            ).first()
            if last_relationship:
                resume_ada = last_relationship.decision.ada
                self.stdout.write(
                    self.style.WARNING(
                        f"Found previous progress. Resume from ADA: {resume_ada}? (use --start-ada to override)"
                    )
                )
                queryset = queryset.filter(ada__gt=resume_ada)
        else:
            queryset = queryset.filter(ada__gte=options["start_ada"])

        if options["limit"]:
            queryset = queryset[: options["limit"]]

        total_decisions = queryset.count()
        self.stdout.write(f"Processing {total_decisions} decisions...")

        batch_size = options["batch_size"]
        processed = 0
        total_entities_extracted = 0

        while processed < total_decisions:
            batch = list(queryset[processed : processed + batch_size])

            if not batch:
                break

            batch_entities = 0

            with transaction.atomic():
                for decision in batch:
                    try:
                        entities = service.extract_afm_entities_from_decision(
                            decision, save_relationships=True
                        )
                        batch_entities += len(entities)

                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(f"Error processing {decision.ada}: {e}")
                        )

            processed += len(batch)
            total_entities_extracted += batch_entities

            last_processed_ada = batch[-1].ada  # Track the last ADA processed

            self.stdout.write(
                f"Processed {processed}/{total_decisions} decisions. "
                f"Extracted {batch_entities} entities in this batch. "
                f"Total entities: {total_entities_extracted}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed! Processed {processed} decisions, "
                f"extracted {total_entities_extracted} total entities."
            )
        )

        # Optionally fetch company data
        if options["fetch_companies"]:
            self.stdout.write("Fetching company data for extracted entities...")

            entities_needing_data = service.get_entities_needing_company_data(limit=100)

            if entities_needing_data:
                stats = service.fetch_company_data_for_entities(entities_needing_data)
                self.stdout.write(
                    self.style.SUCCESS(f"Company data fetch stats: {stats}")
                )
            else:
                self.stdout.write("No entities need company data fetching.")

        # Save progress periodically
        if processed % 100 == 0:  # Every 100 decisions
            self.stdout.write(
                f"Progress checkpoint: Last ADA processed: {last_processed_ada}"
            )
