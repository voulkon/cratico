from core.models.decisions import Decision
from core.models.entities import EntityRole
from core.services.afm_extractor import extract_afms_from_decision
from core.services.gemi_service import GemiService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test GEMI integration with existing AFM extractor"

    def add_arguments(self, parser):
        parser.add_argument("--ada", type=str, help="Test with specific ADA")
        parser.add_argument(
            "--limit", type=int, default=5, help="Number of decisions to test"
        )

    def handle(self, *args, **options):
        if options["ada"]:
            decisions = [Decision.objects.get(ada=options["ada"])]
        else:
            decisions = Decision.objects.filter(extra_field_values_json__isnull=False)[
                : options["limit"]
            ]

        for decision in decisions:
            self.stdout.write(f"\n=== Testing decision {decision.ada} ===")

            # 1. Extract AFMs using your existing service
            extracted = extract_afms_from_decision(decision, save_to_db=False)

            self.stdout.write(f"Found {len(extracted)} AFM entities:")

            for entity_info in extracted:
                afm = entity_info["afm"]
                role = entity_info["role"]

                self.stdout.write(f"  - AFM: {afm}, Role: {role}")

                # Skip organization roles
                if role == EntityRole.ORGANIZATION:
                    self.stdout.write("    → Skipping (organization role)")
                    continue

                # Check afmType filtering
                raw_context = entity_info.get("raw_context", {})
                afm_type = raw_context.get("afmType")

                if afm_type and afm_type != "EL":
                    self.stdout.write(f"    → Skipping (afmType: {afm_type})")
                    continue

                # Test GEMI lookup
                self.stdout.write(f"    → Testing GEMI lookup for {afm}...")

                try:
                    companies = GemiService.fetch_companies_by_afm(
                        afm, max_requests_per_minute=2
                    )

                    if companies:
                        self.stdout.write(
                            self.style.SUCCESS(
                                f"    [OK] Found {len(companies)} companies!"
                            )
                        )
                        for company in companies[:2]:  # Show first 2
                            self.stdout.write(f"      - {company.co_name_el}")
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"    [WARN] No companies found for {afm}"
                            )
                        )

                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"    [FAIL] Error: {e}"))

        # Show rate limit status
        rate_status = GemiService.get_rate_limit_status()
        self.stdout.write(f"\nRate limit status: {rate_status}")
