"""
Regenerate search_vector data from existing raw_text.

This command backfills search_vector data for DocumentExtraction table,
allowing PostgreSQL full-text search to work on existing records.

Usage:
    # Backfill all DocumentExtraction records
    python manage.py backfill_search_vectors

    # Backfill only records without search_vector (NULL)
    python manage.py backfill_search_vectors --only-null

    # Backfill with custom batch size
    python manage.py backfill_search_vectors --batch-size=1000

    # Dry run
    python manage.py backfill_search_vectors --dry-run

Performance:
    - Processes ~1000-2000 records/second (depends on text length)
    - For 500k documents: ~5-10 minutes
    - Batched updates minimize lock time
"""

import time

from core.constants.search_service import POSTGRES_FTS_MODELS
from django.apps import apps
from django.contrib.postgres.search import SearchVector
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from loguru import logger


class Command(BaseCommand):
    help = "Regenerate search_vector data for all models with search_vector fields"

    # Use centralized model configurations
    MODELS = POSTGRES_FTS_MODELS

    @staticmethod
    def _get_model_class(model_path: str):
        """Dynamically load model class from path (e.g., 'core.models.entities.AFMEntity')"""
        app_label, model_name = model_path.rsplit(".", 1)
        return apps.get_model(app_label.split(".")[0], model_name)

    def add_arguments(self, parser):
        # Model selection arguments
        parser.add_argument(
            "--extraction-only",
            action="store_true",
            help="Backfill only extraction model",
        )
        parser.add_argument(
            "--others-only",
            action="store_true",
            help="Backfill only other models (afmentity, organization, unit, signer, company, companyperson)",
        )

        # Operation arguments
        parser.add_argument(
            "--batch-size",
            type=int,
            default=1000,
            help="Batch size for updates (default: 1000)",
        )
        parser.add_argument(
            "--only-null",
            action="store_true",
            help="Only update records where search_vector IS NULL",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be affected without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip trigger status check and confirmation",
        )

    def handle(self, *args, **options):
        """Main command handler"""
        # Determine which models to operate on
        extraction_only = options.get("extraction_only", False)
        others_only = options.get("others_only", False)

        if extraction_only and others_only:
            raise CommandError(
                "Cannot specify both --extraction-only and --others-only"
            )

        if extraction_only:
            models = ["extraction"]
            model_description = "Extraction Model"
        elif others_only:
            models = [m for m in self.MODELS.keys() if m != "extraction"]
            model_description = "Other Models (6 models)"
        else:
            models = list(self.MODELS.keys())
            model_description = "All Models (7 models)"

        # Check trigger status
        if not options["force"]:
            self._check_trigger_status()

        # Show what will be affected
        stats = self._get_stats(models, options["only_null"])
        self._show_stats(stats, options["dry_run"])

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No changes made"))
            return

        # Confirmation
        if not options["force"]:
            total_records = sum(s["to_backfill"] for s in stats.values())
            estimated_time = total_records / 1500  # Rough estimate: 1500 records/second

            self.stdout.write(
                self.style.WARNING(
                    f"\nThis will regenerate search_vector for {total_records:,} records in {model_description.lower()}.\n"
                    f"Estimated time: {estimated_time/60:.1f} minutes"
                )
            )

            confirm = input("Continue? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted")
                return

        # Perform backfill for selected models
        start_time = time.time()
        total_processed = 0

        for model in models:
            if stats[model]["to_backfill"] > 0:
                self.stdout.write(
                    self.style.WARNING(f"\n=== Backfilling {model.upper()} ===")
                )
                processed = self._backfill_model(model, options)
                total_processed += processed

        elapsed = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"\n[OK] Backfill completed in {elapsed:.1f} seconds ({elapsed/60:.1f} minutes)"
            )
        )
        self.stdout.write(f"Total records processed: {total_processed:,}")

        # Show final stats
        self.stdout.write("\n=== Final Status ===")
        final_stats = self._get_stats(models, only_null=False)
        self._show_stats(final_stats, dry_run=False)

        # Clear prerequisite check cache so admin will see updated status
        from core.services.prerequisite_check_service import prerequisite_check

        prerequisite_check.clear_cache()
        self.stdout.write(self.style.SUCCESS("\n[OK] Cleared prerequisite check cache"))

    def _check_trigger_status(self):
        """Check if triggers are enabled and inform user"""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    tgname,
                    CASE tgenabled
                        WHEN 'O' THEN 'enabled'
                        WHEN 'D' THEN 'disabled'
                        ELSE 'unknown'
                    END as status
                FROM pg_trigger
                WHERE tgname LIKE '%search_vector%'
            """
            )

            disabled_triggers = []
            for row in cursor.fetchall():
                if row[1] == "disabled":
                    disabled_triggers.append(row[0])

            if disabled_triggers:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n[WARN]️  WARNING: Triggers are disabled: {", ".join(disabled_triggers)}\n'
                        f"New/updated documents will NOT be auto-indexed.\n"
                        f"Consider enabling triggers after backfill with:\n"
                        f"  python manage.py manage_postgres_search --enable-trigger\n"
                    )
                )

    def _get_stats(self, models, only_null=False):
        """Get statistics for each model"""
        stats = {}

        with connection.cursor() as cursor:
            for model in models:
                config = self.MODELS[model]
                table = config["table"]

                # For models with multiple text fields, just check if any field has data
                # We'll use the model class to do the actual filtering
                model_class = self._get_model_class(config["model_path"])

                # Count records to backfill
                if only_null:
                    to_backfill = model_class.objects.filter(
                        search_vector__isnull=True
                    ).count()
                else:
                    to_backfill = model_class.objects.all().count()

                # Get total counts
                quoted_table = connection.ops.quote_name(table)
                cursor.execute(
                    f"""
                    SELECT
                        COUNT(*) FILTER (WHERE search_vector IS NULL) as null_count,
                        COUNT(*) FILTER (WHERE search_vector IS NOT NULL) as indexed_count,
                        COUNT(*) as total_count
                    FROM {quoted_table}
                """,  # nosec: B608 - Using Django's quote_name() for identifier safety
                )

                counts = cursor.fetchone()

                stats[model] = {
                    "table": table,
                    "to_backfill": to_backfill,
                    "null_count": counts[0],
                    "indexed_count": counts[1],
                    "total_count": counts[2],
                }

        return stats

    def _show_stats(self, stats, dry_run=False):
        """Display statistics"""
        for model, data in stats.items():
            self.stdout.write(f"\n{model.upper()}:")
            self.stdout.write(f"  Total records: {data['total_count']:,}")
            self.stdout.write(f"  With search_vector: {data['indexed_count']:,}")
            self.stdout.write(f"  Without search_vector: {data['null_count']:,}")

            if data["to_backfill"] > 0:
                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  → Would backfill {data['to_backfill']:,} records"
                        )
                    )
                else:
                    self.stdout.write(f"  → To backfill: {data['to_backfill']:,}")
            else:
                self.stdout.write(self.style.SUCCESS("  [OK] Nothing to backfill"))

    def _backfill_model(self, model, options):
        """Backfill search_vector for a specific model"""
        config = self.MODELS[model]
        model_class = self._get_model_class(config["model_path"])
        text_fields = config["text_fields"]
        search_config = config["search_config"]

        batch_size = options["batch_size"]
        only_null = options["only_null"]

        # Build queryset with explicit ordering for consistent batching
        if only_null:
            qs = model_class.objects.filter(search_vector__isnull=True).order_by("pk")
        else:
            qs = model_class.objects.all().order_by("pk")

        total = qs.count()

        if total == 0:
            self.stdout.write(self.style.SUCCESS("[OK] No records to backfill"))
            return 0

        self.stdout.write(
            f"Backfilling search_vector for {total:,} records (batch size: {batch_size:,})..."
        )

        # Process in batches
        processed = 0
        batch_num = 0
        start_time = time.time()

        while processed < total:
            batch_num += 1
            batch_start = time.time()

            # Get IDs for this batch
            batch_ids = list(
                qs.values_list("pk", flat=True)[processed : processed + batch_size]
            )

            if not batch_ids:
                break

            # Build SearchVector from multiple fields
            # Combine all text fields with space separator
            search_vector_expr = SearchVector(text_fields[0], config=search_config)
            for field in text_fields[1:]:
                search_vector_expr = search_vector_expr + SearchVector(
                    field, config=search_config
                )

            # Update search_vector for this batch using Django's SearchVector
            with transaction.atomic():
                model_class.objects.filter(pk__in=batch_ids).update(
                    search_vector=search_vector_expr
                )

            processed += len(batch_ids)
            batch_elapsed = time.time() - batch_start
            total_elapsed = time.time() - start_time
            records_per_second = processed / total_elapsed if total_elapsed > 0 else 0
            estimated_remaining = (
                (total - processed) / records_per_second
                if records_per_second > 0
                else 0
            )

            progress = (processed / total) * 100
            self.stdout.write(
                f"  Batch {batch_num}: Processed {len(batch_ids):,} records in {batch_elapsed:.1f}s "
                f"({processed:,}/{total:,} = {progress:.1f}%) "
                f"[{records_per_second:.0f} rec/s, ETA: {estimated_remaining:.0f}s]"
            )

        total_elapsed = time.time() - start_time
        avg_speed = processed / total_elapsed if total_elapsed > 0 else 0

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] Backfilled search_vector for {processed:,} records in {total_elapsed:.1f}s "
                f"(avg: {avg_speed:.0f} records/second)"
            )
        )
        logger.info(
            f"Backfilled search_vector for {processed:,} {model} records in {total_elapsed:.1f}s"
        )

        return processed
