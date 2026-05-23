from datetime import datetime

from core.services.seed_service import SeedService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Load initial data from Diavgeia API and external sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--organizations",
            action="store_true",
            help="Load organizations and their details",
        )
        parser.add_argument(
            "--dictionaries", action="store_true", help="Load dictionaries"
        )
        parser.add_argument(
            "--dictionary-items", action="store_true", help="Load dictionary items"
        )
        parser.add_argument(
            "--types", action="store_true", help="Load act types and extra fields"
        )
        parser.add_argument(
            "--geodata", action="store_true", help="Load organization geodata"
        )
        parser.add_argument(
            "--decisions", action="store_true", help="Load a sample set of decisions"
        )
        parser.add_argument(
            "--decision-start",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="Start date for decisions (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--decision-end",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="End date for decisions (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--decision-limit",
            type=int,
            default=1000,
            help="Maximum number of decisions to import",
        )
        parser.add_argument(
            "--all", action="store_true", help="Load all available data types"
        )
        parser.add_argument(
            "--force", action="store_true", help="Force update of existing data"
        )
        parser.add_argument(
            "--lite",
            type=int,
            help="Light-weight mode - limit number of entities per type",
        )
        parser.add_argument(
            "--force-all-details",
            action="store_true",
            help="Force seed details (units, positions, signers) for ALL existing organizations",
        )
        parser.add_argument(
            "--dictionary-items-batch-size",
            type=int,
            default=100,
            help="Batch size for dictionary items import (default: 100)",
        )
        parser.add_argument(
            "--organizations-batch-size",
            type=int,
            default=50,
            help="Batch size for organizations import (default: 50)",
        )

    def handle(self, *args, **options):
        service = SeedService(
            number_of_ents_in_lite_mode=options["lite"] if options.get("lite") else None
        )

        if options["all"]:
            result = service.seed_all(
                force=options["force"],
                include_decisions=options["decisions"],
                decision_start_date=options["decision_start"],
                decision_end_date=options["decision_end"],
                decision_limit=options["decision_limit"],
            )
            self.report_results(result["results"])
        else:
            results = {}

            if options["organizations"]:
                org_result = service.seed_organizations(
                    force=options["force"],
                    batch_size=options["organizations_batch_size"],
                )
                self.report_single_result("organizations", org_result)
                results["organizations"] = org_result

            if options["dictionaries"]:
                dict_result = service.seed_dictionaries(force=options["force"])
                self.report_single_result("dictionaries", dict_result)
                results["dictionaries"] = dict_result

            if options["dictionary_items"]:
                items_result = service.seed_dictionary_items(
                    force=options["force"],
                    batch_size=options["dictionary_items_batch_size"],
                )
                self.report_single_result("dictionary items", items_result)
                results["dictionary_items"] = items_result

            if options["types"]:
                types_result = service.seed_types(force=options["force"])
                self.report_single_result("act types", types_result)
                results["types"] = types_result

            if options["geodata"]:
                geodata_result = service.seed_organization_geodata(
                    force=options["force"]
                )
                self.report_single_result("organization geodata", geodata_result)
                results["geodata"] = geodata_result

            if options["decisions"]:
                # Make sure types are seeded first if not explicitly seeded
                if not options["types"] and not options["all"]:
                    types_result = service.seed_types(force=options["force"])
                    self.report_single_result(
                        "act types (pre-req for decisions)", types_result
                    )

                decisions_result = service._seed_sample_decisions(
                    force=options["force"],
                    start_date=options["decision_start"],
                    end_date=options["decision_end"],
                    limit=options["decision_limit"],
                )
                self.report_single_result("decisions", decisions_result)
                results["decisions"] = decisions_result

            if options["force_all_details"]:
                details_result = service.force_seed_all_details()
                self.report_single_result("organization details (all)", details_result)
                results["force_all_details"] = details_result

            # If no specific option was chosen, explain usage
            if not results:
                self.print_help("manage.py", "seed_data")

    def report_single_result(self, entity_type, result):
        if result.get("seeded", False):
            count = result.get("count", 0)
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Successfully seeded {count} {entity_type}")
            )
            if "message" in result:
                self.stdout.write(f"  {result['message']}")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"[WARN] Skipped seeding {entity_type}: {result.get('message', 'Already exists')}"
                )
            )

    def report_results(self, results):
        self.stdout.write(self.style.SUCCESS("===== Seeding Results ====="))

        for entity_type, result in results.items():
            self.report_single_result(entity_type, result)
