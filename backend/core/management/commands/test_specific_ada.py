import json

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.decisions import Decision
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Test a specific ADA to see what data is captured vs dropped"

    def add_arguments(self, parser):
        parser.add_argument(
            "ada",
            nargs="?",
            default="ΡΒ9Υ46906Κ-Μ3Υ",
            help="ADA to test (defaults to the one with AFM data)",
        )

    def handle(self, *args, **options):
        ada = options["ada"]

        self.stdout.write(f"[SCAN] Testing ADA: {ada}")

        # 1. Check what's currently in the database
        try:
            db_decision = Decision.objects.get(ada=ada)
            self.stdout.write("[COPY] Current database extra_field_values_json:")
            self.stdout.write(
                json.dumps(
                    db_decision.extra_field_values_json, indent=2, ensure_ascii=False
                )
            )

            # Look for AFM-related data in current DB
            current_afm_indicators = []
            if db_decision.extra_field_values_json:
                for key, value in db_decision.extra_field_values_json.items():
                    if any(
                        term in key.lower()
                        for term in ["afm", "αφμ", "sponsor", "contractor"]
                    ):
                        current_afm_indicators.append(f"{key}: {value}")
                    elif isinstance(value, (list, dict)):
                        # Check nested structures
                        value_str = json.dumps(value, ensure_ascii=False).lower()
                        if any(
                            term in value_str
                            for term in ["afm", "αφμ", "sponsor", "contractor"]
                        ):
                            current_afm_indicators.append(f"{key}: {value}")

            if current_afm_indicators:
                self.stdout.write("[TARGET] Current AFM-related data found:")
                for indicator in current_afm_indicators:
                    self.stdout.write(f"  • {indicator}")
            else:
                self.stdout.write("[ERROR] No AFM-related data in current database")

        except Decision.DoesNotExist:
            self.stdout.write(
                "[ERROR] Decision not found in database - will be imported fresh"
            )
            db_decision = None

        # 2. Fetch fresh from API and process
        self.stdout.write(f"\n[NET] Fetching fresh data from API...")
        fetcher = DiavgeiaFetcher()
        fresh_dto = fetcher.fetch_a_decision(ada)

        if not fresh_dto:
            self.stdout.write("[ERROR] Could not fetch from API")
            return

        self.stdout.write("[OK] Successfully fetched from API")

        # 3. Process with importer
        importer = DecisionImporter()
        extracted_data = importer._extract_promoted_fields(fresh_dto)

        self.stdout.write("\n[CHART] What nuclear importer extracts:")
        fresh_extra_fields = extracted_data.get("extra_field_values_json", {})
        self.stdout.write(json.dumps(fresh_extra_fields, indent=2, ensure_ascii=False))

        # 4. Compare old vs new
        if db_decision:
            old_fields = (
                set(db_decision.extra_field_values_json.keys())
                if db_decision.extra_field_values_json
                else set()
            )
            new_fields = set(fresh_extra_fields.keys())

            added_fields = new_fields - old_fields
            removed_fields = old_fields - new_fields

            if added_fields:
                self.stdout.write(f"\n🆕 NEW FIELDS that will be captured:")
                for field in sorted(added_fields):
                    self.stdout.write(f"  • {field}: {fresh_extra_fields[field]}")

            if removed_fields:
                self.stdout.write(f"\n[ERROR] FIELDS that will be lost:")
                for field in sorted(removed_fields):
                    self.stdout.write(f"  • {field}")

        # 5. Look specifically for AFM data in fresh extraction
        self.stdout.write(f"\n[TARGET] AFM ANALYSIS of fresh data:")
        afm_found = []

        for key, value in fresh_extra_fields.items():
            # Check top-level keys
            if any(
                term in key.lower()
                for term in ["afm", "αφμ", "sponsor", "contractor", "beneficiary"]
            ):
                afm_found.append(f"Top-level: {key} = {value}")

            # Check nested structures
            elif isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if any(
                        term in nested_key.lower()
                        for term in ["afm", "αφμ", "sponsor", "contractor"]
                    ):
                        afm_found.append(f"In {key}.{nested_key} = {nested_value}")
                    elif isinstance(nested_value, dict) and "afm" in nested_value:
                        afm_found.append(
                            f"In {key}.{nested_key}.afm = {nested_value['afm']}"
                        )

            # Check lists containing AFM data
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        for item_key, item_value in item.items():
                            if any(
                                term in item_key.lower()
                                for term in ["afm", "αφμ", "sponsor", "contractor"]
                            ):
                                afm_found.append(
                                    f"In {key}[{i}].{item_key} = {item_value}"
                                )
                            elif isinstance(item_value, dict) and "afm" in item_value:
                                afm_found.append(
                                    f"In {key}[{i}].{item_key}.afm = {item_value['afm']}"
                                )

        if afm_found:
            self.stdout.write("[TARGET] AFM/Entity data found:")
            for afm in afm_found:
                self.stdout.write(f"  • {afm}")
        else:
            self.stdout.write("[ERROR] No AFM/Entity data found in fresh extraction")

        # 6. Offer to update the database
        if db_decision and fresh_extra_fields != (
            db_decision.extra_field_values_json or {}
        ):
            self.stdout.write(
                f"\n[SAVE] Database differs from fresh data. Update? (y/N): ", ending=""
            )
            # For testing, auto-update
            update = input().lower().startswith("y")

            if update:
                for field, value in extracted_data.items():
                    if hasattr(db_decision, field):
                        setattr(db_decision, field, value)
                db_decision.save()
                self.stdout.write("[OK] Database updated with fresh data")
            else:
                self.stdout.write("⏭️  Database not updated")
        elif not db_decision:
            self.stdout.write(
                f"\n[SAVE] Decision not in database. Import it? (y/N): ", ending=""
            )
            import_decision = input().lower().startswith("y")

            if import_decision:
                # This would require full import logic - skip for now
                self.stdout.write("⏭️  Full import not implemented in this test command")
        else:
            self.stdout.write(f"\n[OK] Database already matches fresh API data")

        # 7. Summary
        self.stdout.write(f"\n[COPY] SUMMARY for {ada}:")
        self.stdout.write(
            f"  • Database has data: {'[OK]' if db_decision else '[ERROR]'}"
        )
        self.stdout.write(f"  • API fetch successful: [OK]")
        self.stdout.write(f"  • AFM data found: {'[OK]' if afm_found else '[ERROR]'}")
        self.stdout.write(
            f"  • Nuclear capture working: {'[OK]' if fresh_extra_fields else '[ERROR]'}"
        )

        if afm_found:
            self.stdout.write(
                f"\n[EVENT] SUCCESS! AFM data is being captured by the nuclear models!"
            )
        else:
            self.stdout.write(
                f"\n[FAIL] No AFM data found - either this decision doesn't have any, or there's still an issue"
            )
