import logging

from core.models.decision_classification import DecisionClassification
from core.models.decisions import Decision
from core.services.direct_assignment_detection_service import classification_service
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils.dateparse import parse_date
from loguru import logger


class Command(BaseCommand):
    help = """
    Backfill direct assignment classifications for decisions.

    This command classifies decisions as direct assignments (ΑΠΕΥΘΕΙΑΣ ΑΝΑΘΕΣΕΙΣ) based on:
    - Decision type (Δ.1)
    - Amount below threshold (€37,200)
    - Text content patterns (keywords indicating direct assignment)

    Results are stored in DecisionClassification model for fast querying.

    [TARGET] Common Usage Examples:

    # 1. Test with specific ADA first (recommended)
    python manage.py backfill_direct_assignment_classification --ada 9ΥΘΧΩ9Γ-1Μ6 --dry-run

    # 2. Classify decisions from specific dates
    python manage.py backfill_direct_assignment_classification --start-date 2025-06-30 --end-date 2025-07-01

    # 3. Find and classify all unclassified decisions
    python manage.py backfill_direct_assignment_classification --check-integrity

    # 4. Re-classify all decisions (when algorithm updates)
    python manage.py backfill_direct_assignment_classification --reclassify --start-date 2025-01-01

    # 5. Dry run to analyze what needs classifying
    python manage.py backfill_direct_assignment_classification --check-integrity --dry-run

    # 6. Full integrity check with optimizations (for large datasets)
    python manage.py backfill_direct_assignment_classification --check-integrity --quiet --batch-size 1000

    # 7. Re-classify outdated versions (after algorithm update)
    python manage.py backfill_direct_assignment_classification --outdated-only

    # 8. For long-running operations (use nohup in Docker)
    nohup python manage.py backfill_direct_assignment_classification --check-integrity --quiet --batch-size 1000 > /tmp/classification.log 2>&1 & echo $!

    # 9. Monitor the background process
    tail -f /tmp/classification.log                          # Watch logs in real-time
    tail -n 50 /tmp/classification.log                       # Check last 50 lines
    grep "Progress:" /tmp/classification.log | tail -n 5     # Check recent progress
    grep -i "error\\|exception" /tmp/classification.log       # Check for errors
    ps aux | grep <PID>                                      # Check if process is running

    # 10. Stop the background process (if needed)
    kill <PID>

    [CRIT] Performance Tips:
    - Use --quiet for large datasets to reduce log noise
    - Use --batch-size 1000 for optimal performance
    - Use nohup for operations that might take hours (screen/tmux not available in Docker)
    - Always test with --dry-run first
    - Start with specific dates before full --check-integrity
    - Monitor progress with: tail -f /tmp/classification.log

    [CHART] Workflow Integration:
    - Run AFTER backfill_decision_entities_and_amounts (classification depends on amounts)
    - Run when classifier algorithm is updated (to re-classify with new logic)
    - Run periodically to catch any unclassified decisions
    """

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date (YYYY-MM-DD) for filtering decisions by issue_date",
        )
        parser.add_argument(
            "--end-date",
            type=str,
            help="End date (YYYY-MM-DD) for filtering decisions by issue_date",
        )
        parser.add_argument(
            "--check-integrity",
            action="store_true",
            help="Find and classify all unclassified decisions",
        )
        parser.add_argument(
            "--reclassify",
            action="store_true",
            help="Re-classify decisions even if already classified (useful after algorithm updates)",
        )
        parser.add_argument(
            "--outdated-only",
            action="store_true",
            help="Only re-classify decisions with outdated classifier versions",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for processing decisions (default: 1000)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be processed without making changes",
        )
        parser.add_argument(
            "--ada", type=str, help="Process only a specific ADA (useful for testing)"
        )
        parser.add_argument(
            "--quiet", action="store_true", help="Suppress debug logging"
        )

    def handle(self, *args, **options):
        # Set logging level based on quiet flag
        if options["quiet"]:
            logger.remove()
            logger.add(lambda msg: None, level="INFO")
            logging.getLogger(
                "core.services.direct_assignment_detection_service"
            ).setLevel(logging.INFO)

        self.dry_run = options["dry_run"]
        self.batch_size = options["batch_size"]
        self.reclassify = options["reclassify"]

        # Get the queryset of decisions to process
        decisions_qs = self.get_decisions_queryset(options)

        total_decisions = decisions_qs.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"[CHART] Found {total_decisions:,} decisions to classify"
            )
        )

        if self.dry_run:
            self.stdout.write(
                self.style.WARNING("[SCAN] DRY RUN MODE - No changes will be made")
            )
            self.analyze_decisions(decisions_qs)
            return

        # Process decisions using the service's bulk_classify method
        self.classify_decisions(decisions_qs)

        self.stdout.write(self.style.SUCCESS("[OK] Classification complete!"))

    def get_decisions_queryset(self, options):
        """Build the queryset based on command options."""
        decisions_qs = Decision.objects.all()

        # Filter by specific ADA if provided
        if options["ada"]:
            decisions_qs = decisions_qs.filter(ada=options["ada"])
            return decisions_qs

        # Filter by date range
        if options["start_date"]:
            start_date = parse_date(options["start_date"])
            if not start_date:
                raise CommandError(f"Invalid start date: {options['start_date']}")
            decisions_qs = decisions_qs.filter(issue_date__gte=start_date)

        if options["end_date"]:
            end_date = parse_date(options["end_date"])
            if not end_date:
                raise CommandError(f"Invalid end date: {options['end_date']}")
            decisions_qs = decisions_qs.filter(issue_date__lte=end_date)

        # Filter by classification status
        if options["check_integrity"]:
            # Find decisions without classifications
            decisions_qs = decisions_qs.filter(classification__isnull=True)
        elif options["outdated_only"]:
            # Find decisions with outdated classifier versions
            current_version = classification_service.CLASSIFIER_VERSION
            decisions_qs = decisions_qs.filter(
                ~Q(classification__classifier_version=current_version)
            )
        elif not options["reclassify"]:
            # By default, only classify unclassified decisions
            # (unless --reclassify is specified)
            decisions_qs = decisions_qs.filter(classification__isnull=True)

        return decisions_qs.order_by("id")

    def analyze_decisions(self, decisions_qs):
        """Analyze decisions to show what would be classified in dry-run mode."""
        total = decisions_qs.count()
        unclassified = 0
        already_classified = 0

        self.stdout.write("[SCAN] Analyzing decisions...")

        for decision in decisions_qs.iterator(chunk_size=self.batch_size):
            has_classification = DecisionClassification.objects.filter(
                decision=decision
            ).exists()

            if has_classification:
                already_classified += 1
            else:
                unclassified += 1

        self.stdout.write(f"[METRIC] Analysis Results:")
        self.stdout.write(f"   Total decisions: {total:,}")
        self.stdout.write(f"   Unclassified: {unclassified:,}")
        self.stdout.write(f"   Already classified: {already_classified:,}")

        if self.reclassify:
            self.stdout.write(f"   Would process (with reclassify): {total:,}")
        else:
            self.stdout.write(f"   Would process: {unclassified:,}")

    def classify_decisions(self, decisions_qs):
        """Classify decisions using the bulk_classify service method."""
        self.stdout.write("[RETRY] Starting classification...")

        # Use the service's bulk_classify method
        stats = classification_service.bulk_classify(
            decisions=decisions_qs, batch_size=self.batch_size
        )

        # Display results
        self.stdout.write(
            self.style.SUCCESS(
                f"\n[EVENT] Classification Complete!\n"
                f"   Total processed: {stats['total_processed']:,}\n"
                f"   Direct assignments found: {stats['direct_assignments']:,}\n"
                f"   Non-direct assignments: {stats['non_direct_assignments']:,}\n"
                f"   New classifications: {stats['created']:,}\n"
                f"   Updated classifications: {stats['updated']:,}\n"
                f"   Errors: {stats['errors']:,}"
            )
        )

        # Calculate percentage if we have results
        if stats["total_processed"] > 0:
            direct_pct = (stats["direct_assignments"] / stats["total_processed"]) * 100
            self.stdout.write(
                f"\n[CHART] {direct_pct:.1f}% of processed decisions are direct assignments"
            )
