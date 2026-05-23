"""
Manage PostgreSQL full-text search triggers and indexes.

This command provides tools for enabling/disabling PostgreSQL full-text search
to save database space (~9GB total: 9GB index + search_vector data in TOAST).

Model Selection:
    # Operate on extraction model only
    python manage.py manage_postgres_search --extraction-only --status

    # Operate on other 6 models (excluding extraction)
    python manage.py manage_postgres_search --others-only --status

    # Operate on all 7 models (default behavior)
    python manage.py manage_postgres_search --status

Usage Examples:
    # Check current status (all models by default)
    python manage.py manage_postgres_search --status

    # Disable trigger for extraction only
    python manage.py manage_postgres_search --extraction-only --disable-trigger

    # Enable trigger for other 6 models
    python manage.py manage_postgres_search --others-only --enable-trigger

    # Drop GIN index for all models (saves ~9GB)
    python manage.py manage_postgres_search --drop-index

    # Create GIN index for extraction model
    python manage.py manage_postgres_search --extraction-only --create-index

    # Complete disable workflow for other 6 models (trigger + index)
    python manage.py manage_postgres_search --others-only --disable-all

    # Complete enable workflow for all models (index + trigger)
    python manage.py manage_postgres_search --enable-all
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from loguru import logger


class Command(BaseCommand):
    help = "Manage PostgreSQL full-text search triggers and indexes"

    # Table and trigger definitions
    MODELS = {
        "extraction": {
            "table": "core_documentextraction",
            "trigger": "document_extraction_search_vector_update",
            "function": "document_extraction_search_vector_update",
            "index": "core_docume_search__d7ddb0_gin",
            "field": "search_vector",
        },
        "afmentity": {
            "table": "core_afmentity",
            "trigger": "afmentity_search_vector_update",
            "function": "afmentity_search_vector_update",
            "index": "core_afmentity_search_vector_idx",
            "field": "search_vector",
        },
        "organization": {
            "table": "core_organization",
            "trigger": "organization_search_vector_update",
            "function": "organization_search_vector_update",
            "index": "core_organization_search_vector_idx",
            "field": "search_vector",
        },
        "unit": {
            "table": "core_unit",
            "trigger": "unit_search_vector_update",
            "function": "unit_search_vector_update",
            "index": "core_unit_search_vector_idx",
            "field": "search_vector",
        },
        "signer": {
            "table": "core_signer",
            "trigger": "signer_search_vector_update",
            "function": "signer_search_vector_update",
            "index": "core_signer_search_vector_idx",
            "field": "search_vector",
        },
        "company": {
            "table": "companies",
            "trigger": "companies_search_vector_update",
            "function": "companies_search_vector_update",
            "index": "companies_search_vector_idx",
            "field": "search_vector",
        },
        "companyperson": {
            "table": "company_persons",
            "trigger": "company_person_search_vector_update",
            "function": "company_person_search_vector_update",
            "index": "company_persons_search_vector_idx",
            "field": "search_vector",
        },
    }

    def add_arguments(self, parser):
        # Model selection arguments
        parser.add_argument(
            "--extraction-only",
            action="store_true",
            help="Apply operations only to extraction model",
        )
        parser.add_argument(
            "--others-only",
            action="store_true",
            help="Apply operations only to other models (afmentity, organization, unit, signer, company, companyperson)",
        )

        # Operation arguments
        parser.add_argument(
            "--status",
            action="store_true",
            help="Show current status of triggers and indexes",
        )
        parser.add_argument(
            "--disable-trigger",
            action="store_true",
            help="Disable search_vector auto-update trigger",
        )
        parser.add_argument(
            "--enable-trigger",
            action="store_true",
            help="Enable search_vector auto-update trigger",
        )
        parser.add_argument(
            "--drop-index",
            action="store_true",
            help="Drop GIN index on search_vector (saves ~9GB)",
        )
        parser.add_argument(
            "--create-index",
            action="store_true",
            help="Create GIN index on search_vector",
        )
        parser.add_argument(
            "--disable-all",
            action="store_true",
            help="Complete disable: disable trigger + drop index",
        )
        parser.add_argument(
            "--enable-all",
            action="store_true",
            help="Complete enable: create index + enable trigger",
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
            models_to_process = ["extraction"]
            model_description = "Extraction Model"
        elif others_only:
            models_to_process = [m for m in self.MODELS.keys() if m != "extraction"]
            model_description = "Other Models (6 models)"
        else:
            models_to_process = list(self.MODELS.keys())
            model_description = "All Models (7 models)"

        # Handle compound operations
        if options["disable_all"]:
            self.stdout.write(
                self.style.WARNING(
                    f"=== Complete Disable Workflow ({model_description}) ==="
                )
            )
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.disable_trigger(model, force=options["force"])
                self.drop_index(model, force=options["force"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[OK] PostgreSQL search fully disabled for {model_description.lower()}"
                )
            )
            return

        if options["enable_all"]:
            self.stdout.write(
                self.style.WARNING(
                    f"=== Complete Enable Workflow ({model_description}) ==="
                )
            )
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.create_index(model, force=options["force"])
                self.enable_trigger(model, force=options["force"])
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[OK] PostgreSQL search fully enabled for {model_description.lower()}"
                )
            )
            self.stdout.write(
                self.style.WARNING("Run backfill_search_vectors to index existing data")
            )
            return

        # Handle individual operations
        if options["status"]:
            for model in models_to_process:
                self.show_status(model)

        if options["disable_trigger"]:
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.disable_trigger(model, force=options["force"])

        if options["enable_trigger"]:
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.enable_trigger(model, force=options["force"])

        if options["drop_index"]:
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.drop_index(model, force=options["force"])

        if options["create_index"]:
            for model in models_to_process:
                self.stdout.write(f"\n--- {model.upper()} ---")
                self.create_index(model, force=options["force"])

        # If no options specified, show status
        if not any(
            [
                options["status"],
                options["disable_trigger"],
                options["enable_trigger"],
                options["drop_index"],
                options["create_index"],
                options["disable_all"],
                options["enable_all"],
            ]
        ):
            for model in models_to_process:
                self.show_status(model)

    def show_status(self, model):
        """Show current status of triggers and indexes"""
        config = self.MODELS[model]
        self.stdout.write(self.style.WARNING(f"\n=== {model.upper()} Status ==="))

        with connection.cursor() as cursor:
            # Check trigger status
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
                WHERE tgname = %s
            """,
                [config["trigger"]],
            )

            trigger_row = cursor.fetchone()
            if trigger_row:
                trigger_status = trigger_row[1]
                if trigger_status == "enabled":
                    self.stdout.write(f"Trigger: {self.style.SUCCESS('[OK] ENABLED')}")
                else:
                    self.stdout.write(f"Trigger: {self.style.ERROR('[FAIL] DISABLED')}")
            else:
                self.stdout.write(f"Trigger: {self.style.WARNING('NOT FOUND')}")

            # Check index status
            cursor.execute(
                """
                SELECT
                    schemaname,
                    indexname,
                    pg_size_pretty(pg_relation_size(pg_class.oid)) as size
                FROM pg_indexes
                JOIN pg_class ON pg_class.relname = pg_indexes.indexname
                WHERE indexname = %s
            """,
                [config["index"]],
            )

            index_row = cursor.fetchone()
            if index_row:
                index_size = index_row[2]
                self.stdout.write(
                    f"Index: {self.style.SUCCESS('[OK] EXISTS')} ({index_size})"
                )
            else:
                self.stdout.write(f"Index: {self.style.ERROR('[FAIL] MISSING')}")

            # Check NULL count
            quoted_table = connection.ops.quote_name(config["table"])
            quoted_field = connection.ops.quote_name(config["field"])
            cursor.execute(
                f"""
                SELECT
                    COUNT(*) FILTER (WHERE {quoted_field} IS NULL) as null_count,
                    COUNT(*) FILTER (WHERE {quoted_field} IS NOT NULL) as indexed_count,
                    COUNT(*) as total_count
                FROM {quoted_table}
            """,  # nosec: B608 - Using Django's quote_name() for identifier safety
            )

            counts = cursor.fetchone()
            null_count, indexed_count, total_count = counts

            self.stdout.write(
                f"Records with search_vector: {indexed_count:,} / {total_count:,}"
            )
            if null_count > 0:
                self.stdout.write(
                    f"Records WITHOUT search_vector: {self.style.WARNING(f'{null_count:,}')}"
                )

            # Check table size
            cursor.execute(
                f"""
                SELECT
                    pg_size_pretty(pg_total_relation_size(%s)) as total_size,
                    pg_size_pretty(pg_relation_size(%s)) as table_size
            """,
                [config["table"], config["table"]],
            )

            sizes = cursor.fetchone()
            self.stdout.write(f"Table size (total): {sizes[0]}")
            self.stdout.write(f"Table size (main): {sizes[1]}")

    def disable_trigger(self, model, force=False):
        """Disable the auto-update trigger"""
        config = self.MODELS[model]

        if not force:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDisabling trigger for {model} will stop auto-indexing new/updated documents."
                )
            )
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted")
                return

        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                    ALTER TABLE {config['table']}
                    DISABLE TRIGGER {config['trigger']}
                """
                )
                self.stdout.write(
                    self.style.SUCCESS(f'[OK] Disabled trigger: {config["trigger"]}')
                )
                logger.info(f"Disabled PostgreSQL search trigger for {model}")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] Error disabling trigger: {e}")
                )
                logger.error(f"Failed to disable trigger for {model}: {e}")

    def enable_trigger(self, model, force=False):
        """Enable the auto-update trigger"""
        config = self.MODELS[model]

        with connection.cursor() as cursor:
            try:
                cursor.execute(
                    f"""
                    ALTER TABLE {config['table']}
                    ENABLE TRIGGER {config['trigger']}
                """
                )
                self.stdout.write(
                    self.style.SUCCESS(f'[OK] Enabled trigger: {config["trigger"]}')
                )
                logger.info(f"Enabled PostgreSQL search trigger for {model}")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] Error enabling trigger: {e}")
                )
                logger.error(f"Failed to enable trigger for {model}: {e}")

    def drop_index(self, model, force=False):
        """Drop the GIN index"""
        config = self.MODELS[model]

        if not force:
            self.stdout.write(
                self.style.WARNING(
                    f"\nDropping index for {model} will save ~9GB but searches will be slower.\n"
                    f"Index can be recreated later with --create-index."
                )
            )
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted")
                return

        with connection.cursor() as cursor:
            try:
                self.stdout.write(f'Dropping index {config["index"]}...')
                cursor.execute(f'DROP INDEX IF EXISTS {config["index"]}')
                self.stdout.write(
                    self.style.SUCCESS(f'[OK] Dropped index: {config["index"]}')
                )
                logger.info(f"Dropped PostgreSQL search index for {model}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[FAIL] Error dropping index: {e}"))
                logger.error(f"Failed to drop index for {model}: {e}")

    def create_index(self, model, force=False):
        """Create the GIN index"""
        config = self.MODELS[model]

        if not force:
            self.stdout.write(
                self.style.WARNING(
                    f"\nCreating index for {model} will take several minutes and use ~9GB disk space.\n"
                    f"Using CONCURRENTLY to avoid table locks."
                )
            )
            confirm = input("Continue? [y/N]: ")
            if confirm.lower() != "y":
                self.stdout.write("Aborted")
                return

        with connection.cursor() as cursor:
            try:
                self.stdout.write(
                    f'Creating index {config["index"]} (this may take several minutes)...'
                )

                # Use CONCURRENTLY to avoid table locks
                # Note: Cannot use parameters with CREATE INDEX CONCURRENTLY
                cursor.execute(
                    f"""
                    CREATE INDEX CONCURRENTLY IF NOT EXISTS {config["index"]}
                    ON {config["table"]} USING GIN ({config["field"]})
                """
                )

                self.stdout.write(
                    self.style.SUCCESS(f'[OK] Created index: {config["index"]}')
                )
                logger.info(f"Created PostgreSQL search index for {model}")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"[FAIL] Error creating index: {e}"))
                logger.error(f"Failed to create index for {model}: {e}")
