import json
import time

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.decisions import Decision
from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger


class Command(BaseCommand):
    help = "Re-import decisions to capture previously missed AFM/entity data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of decisions to process in each batch",
        )
        parser.add_argument(
            "--max-decisions",
            type=int,
            default=1000,
            help="Maximum number of decisions to process (for testing)",
        )
        parser.add_argument(
            "--delay-seconds",
            type=float,
            default=0.1,
            help="Delay between API requests to be nice to the server",
        )
        parser.add_argument(
            "--start-from-ada",
            type=str,
            help="Start processing from this specific ADA (for resuming)",
        )
        parser.add_argument(
            "--test-mode",
            action="store_true",
            help="Test mode: only process first 10 decisions and show detailed output",
        )

    def handle(self, *args, **options):
        self.options = options
        self.fetcher = DiavgeiaFetcher()
        self.importer = DecisionImporter()

        batch_size = options["batch_size"]
        max_decisions = options["max_decisions"]
        delay = options["delay_seconds"]
        start_from_ada = options.get("start_from_ada")
        test_mode = options["test_mode"]

        if test_mode:
            max_decisions = 10
            self.stdout.write(
                "[TEST] TEST MODE: Processing only 10 decisions with detailed output"
            )

        # Get all decisions to re-import
        queryset = Decision.objects.all().order_by("ada")

        if start_from_ada:
            queryset = queryset.filter(ada__gte=start_from_ada)
            self.stdout.write(f"[LOC] Starting from ADA: {start_from_ada}")

        total_decisions = min(queryset.count(), max_decisions)
        self.stdout.write(
            f"[RETRY] Re-importing {total_decisions:,} decisions in batches of {batch_size}"
        )

        processed = 0
        updated_count = 0
        new_fields_found = set()
        errors = []

        for i in range(0, total_decisions, batch_size):
            batch = list(queryset[i : i + batch_size])

            self.stdout.write(
                f"\n[PKG] Processing batch {i//batch_size + 1} ({len(batch)} decisions)"
            )

            for decision in batch:
                try:
                    # Store original data for comparison
                    original_extra_fields = (
                        decision.extra_field_values_json.copy()
                        if decision.extra_field_values_json
                        else {}
                    )

                    # Fetch fresh data from API
                    fresh_dto = self.fetcher.fetch_a_decision(decision.ada)

                    if not fresh_dto:
                        self.stdout.write(f"[ERROR] Could not fetch {decision.ada}")
                        errors.append(f"Failed to fetch {decision.ada}")
                        continue

                    # Extract new data
                    new_data = self.importer._extract_promoted_fields(fresh_dto)
                    new_extra_fields = new_data.get("extra_field_values_json", {})

                    # Compare and detect new fields
                    new_fields_in_this_decision = set(new_extra_fields.keys()) - set(
                        original_extra_fields.keys()
                    )
                    if new_fields_in_this_decision:
                        new_fields_found.update(new_fields_in_this_decision)
                        self.stdout.write(
                            f"[TARGET] NEW FIELDS in {decision.ada}: {new_fields_in_this_decision}"
                        )

                        if test_mode:
                            self.stdout.write(
                                "[COPY] Original extra_field_values_json:"
                            )
                            self.stdout.write(
                                json.dumps(
                                    original_extra_fields, indent=2, ensure_ascii=False
                                )
                            )
                            self.stdout.write("[COPY] New extra_field_values_json:")
                            self.stdout.write(
                                json.dumps(
                                    new_extra_fields, indent=2, ensure_ascii=False
                                )
                            )

                    # Check if data actually changed
                    if new_extra_fields != original_extra_fields:
                        # Update the decision
                        with transaction.atomic():
                            for field, value in new_data.items():
                                if hasattr(decision, field):
                                    setattr(decision, field, value)
                            decision.save()

                        updated_count += 1

                        if test_mode or new_fields_in_this_decision:
                            self.stdout.write(f"[OK] Updated {decision.ada}")

                    processed += 1

                    # Progress update
                    if processed % 50 == 0:
                        self.stdout.write(
                            f"[CHART] Progress: {processed}/{total_decisions} ({processed/total_decisions*100:.1f}%)"
                        )
                        self.stdout.write(
                            f"   Updated: {updated_count}, New fields found: {len(new_fields_found)}"
                        )

                    # Be nice to the API
                    if delay > 0:
                        time.sleep(delay)

                except Exception as e:
                    error_msg = f"Error processing {decision.ada}: {str(e)}"
                    self.stdout.write(f"[ERROR] {error_msg}")
                    errors.append(error_msg)
                    logger.error(error_msg)

        # Final summary
        self.stdout.write(f"\n[TARGET] RE-IMPORT COMPLETE!")
        self.stdout.write(f"[CHART] Total processed: {processed:,}")
        self.stdout.write(f"[CHART] Total updated: {updated_count:,}")
        self.stdout.write(f"[CHART] Errors: {len(errors)}")

        if new_fields_found:
            self.stdout.write("\nNEW FIELDS DISCOVERED:")
            for field in sorted(new_fields_found):
                self.stdout.write(f"  • {field}")

            # Count how many decisions have these new fields
            self.stdout.write(f"\n[METRIC] FIELD USAGE ANALYSIS:")
            for field in sorted(new_fields_found):
                count = Decision.objects.filter(
                    extra_field_values_json__has_key=field
                ).count()
                self.stdout.write(f"  • {field}: {count:,} decisions")
        else:
            self.stdout.write(f"\n[ERROR] No new fields discovered")

        if errors:
            self.stdout.write(f"\n[ERROR] ERRORS:")
            for error in errors[:10]:  # Show first 10 errors
                self.stdout.write(f"  • {error}")
            if len(errors) > 10:
                self.stdout.write(f"  ... and {len(errors) - 10} more errors")
