"""
NULL out search_vector data and VACUUM to reclaim disk space.

This command removes search_vector data from DocumentExtraction table,
then runs VACUUM to reclaim the disk space (~7GB from TOAST table).

Usage:
    # NULL all search vectors for DocumentExtraction (with standard VACUUM)
    python manage.py cleanup_search_vectors

    # Use VACUUM FULL for maximum space reclamation (requires maintenance window)
    python manage.py cleanup_search_vectors --vacuum-full

    # Skip VACUUM entirely (faster, but no space reclaimed)
    python manage.py cleanup_search_vectors --no-vacuum

    # Dry run (show what would be affected)
    python manage.py cleanup_search_vectors --dry-run

    # Custom batch size for NULL updates
    python manage.py cleanup_search_vectors --batch-size=10000

Space Reclamation:
    - search_vector data: ~7GB (in TOAST table)
    - Requires VACUUM to actually reclaim space
    - VACUUM FULL: Maximum reclamation, locks table (use during maintenance)
    - VACUUM (standard): Marks space as reusable, no locks (safe for production)
"""

import time

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from loguru import logger


class Command(BaseCommand):
    help = "NULL search_vector data and VACUUM to reclaim disk space for all models"

    # Model configurations (table names)
    MODELS = {
        "extraction": "core_documentextraction",
        "afmentity": "core_afmentity",
        "organization": "core_organization",
        "unit": "core_unit",
        "signer": "core_signer",
        "company": "companies",
        "companyperson": "company_persons",
    }

    def add_arguments(self, parser):
        # Model selection arguments
        parser.add_argument(
            "--extraction-only", action="store_true", help="Clean only extraction model"
        )
        parser.add_argument(
            "--others-only",
            action="store_true",
            help="Clean only other models (afmentity, organization, unit, signer, company, companyperson)",
        )

        # Operation arguments
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be affected without making changes",
        )
        parser.add_argument(
            "--no-vacuum",
            action="store_true",
            help="Skip VACUUM (faster, but no space reclaimed)",
        )
        parser.add_argument(
            "--vacuum-full",
            action="store_true",
            help="Use VACUUM FULL (max space reclamation, locks table)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=5000,
            help="Batch size for NULL updates (default: 5000)",
        )
        parser.add_argument(
            "--force", action="store_true", help="Skip confirmation prompts"
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

        # Check trigger status and warn if enabled
        self._check_trigger_status()

        # Show what will be affected
        stats = self._get_stats(models)
        self._show_stats(stats, options["dry_run"])

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\n[DRY RUN] No changes made"))
            return

        # Confirmation
        if not options["force"]:
            if options["vacuum_full"]:
                self.stdout.write(
                    self.style.ERROR(
                        "\n[WARN]️  VACUUM FULL will lock tables and may take 10-30 minutes!"
                    )
                )

            total_records = sum(s["indexed_count"] for s in stats.values())
            self.stdout.write(
                self.style.WARNING(
                    f"\nThis will NULL search_vector for {total_records:,} records in {model_description.lower()}."
                )
            )

            confirm = input("Continue? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted")
                return

        # Perform cleanup for selected models
        start_time = time.time()

        for model in models:
            self.stdout.write(self.style.WARNING(f"\n=== Cleaning {model.upper()} ==="))
            self._cleanup_model(model, options)

        elapsed = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(f"\n[OK] Cleanup completed in {elapsed:.1f} seconds")
        )

        # Show final stats
        self.stdout.write("\n=== Final Status ===")
        final_stats = self._get_stats(models)
        self._show_stats(final_stats, dry_run=False)

    def _check_trigger_status(self):
        """Check if triggers are enabled and warn user"""
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

            enabled_triggers = []
            for row in cursor.fetchall():
                if row[1] == "enabled":
                    enabled_triggers.append(row[0])

            if enabled_triggers:
                self.stdout.write(
                    self.style.WARNING(
                        f'\n[WARN]️  WARNING: Triggers are still enabled: {", ".join(enabled_triggers)}\n'
                        f"New/updated documents will be re-indexed automatically.\n"
                        f"Consider disabling triggers first with:\n"
                        f"  python manage.py manage_postgres_search --disable-trigger\n"
                    )
                )

    def _get_stats(self, models):
        """Get statistics for each model"""
        stats = {}

        with connection.cursor() as cursor:
            for model in models:
                table = self.MODELS[model]
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

                cursor.execute(
                    f"""
                    SELECT
                        pg_size_pretty(pg_total_relation_size(%s)) as total_size,
                        pg_size_pretty(pg_relation_size(%s)) as table_size
                """,
                    [table, table],
                )

                sizes = cursor.fetchone()

                stats[model] = {
                    "table": table,
                    "null_count": counts[0],
                    "indexed_count": counts[1],
                    "total_count": counts[2],
                    "total_size": sizes[0],
                    "table_size": sizes[1],
                }

        return stats

    def _show_stats(self, stats, dry_run=False):
        """Display statistics"""
        for model, data in stats.items():
            self.stdout.write(f"\n{model.upper()}:")
            self.stdout.write(f"  Total records: {data['total_count']:,}")
            self.stdout.write(f"  With search_vector: {data['indexed_count']:,}")
            self.stdout.write(f"  Without search_vector: {data['null_count']:,}")
            self.stdout.write(f"  Total size: {data['total_size']}")
            self.stdout.write(f"  Table size: {data['table_size']}")

            if dry_run and data["indexed_count"] > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"  → Would NULL {data['indexed_count']:,} search_vector fields"
                    )
                )

    def _cleanup_model(self, model, options):
        """Clean up search_vector for a specific model"""
        table = self.MODELS[model]
        quoted_table = connection.ops.quote_name(table)
        batch_size = options["batch_size"]

        # Get count of records to update
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM {quoted_table}
                WHERE search_vector IS NOT NULL
            """,  # nosec: B608 - Using Django's quote_name() for identifier safety
            )
            total_to_update = cursor.fetchone()[0]

        if total_to_update == 0:
            self.stdout.write(
                self.style.SUCCESS("[OK] No records to clean (all already NULL)")
            )
            return

        self.stdout.write(
            f"NULLing search_vector for {total_to_update:,} records (batch size: {batch_size:,})..."
        )

        # NULL in batches to avoid long-running transactions
        updated_count = 0
        batch_num = 0

        # Determine primary key field based on table
        pk_field = (
            "uid"
            if table in ["core_organization", "core_unit", "core_signer"]
            else "id"
        )

        while updated_count < total_to_update:
            batch_num += 1
            with transaction.atomic():
                with connection.cursor() as cursor:
                    quoted_pk = connection.ops.quote_name(pk_field)
                    cursor.execute(
                        f"""
                        WITH to_update AS (
                            SELECT {quoted_pk} FROM {quoted_table}
                            WHERE search_vector IS NOT NULL
                            LIMIT %s
                        )
                        UPDATE {quoted_table}
                        SET search_vector = NULL
                        WHERE {quoted_pk} IN (SELECT {quoted_pk} FROM to_update)
                    """,
                        [
                            batch_size
                        ],  # nosec: B608 - Using Django's quote_name() for identifier safety
                    )

                    rows_updated = cursor.rowcount
                    updated_count += rows_updated

                    if rows_updated > 0:
                        progress = (updated_count / total_to_update) * 100
                        self.stdout.write(
                            f"  Batch {batch_num}: Updated {rows_updated:,} records "
                            f"({updated_count:,}/{total_to_update:,} = {progress:.1f}%)"
                        )
                    else:
                        # No more records to update
                        break

        self.stdout.write(
            self.style.SUCCESS(
                f"[OK] NULLed search_vector for {updated_count:,} records"
            )
        )
        logger.info(f"Cleaned search_vector for {updated_count:,} {model} records")

        # Run VACUUM unless --no-vacuum specified
        if not options["no_vacuum"]:
            self._vacuum_table(table, options["vacuum_full"])

    def _vacuum_table(self, table, full=False):
        """Run VACUUM on a table"""
        vacuum_type = "VACUUM FULL" if full else "VACUUM"

        if full:
            self.stdout.write(
                self.style.WARNING(f"\nRunning {vacuum_type} ANALYZE on {table}...")
            )
            self.stdout.write(
                self.style.ERROR(
                    f"[WARN]️  This will LOCK the table and may take 10-30 minutes!"
                )
            )
        else:
            self.stdout.write(f"\nRunning {vacuum_type} ANALYZE on {table}...")

        start_time = time.time()

        try:
            # VACUUM cannot run inside a transaction block
            # Close any existing transaction and use autocommit mode
            connection.close()
            connection.ensure_connection()

            # Ensure we're in autocommit mode (Django's default outside of atomic blocks)
            connection.set_autocommit(True)

            with connection.cursor() as cursor:
                if full:
                    cursor.execute(f"VACUUM FULL ANALYZE {table}")
                else:
                    cursor.execute(f"VACUUM ANALYZE {table}")

                elapsed = time.time() - start_time
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] {vacuum_type} completed in {elapsed:.1f} seconds"
                    )
                )
                logger.info(f"Completed {vacuum_type} on {table} in {elapsed:.1f}s")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"[FAIL] VACUUM failed: {e}"))
            logger.error(f"VACUUM failed on {table}: {e}")
            raise
