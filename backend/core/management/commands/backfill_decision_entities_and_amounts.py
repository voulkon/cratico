from core.models.decisions import Decision
from core.models.entities import DecisionAmountField, DecisionEntityRelationship
from core.services.entity_amount_extraction_service import EntityAmountExtractionService
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_date
from loguru import logger


class Command(BaseCommand):
    help = """
    Backfill AFM entities and amounts for decisions.

    [TARGET] Common Usage Examples:

    # 1. Test with specific ADA first (recommended)
    python manage.py backfill_decision_entities_and_amounts --ada 9ΥΘΧΩ9Γ-1Μ6 --dry-run

    # 2. Backfill decisions from specific dates
    python manage.py backfill_decision_entities_and_amounts --start-date 2025-06-30 --end-date 2025-07-01

    # 3. Full integrity check with optimizations (for large datasets)
    python manage.py backfill_decision_entities_and_amounts --check-integrity --quiet --batch-size 1000

    # 4. Dry run to analyze what needs fixing
    python manage.py backfill_decision_entities_and_amounts --check-integrity --dry-run

    # 5. Backfill only AFM entities (skip amounts)
    python manage.py backfill_decision_entities_and_amounts --entities-only --start-date 2025-06-30

    # 6. Backfill only amounts (skip entities)
    python manage.py backfill_decision_entities_and_amounts --amounts-only --start-date 2025-06-30

    # 7. Fix linkages only (fastest - no re-extraction)
    python manage.py backfill_decision_entities_and_amounts --relink-only --check-integrity

    # 8. Fix linkages for specific ADA
    python manage.py backfill_decision_entities_and_amounts --ada ΡΔΕ546ΝΚΟΤ-ΧΩΛ --relink-only

    # 9. Force re-extraction to fix linkages
    python manage.py backfill_decision_entities_and_amounts --ada ΡΔΕ546ΝΚΟΤ-ΧΩΛ --force

    # 10. Test with dry-run first, then apply
    python manage.py backfill_decision_entities_and_amounts --ada ΡΔΕ546ΝΚΟΤ-ΧΩΛ --dry-run
    python manage.py backfill_decision_entities_and_amounts --ada ΡΔΕ546ΝΚΟΤ-ΧΩΛ

    # 11. For long-running operations (use nohup in Docker)
    nohup python manage.py backfill_decision_entities_and_amounts --check-integrity --quiet --batch-size 1000 > /tmp/backfill.log 2>&1 & echo $!

    # 12. Monitor the background process
    tail -f /tmp/backfill.log                          # Watch logs in real-time
    tail -n 50 /tmp/backfill.log                       # Check last 50 lines
    grep "Progress:" /tmp/backfill.log | tail -n 5     # Check recent progress
    grep -i "error|exception" /tmp/backfill.log        # Check for errors
    ps aux | grep <PID>                                # Check if process is running

    # 13. Stop the background process (if needed)
    kill <PID>

    [CRIT] Performance Tips:
    - Use --quiet for large datasets to reduce log noise
    - Use --batch-size 500-1000 for optimal performance
    - Use --relink-only for fastest linkage fixes (no extraction)
    - Use nohup for operations that might take hours (screen/tmux not available in Docker)
    - Always test with --dry-run first
    - Start with specific dates before full --check-integrity
    - Monitor progress with: tail -f /tmp/backfill.log
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
            help="Check all decisions for missing entities/amounts and backfill",
        )
        parser.add_argument(
            "--entities-only",
            action="store_true",
            help="Only backfill AFM entities, skip amounts",
        )
        parser.add_argument(
            "--amounts-only",
            action="store_true",
            help="Only backfill amounts, skip AFM entities",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Batch size for processing decisions (default: 100)",
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
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-extraction even if entities/amounts exist (useful for fixing linkages)",
        )
        parser.add_argument(
            "--relink-only",
            action="store_true",
            help="Only fix linkages between existing entities and amounts (fastest, no extraction)",
        )

    def handle(self, *args, **options):
        # Set logging level based on quiet flag
        if options["quiet"]:
            import logging

            logging.getLogger("core.importers.decisions").setLevel(logging.INFO)
            logging.getLogger("core.services.afm_extractor").setLevel(logging.INFO)

        self.dry_run = options["dry_run"]
        self.batch_size = options["batch_size"]
        self.entities_only = options["entities_only"]
        self.amounts_only = options["amounts_only"]
        self.force = options["force"]
        self.relink_only = options["relink_only"]

        # Initialize the extraction service
        self.extraction_service = EntityAmountExtractionService()

        # Get the queryset of decisions to process
        decisions_qs = self.get_decisions_queryset(options)

        total_decisions = decisions_qs.count()
        self.stdout.write(
            self.style.SUCCESS(
                f"[CHART] Found {total_decisions:,} decisions to process"
            )
        )

        if self.dry_run:
            self.stdout.write(
                self.style.WARNING("[SCAN] DRY RUN MODE - No changes will be made")
            )
            self.analyze_decisions(decisions_qs)
            return

        # Process decisions in batches
        self.process_decisions(decisions_qs, total_decisions)

        self.stdout.write(self.style.SUCCESS("[OK] Backfill complete!"))

    def _relink_amounts(self, decision: Decision) -> int:
        """
        Fast path: re-link existing amounts to existing entities without re-extraction.

        Returns:
            Number of new links created
        """
        # Get all existing entities and amounts for this decision
        entities = list(decision.entity_relationships.all())
        amounts = decision.amount_fields.filter(associated_relationship__isnull=True)

        if not entities or not amounts.exists():
            return 0

        links_created = 0

        for amount in amounts:
            # Try to find matching relationship
            matching_rel = self.extraction_service._find_matching_relationship(
                amount.parent_key_path, entities
            )

            if matching_rel:
                amount.associated_relationship = matching_rel
                if not self.dry_run:
                    amount.save(update_fields=["associated_relationship"])
                links_created += 1

        return links_created

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

        # Filter by integrity check
        if options["check_integrity"]:
            if not self.entities_only and not self.amounts_only:
                # Check for decisions missing either entities OR amounts
                decisions_qs = decisions_qs.filter(
                    Q(entity_relationships__isnull=True) | Q(amount_fields__isnull=True)
                ).distinct()
            elif self.entities_only:
                # Only check for missing entities
                decisions_qs = decisions_qs.filter(entity_relationships__isnull=True)
            elif self.amounts_only:
                # Only check for missing amounts
                decisions_qs = decisions_qs.filter(amount_fields__isnull=True)

        return decisions_qs.order_by("id")

    def analyze_decisions(self, decisions_qs):
        """Analyze decisions to show what would be processed in dry-run mode."""
        total = decisions_qs.count()
        missing_entities = 0
        missing_amounts = 0
        missing_both = 0

        self.stdout.write("[SCAN] Analyzing decisions...")

        for decision in decisions_qs.iterator(chunk_size=self.batch_size):
            has_entities = DecisionEntityRelationship.objects.filter(
                decision=decision
            ).exists()
            has_amounts = DecisionAmountField.objects.filter(decision=decision).exists()

            if not has_entities and not has_amounts:
                missing_both += 1
            elif not has_entities:
                missing_entities += 1
            elif not has_amounts:
                missing_amounts += 1

        self.stdout.write(f"[METRIC] Analysis Results:")
        self.stdout.write(f"   Total decisions: {total:,}")
        self.stdout.write(f"   Missing entities only: {missing_entities:,}")
        self.stdout.write(f"   Missing amounts only: {missing_amounts:,}")
        self.stdout.write(f"   Missing both: {missing_both:,}")
        self.stdout.write(
            f"   Would process: {missing_entities + missing_amounts + missing_both:,}"
        )

    def process_decisions(self, decisions_qs, total_decisions):
        """Process decisions in batches."""
        processed = 0
        entities_created = 0
        amounts_created = 0
        links_created = 0
        errors = 0

        for i in range(0, total_decisions, self.batch_size):
            batch = list(decisions_qs[i : i + self.batch_size])

            with transaction.atomic():
                for decision in batch:
                    try:
                        if self.relink_only:
                            # Fast path: only re-link existing entities and amounts
                            decision_links = self._relink_amounts(decision)
                            links_created += decision_links
                            processed += 1

                            if decision_links > 0:
                                self.stdout.write(
                                    f"[LINK] {decision.ada}: linked {decision_links} amounts"
                                )
                        else:
                            # Determine skip behavior based on flags
                            # If entities-only: skip if has entities
                            # If amounts-only: skip if has amounts
                            # If both: skip if has both entities AND amounts
                            should_skip = False
                            if (
                                self.entities_only
                                and decision.entity_relationships.exists()
                            ):
                                should_skip = True
                            elif self.amounts_only and decision.amount_fields.exists():
                                should_skip = True
                            elif not self.entities_only and not self.amounts_only:
                                # Both entities and amounts - skip only if both exist
                                if (
                                    decision.entity_relationships.exists()
                                    and decision.amount_fields.exists()
                                ):
                                    should_skip = True

                            # Use the unified service to extract both entities and amounts
                            result = self.extraction_service.extract_from_decision(
                                decision,
                                save_to_db=not self.dry_run,
                                skip_if_existing=should_skip
                                and not self.force,  # Force overrides skip
                            )

                            # Track what was created
                            decision_entities_created = (
                                result.entities_created if not self.amounts_only else 0
                            )
                            decision_amounts_created = (
                                result.amounts_created if not self.entities_only else 0
                            )

                            entities_created += decision_entities_created
                            amounts_created += decision_amounts_created
                            processed += 1

                            # Log progress for significant decisions
                            if (
                                decision_entities_created > 0
                                or decision_amounts_created > 0
                            ):
                                self.stdout.write(
                                    f"[OK] {decision.ada}: "
                                    f"+{decision_entities_created} entities, "
                                    f"+{decision_amounts_created} amounts"
                                )

                            # Log any errors from the extraction
                            if result.errors:
                                for error in result.errors:
                                    self.stdout.write(
                                        self.style.WARNING(
                                            f"[WARN]️  {decision.ada}: {error}"
                                        )
                                    )

                    except Exception as e:
                        errors += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f"[ERROR] Error processing {decision.ada}: {e}"
                            )
                        )
                        logger.exception(f"Error processing decision {decision.ada}")

            # Progress update
            if self.relink_only:
                self.stdout.write(
                    f"[CHART] Progress: {processed:,}/{total_decisions:,} "
                    f"({processed/total_decisions*100:.1f}%) - "
                    f"Links: +{links_created}, Errors: {errors}"
                )
            else:
                self.stdout.write(
                    f"[CHART] Progress: {processed:,}/{total_decisions:,} "
                    f"({processed/total_decisions*100:.1f}%) - "
                    f"Entities: +{entities_created}, Amounts: +{amounts_created}, "
                    f"Errors: {errors}"
                )

        if self.relink_only:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[EVENT] Completed! Processed {processed:,} decisions. "
                    f"Created {links_created:,} links. "
                    f"Errors: {errors}"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[EVENT] Completed! Processed {processed:,} decisions. "
                    f"Created {entities_created:,} entities and {amounts_created:,} amounts. "
                    f"Errors: {errors}"
                )
            )
