"""
Management command to classify decisions as direct assignments.

Usage:
    python manage.py classify_decisions                  # Classify unclassified only
    python manage.py classify_decisions --limit 1000     # Limit to 1000 decisions
    python manage.py classify_decisions --all            # Reclassify all decisions
    python manage.py classify_decisions --outdated       # Only reclassify outdated versions
"""

from core.models.decisions import Decision
from core.services.direct_assignment_detection_service import classification_service
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Classify decisions as direct assignments"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Maximum number of decisions to classify",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Reclassify all decisions (not just unclassified)",
        )
        parser.add_argument(
            "--outdated",
            action="store_true",
            help="Only reclassify decisions with outdated classifier version",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for bulk operations",
        )

    def handle(self, *args, **options):
        limit = options.get("limit")
        classify_all = options.get("all")
        classify_outdated = options.get("outdated")
        batch_size = options.get("batch_size")

        self.stdout.write("Starting decision classification...")

        # Determine which decisions to classify
        if classify_all:
            self.stdout.write("Classifying ALL decisions...")
            decisions = Decision.objects.all()
        elif classify_outdated:
            self.stdout.write(
                "Classifying decisions with outdated classifier version..."
            )
            decisions = classification_service.get_outdated_classifications()
        else:
            self.stdout.write("Classifying unclassified decisions only...")
            decisions = classification_service.get_unclassified_decisions()

        # Apply limit if specified
        if limit:
            decisions = decisions[:limit]
            self.stdout.write(f"Limited to {limit} decisions")

        # Count before processing
        total = decisions.count()

        if total == 0:
            self.stdout.write(
                self.style.SUCCESS("No decisions to classify. All up to date!")
            )
            return

        self.stdout.write(f"Found {total} decisions to classify...")

        # Run bulk classification
        stats = classification_service.bulk_classify(decisions, batch_size=batch_size)

        # Output results
        self.stdout.write(
            self.style.SUCCESS(
                f"\nClassification complete:\n"
                f"  Total processed: {stats['total_processed']}\n"
                f"  Direct assignments: {stats['direct_assignments']}\n"
                f"  Non-direct assignments: {stats['non_direct_assignments']}\n"
                f"  Created: {stats['created']}\n"
                f"  Updated: {stats['updated']}\n"
                f"  Errors: {stats['errors']}"
            )
        )

        if stats["errors"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"Warning: {stats['errors']} decisions failed to classify. Check logs for details."
                )
            )
