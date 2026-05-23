"""
AFM Entity Scoring and Queue Management Command

Provides command-line interface for:
1. Scoring AFM entities by importance
2. Populating the priority fetch queue
3. Processing batches from the queue
4. Monitoring queue status

Usage:
    # Run full workflow: score -> populate queue -> process batch
    python manage.py manage_afm_queue --all

    # Score all entities
    python manage.py manage_afm_queue --score

    # Populate queue with top 1000 entities
    python manage.py manage_afm_queue --populate --limit 1000

    # Process a batch of 50 AFMs
    python manage.py manage_afm_queue --process --batch-size 50

    # Show queue status
    python manage.py manage_afm_queue --status

    # Clear queue (use with caution!)
    python manage.py manage_afm_queue --clear-queue

    # Retry failed AFMs
    python manage.py manage_afm_queue --retry-failed

    # Create default scoring configuration
    python manage.py manage_afm_queue --create-default-config

Cron Job Example (score and process daily):
    0 2 * * * cd /path/to/project && python manage.py manage_afm_queue --score --populate --process --batch-size 200
"""

from decimal import Decimal

from core.models.afm_scoring import AFMScoringConfig
from core.services.afm_fetch_queue_service import AFMFetchQueueService
from core.services.afm_scoring_service import AFMEntityScoringService
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Manage AFM entity scoring and fetch queue"

    def add_arguments(self, parser):
        # Action flags
        parser.add_argument(
            "--all",
            action="store_true",
            help="Run full workflow: score, populate queue, and process batch",
        )
        parser.add_argument(
            "--score",
            action="store_true",
            help="Run scoring algorithm on all AFM entities",
        )
        parser.add_argument(
            "--populate",
            action="store_true",
            help="Populate Redis queue from scored entities",
        )
        parser.add_argument(
            "--process", action="store_true", help="Process a batch from the queue"
        )
        parser.add_argument(
            "--status", action="store_true", help="Show queue status and statistics"
        )
        parser.add_argument(
            "--clear-queue",
            action="store_true",
            help="Clear all queue data (WARNING: destructive!)",
        )
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Move failed AFMs back to pending queue for retry",
        )
        parser.add_argument(
            "--create-default-config",
            action="store_true",
            help="Create default scoring configuration",
        )

        # Options
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of entities to queue (default: all eligible)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,
            help="Number of AFMs to process in batch (default: 50)",
        )
        parser.add_argument(
            "--force-refresh",
            action="store_true",
            help="Clear existing queue before populating",
        )
        parser.add_argument(
            "--exclude-fetched",
            action="store_true",
            help="Exclude entities with successful GEMI data when scoring",
        )
        parser.add_argument(
            "--config-id",
            type=int,
            help="Use specific scoring config ID (default: active config)",
        )

    def handle(self, *args, **options):
        """Main command handler."""

        # Check if any action specified
        actions = [
            options["all"],
            options["score"],
            options["populate"],
            options["process"],
            options["status"],
            options["clear_queue"],
            options["retry_failed"],
            options["create_default_config"],
        ]

        if not any(actions):
            self.stdout.write(
                self.style.ERROR("No action specified. Use --help for options.")
            )
            return

        # Create default config if requested
        if options["create_default_config"]:
            self.create_default_config()
            return

        # Show status if requested
        if options["status"]:
            self.show_status()
            return

        # Clear queue if requested
        if options["clear_queue"]:
            self.clear_queue()
            return

        # Retry failed if requested
        if options["retry_failed"]:
            self.retry_failed(options["limit"])
            return

        # Run full workflow if --all specified
        if options["all"]:
            self.stdout.write(self.style.SUCCESS("Running full AFM queue workflow..."))
            self.run_scoring(options)
            self.populate_queue(options)
            self.process_batch(options)
            self.show_status()
            return

        # Run individual steps
        if options["score"]:
            self.run_scoring(options)

        if options["populate"]:
            self.populate_queue(options)

        if options["process"]:
            self.process_batch(options)

    def create_default_config(self):
        """Create default scoring configuration."""
        self.stdout.write("Creating default AFM scoring configuration...")

        config, created = AFMScoringConfig.objects.get_or_create(
            name="Default",
            defaults={
                "is_active": True,
                "frequency_weight": 0.30,
                "amount_weight": 0.50,
                "organization_weight": 0.20,
                "min_appearances": 3,
                "min_total_amount": Decimal("5000.00"),
                "min_unique_organizations": 2,
                "retry_failed_after_days": 90,
                "never_retry_after_failures": 5,
                "enable_recency_boost": False,
            },
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Created default configuration: {config.name}")
            )
        else:
            self.stdout.write(
                self.style.WARNING(f"Configuration already exists: {config.name}")
            )

    def run_scoring(self, options):
        """Run scoring algorithm."""
        self.stdout.write(self.style.NOTICE("Step 1: Running scoring algorithm..."))

        # Get config
        if options["config_id"]:
            try:
                config = AFMScoringConfig.objects.get(id=options["config_id"])
                self.stdout.write(f"Using config: {config.name}")
            except AFMScoringConfig.DoesNotExist:
                raise CommandError(f'Config ID {options["config_id"]} not found')
        else:
            config = None  # Will use active config

        # Initialize service
        service = AFMEntityScoringService(config=config)

        # Run scoring
        try:
            stats = service.score_all_entities(
                batch_size=1000, exclude_already_fetched=options["exclude_fetched"]
            )

            self.stdout.write(self.style.SUCCESS("[OK] Scoring completed!"))
            self.stdout.write(f"  Total scored: {stats['total_scored']}")
            self.stdout.write(f"  Eligible for fetch: {stats['eligible_for_fetch']}")
            self.stdout.write(f"  Ineligible: {stats['ineligible']}")
            self.stdout.write(f"  Config used: {stats['config_used']}")

        except Exception as e:
            raise CommandError(f"Scoring failed: {str(e)}")

    def populate_queue(self, options):
        """Populate Redis queue from scores."""
        self.stdout.write(self.style.NOTICE("Step 2: Populating Redis queue..."))

        queue_service = AFMFetchQueueService()

        try:
            stats = queue_service.populate_queue_from_scores(
                limit=options["limit"],
                force_refresh=options["force_refresh"],
                auto_trigger=False,  # Management command - user controls workflow explicitly
            )

            self.stdout.write(self.style.SUCCESS("[OK] Queue populated!"))
            self.stdout.write(f"  Added: {stats['added']}")
            self.stdout.write(
                f"  Skipped (already queued): {stats['skipped_already_queued']}"
            )
            self.stdout.write(
                f"  Skipped (already processed): {stats['skipped_already_processed']}"
            )
            self.stdout.write(f"  Total pending: {stats['total_pending']}")

        except Exception as e:
            raise CommandError(f"Queue population failed: {str(e)}")

    def process_batch(self, options):
        """Process a batch from the queue."""
        batch_size = options["batch_size"]
        self.stdout.write(
            self.style.NOTICE(f"Step 3: Processing batch of {batch_size} AFMs...")
        )

        queue_service = AFMFetchQueueService()

        try:
            stats = queue_service.process_batch(batch_size=batch_size)

            if stats.get("status") == "locked":
                self.stdout.write(self.style.WARNING(f'[WARN] {stats["message"]}'))
                return

            if stats.get("status") == "empty_queue":
                self.stdout.write(self.style.WARNING("Queue is empty"))
                return

            self.stdout.write(self.style.SUCCESS("[OK] Batch processing completed!"))
            self.stdout.write(f"  Processed: {stats['processed']}")
            self.stdout.write(f"  Successful: {stats['successful']}")
            self.stdout.write(f"  Failed: {stats['failed']}")
            self.stdout.write(f"  Not found: {stats['not_found']}")
            self.stdout.write(f"  Elapsed: {stats['elapsed_seconds']}s")
            self.stdout.write(f"  Rate: {stats['afms_per_second']} AFMs/sec")

            if stats.get("errors"):
                self.stdout.write(
                    self.style.WARNING(f"\n  Errors ({len(stats['errors'])}):")
                )
                for error in stats["errors"][:5]:  # Show first 5 errors
                    self.stdout.write(f"    - {error['afm']}: {error['error']}")

        except Exception as e:
            raise CommandError(f"Batch processing failed: {str(e)}")

    def show_status(self):
        """Show queue status."""
        self.stdout.write(self.style.NOTICE("\n[CHART] Queue Status:"))

        queue_service = AFMFetchQueueService()
        status = queue_service.get_queue_status()

        self.stdout.write(f"\nQueue Counts:")
        self.stdout.write(f"  Pending:     {status['pending']:>6}")
        self.stdout.write(f"  Active:      {status['active']:>6}")
        self.stdout.write(f"  Fetched:     {status['fetched']:>6}")
        self.stdout.write(f"  Failed:      {status['failed']:>6}")
        self.stdout.write(f"  Ignored:     {status['ignored']:>6}")

        total = status["total_processed"]
        success_rate = status["success_rate"]

        self.stdout.write(f"\nProgress:")
        self.stdout.write(f"  Total processed: {total}")
        self.stdout.write(f"  Success rate:    {success_rate}%")
        self.stdout.write(
            f"  Queue locked:    {'Yes' if status['is_locked'] else 'No'}"
        )

        if status["top_pending"]:
            self.stdout.write(f"\nTop 5 Pending (by priority):")
            for item in status["top_pending"][:5]:
                self.stdout.write(f"  #{item['priority_rank']}: {item['afm']}")

        if status["recent_stats"]:
            self.stdout.write(f"\nRecent Activity:")
            for key, value in status["recent_stats"].items():
                self.stdout.write(f"  {key}: {value}")

    def clear_queue(self):
        """Clear all queue data."""
        self.stdout.write(
            self.style.WARNING("[WARN]️  WARNING: This will clear all queue data!")
        )
        confirm = input('Type "yes" to confirm: ')

        if confirm.lower() != "yes":
            self.stdout.write("Aborted.")
            return

        queue_service = AFMFetchQueueService()
        queue_service.clear_queue(keep_stats=False)

        self.stdout.write(self.style.SUCCESS("[OK] Queue cleared!"))

    def retry_failed(self, limit):
        """Retry failed AFMs."""
        self.stdout.write(self.style.NOTICE("Retrying failed AFMs..."))

        queue_service = AFMFetchQueueService()
        stats = queue_service.retry_failed(limit=limit)

        self.stdout.write(self.style.SUCCESS(f"[OK] Retried {stats['retried']} AFMs"))
