import json

from core.models.decisions import Decision
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Find the specific AFM record from your download logs"

    def handle(self, *args, **options):
        target_afm = "997288180"
        target_org_name = "ΠΕΡΙΦΕΡΕΙΑΚΟΣ ΣΥΝΔΕΣΜΟΣ"

        self.stdout.write(f"[SCAN] Searching for AFM: {target_afm}")
        self.stdout.write(f"[SCAN] Searching for org containing: {target_org_name}")

        # Method 1: Search all decisions for the AFM number
        self.stdout.write("\n[CHART] Method 1: Scanning all extra_field_values_json...")

        count = 0
        found_decisions = []

        for decision in Decision.objects.exclude(
            extra_field_values_json__isnull=True
        ).exclude(extra_field_values_json={}):
            count += 1

            # Convert to string and search
            json_str = json.dumps(decision.extra_field_values_json, ensure_ascii=False)

            if target_afm in json_str or target_org_name in json_str:
                self.stdout.write(f"[TARGET] FOUND in decision {decision.ada}!")
                self.stdout.write("[COPY] Full content:")
                self.stdout.write(
                    json.dumps(
                        decision.extra_field_values_json, indent=2, ensure_ascii=False
                    )
                )
                self.stdout.write("-" * 80)
                found_decisions.append(decision.ada)

                if len(found_decisions) >= 3:  # Stop after finding 3
                    break

            if count % 10000 == 0:
                self.stdout.write(f"   Scanned {count:,} decisions...")

            if count > 50000:  # Limit scan to avoid timeout
                break

        if not found_decisions:
            self.stdout.write("[ERROR] Target AFM not found in extra_field_values_json")

            # Method 2: Try searching other fields
            self.stdout.write("\n[CHART] Method 2: Searching in subject field...")

            decisions_with_afm_in_subject = Decision.objects.filter(
                subject__icontains=target_afm
            ) | Decision.objects.filter(subject__icontains=target_org_name)

            for decision in decisions_with_afm_in_subject[:5]:
                self.stdout.write(
                    f"[TARGET] Found in subject of {decision.ada}: {decision.subject}"
                )

        # Method 3: Check for different JSON structure patterns
        self.stdout.write(f"\n[CHART] Method 3: Looking for common AFM patterns...")

        afm_patterns = ["afm", "αφμ", "AFM", "extraFieldValues", "org"]

        for pattern in afm_patterns:
            count = Decision.objects.filter(
                extra_field_values_json__icontains=pattern
            ).count()
            self.stdout.write(f"   '{pattern}': {count} decisions")

        self.stdout.write(
            f"\n[METRIC] Summary: Scanned {count:,} decisions, found {len(found_decisions)} matches"
        )
