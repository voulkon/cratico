"""
Management command for running health guarantee checks.

Usage:
    # Dry run to see what would be fixed
    python manage.py ensure_health --dry-run

    # Actually fix everything
    python manage.py ensure_health

    # Fix only specific steps
    python manage.py ensure_health --step organizations
    python manage.py ensure_health --step entities
    python manage.py ensure_health --step companies
    python manage.py ensure_health --step opensearch

    # Target specific decisions
    python manage.py ensure_health --adas ADA1 ADA2 ADA3
"""

from core.services.decision_health_guarantee_service import (
    DecisionHealthGuaranteeService,
)
from django.core.management.base import BaseCommand
from loguru import logger


class Command(BaseCommand):
    help = "Ensure data consistency across all decisions by running health guarantee checks"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Only show what would be done without making changes",
        )
        parser.add_argument(
            "--step",
            type=str,
            choices=["organizations", "entities", "companies", "opensearch", "all"],
            default="all",
            help="Run only a specific health check step",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=5,
            help="Number of parallel workers (default: 5)",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Batch size for processing (default: 100)",
        )
        parser.add_argument(
            "--adas",
            nargs="+",
            help="Specific decision ADAs to check (optional)",
        )
        parser.add_argument(
            "--show-samples",
            type=int,
            default=3,
            help="Number of sample decisions to show with their extra_field_values_json (default: 3)",
        )
        parser.add_argument(
            "--show-json",
            action="store_true",
            help="Show the extra_field_values_json content for sample decisions",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        step = options["step"]
        max_workers = options["max_workers"]
        batch_size = options["batch_size"]
        decision_adas = options.get("adas")
        show_samples = options["show_samples"]
        show_json = options["show_json"]

        service = DecisionHealthGuaranteeService()

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "[SCAN] Running in DRY RUN mode - no changes will be made"
                )
            )

        if decision_adas:
            self.stdout.write(
                self.style.WARNING(
                    f"[TARGET] Targeting {len(decision_adas)} specific decisions"
                )
            )

        if show_json:
            self.stdout.write(
                self.style.WARNING(
                    f"[FILE] Will show extra_field_values_json for up to {show_samples} sample decisions"
                )
            )

        try:
            if step == "all":
                results = service.ensure_all_decisions_health(
                    max_workers=max_workers,
                    dry_run=dry_run,
                    decision_adas=decision_adas,
                )
            elif step == "organizations":
                results = service.ensure_organization_resolution(
                    batch_size=batch_size,
                    max_workers=max_workers,
                    dry_run=dry_run,
                    decision_adas=decision_adas,
                )

                # Show detailed samples if requested
                if show_json and dry_run:
                    self._show_entity_extraction_samples(results, show_samples)
            elif step == "entities":
                results = service.ensure_entity_extraction(
                    batch_size=batch_size,
                    max_workers=max_workers,
                    dry_run=dry_run,
                    decision_adas=decision_adas,
                )

                # Show detailed samples if requested
                if show_json and dry_run:
                    self._show_entity_extraction_samples(results, show_samples)
            elif step == "companies":
                # Extract AFMs from targeted decisions if specified
                afm_list = None
                if decision_adas:
                    from core.models.entities import DecisionEntityRelationship

                    afm_list = list(
                        DecisionEntityRelationship.objects.filter(
                            decision__ada__in=decision_adas
                        )
                        .values_list("entity__afm", flat=True)
                        .distinct()
                    )

                results = service.ensure_company_enrichment(
                    batch_size=batch_size, dry_run=dry_run, afm_list=afm_list
                )
            elif step == "opensearch":
                results = service.ensure_opensearch_indexing(
                    batch_size=batch_size,
                    max_workers=max_workers,
                    dry_run=dry_run,
                    decision_adas=decision_adas,
                )

            # Print results summary
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(
                self.style.SUCCESS("[OK] Health guarantee check completed")
            )

            # Show entity extraction samples if requested
            if show_json and dry_run:
                entity_results = results.get("steps", {}).get("entity_extraction", {})
                if entity_results:
                    self._show_entity_extraction_samples(entity_results, show_samples)
            self.stdout.write("=" * 80 + "\n")

            if step == "all":
                self._print_full_summary(results)
            else:
                self._print_step_summary(results, step)

        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"[ERROR] Health guarantee check failed: {e}")
            )
            logger.exception("Health guarantee check failed")
            raise

    def _print_full_summary(self, results):
        """Print summary for full health check."""
        steps = results.get("steps", {})

        for step_name, step_results in steps.items():
            self.stdout.write(f'\n{step_name.replace("_", " ").title()}:')

            if step_results.get("status") == "skipped":
                # Show what would be processed if feature was enabled
                total_missing = step_results.get("total_missing", 0)
                total_extractions = step_results.get("total_extractions", 0)
                would_process = step_results.get("would_process_if_enabled", 0)
                would_check = step_results.get("would_check_if_enabled", 0)

                if total_missing > 0 or would_process > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipped (feature flag disabled) - "
                            f"{total_missing or would_process} items would be processed if enabled"
                        )
                    )
                elif total_extractions > 0 or would_check > 0:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Skipped (feature flag disabled) - "
                            f"{total_extractions or would_check} items would be checked if enabled"
                        )
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING("  Skipped (feature flag disabled)")
                    )
                continue

            if "total_missing" in step_results:
                total = step_results["total_missing"]
                processed = (
                    step_results.get("resolved")
                    or step_results.get("processed")
                    or step_results.get("indexed")
                    or step_results.get("queued", 0)
                )
                self.stdout.write(f"  {processed}/{total} items processed")

            if step_results.get("errors"):
                error_count = len(step_results["errors"])
                self.stdout.write(self.style.ERROR(f"  {error_count} errors"))

    def _print_step_summary(self, results, step_name):
        """Print summary for individual step."""
        if results.get("status") == "skipped":
            total_missing = results.get("total_missing", 0)
            total_extractions = results.get("total_extractions", 0)
            would_process = results.get("would_process_if_enabled", 0)
            would_check = results.get("would_check_if_enabled", 0)

            if total_missing > 0 or would_process > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"{step_name.title()} skipped (feature flag disabled)\n"
                        f"Would process: {total_missing or would_process} items if enabled"
                    )
                )
            elif total_extractions > 0 or would_check > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"{step_name.title()} skipped (feature flag disabled)\n"
                        f"Would check: {total_extractions or would_check} items if enabled"
                    )
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f"{step_name.title()} skipped (feature flag disabled)"
                    )
                )

            # Show sample if available
            if results.get("sample_entities"):
                self.stdout.write("\n  Sample entities that would be enriched:")
                for entity in results["sample_entities"][:5]:
                    self.stdout.write(
                        f'    - AFM: {entity.get("afm")}, Name: {entity.get("name")}'
                    )

            if results.get("sample_documents"):
                self.stdout.write("\n  Sample documents that would be checked:")
                for doc in results["sample_documents"][:5]:
                    self.stdout.write(
                        f'    - {doc.get("ada")} ({doc.get("text_length")} chars)'
                    )

            return

        if results.get("status") == "dry_run":
            self.stdout.write(self.style.WARNING("DRY RUN RESULTS:"))
            self.stdout.write(
                f'  Would process: {results.get("total_missing", 0)} items'
            )
            if "sample_decisions" in results:
                self.stdout.write("  Sample decisions:")
                for item in results["sample_decisions"][:5]:
                    self.stdout.write(f"    - {item}")
            return

        results.get("total_missing", 0)

    def _show_entity_extraction_samples(self, results, sample_count):
        """Show detailed samples of decisions that would be processed for entity extraction."""
        import json

        from core.models.decisions import Decision
        from core.models.entities import DecisionAmountField, DecisionEntityRelationship

        if results.get("status") not in ["dry_run", "skipped"]:
            return

        total_missing = results.get("total_missing", 0)
        if total_missing == 0:
            return

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.WARNING(f"[COPY] DETAILED SAMPLES ({sample_count} decisions)")
        )
        self.stdout.write("=" * 80 + "\n")

        # Get the actual decisions
        from django.db.models import Exists, OuterRef, Q

        decisions_without_entities = (
            Decision.objects.annotate(
                has_entities=Exists(
                    DecisionEntityRelationship.objects.filter(decision=OuterRef("pk"))
                ),
                has_amounts=Exists(
                    DecisionAmountField.objects.filter(decision=OuterRef("pk"))
                ),
            )
            .filter(Q(has_entities=False) | Q(has_amounts=False))
            .order_by("-issue_date")[:sample_count]
        )

        for i, decision in enumerate(decisions_without_entities, 1):
            self.stdout.write(f'\n{"-" * 80}')
            self.stdout.write(f"Sample {i}/{sample_count}: {decision.ada}")
            self.stdout.write(f'{"-" * 80}')
            self.stdout.write(f"Issue Date: {decision.issue_date}")
            self.stdout.write(
                f"Subject: {decision.subject[:100]}..."
                if len(decision.subject) > 100
                else f"Subject: {decision.subject}"
            )
            self.stdout.write(f"Organization: {decision.organization}")

            # Show current state
            entity_count = decision.entity_relationships.count()
            amount_count = decision.amount_fields.count()
            self.stdout.write(f"\nCurrent State:")
            self.stdout.write(f"  Entities: {entity_count}")
            self.stdout.write(f"  Amounts: {amount_count}")

            # Show extra_field_values_json
            if decision.extra_field_values_json:
                self.stdout.write(f"\nextra_field_values_json:")
                json_str = json.dumps(
                    decision.extra_field_values_json, indent=2, ensure_ascii=False
                )

                # Truncate if too long
                if len(json_str) > 1000:
                    self.stdout.write(
                        json_str[:1000]
                        + "\n  ... (truncated, total length: {} chars)".format(
                            len(json_str)
                        )
                    )
                else:
                    self.stdout.write(json_str)

                # Analyze what WOULD be extracted
                self.stdout.write(
                    f'\n{self.style.SUCCESS("Analysis (what would be extracted):")}'
                )
                self._analyze_extractable_content(decision)
            else:
                self.stdout.write(
                    self.style.WARNING("\nextra_field_values_json: (empty)")
                )

        self.stdout.write("\n" + "=" * 80 + "\n")

    def _analyze_extractable_content(self, decision):
        """Analyze what would be extracted from a decision without actually extracting."""
        from core.services.entity_amount_extraction_service import (
            EntityAmountExtractionService,
        )

        service = EntityAmountExtractionService()
        efv = decision.extra_field_values_json

        if not efv:
            self.stdout.write(
                "  No extractable content (empty extra_field_values_json)"
            )
            return

        # Dry-run extraction (don't save)
        entity_extractions = service._extract_entities(efv)
        amount_extractions = service._extract_amounts(efv, decision.ada)

        # Show what would be extracted
        if entity_extractions:
            self.stdout.write(
                f"  [OK] Would extract {len(entity_extractions)} entities:"
            )
            for extraction in entity_extractions[:5]:
                afm = extraction["afm"]
                role = extraction["role"]
                path = extraction["parent_key_path"]
                name = extraction.get("name", "Unknown")
                self.stdout.write(
                    f"    - AFM: {afm} ({name}) - Role: {role} - Path: {path}"
                )
            if len(entity_extractions) > 5:
                self.stdout.write(f"    ... and {len(entity_extractions) - 5} more")
        else:
            self.stdout.write(
                "  [FAIL] No entities would be extracted (no AFM fields found)"
            )

        if amount_extractions:
            total_amounts = sum(
                len(e["amount_info"]["amounts"]) for e in amount_extractions
            )
            self.stdout.write(
                f"  [OK] Would extract {total_amounts} amounts from {len(amount_extractions)} locations:"
            )
            for extraction in amount_extractions[:5]:
                path = extraction["parent_path"]
                amounts = extraction["amount_info"]["amounts"]
                fields = extraction["amount_info"]["fields_found"]
                for amt, field in zip(amounts[:2], fields[:2]):
                    self.stdout.write(f"    - {amt} EUR from {field} at {path}")
            if len(amount_extractions) > 5:
                self.stdout.write(
                    f"    ... and {len(amount_extractions) - 5} more locations"
                )
        else:
            self.stdout.write(
                "  [FAIL] No amounts would be extracted (no amount fields found)"
            )
