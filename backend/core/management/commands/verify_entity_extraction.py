from core.models.companies import Company
from core.models.decisions import Decision
from core.models.entities import AFMEntity, DecisionEntityRelationship
from django.core.management.base import BaseCommand
from django.db.models import Q


class Command(BaseCommand):
    help = "Verify entity extraction and company data fetching status"

    def handle(self, *args, **options):
        # 1. Count decisions with extra field values
        decisions_with_efv = (
            Decision.objects.filter(extra_field_values_json__isnull=False)
            .exclude(extra_field_values_json={})
            .count()
        )

        # 2. Count decisions with extracted entities
        decisions_with_entities = (
            DecisionEntityRelationship.objects.values("decision").distinct().count()
        )

        # 3. Count AFM entities
        total_entities = AFMEntity.objects.count()
        entities_with_company_data = AFMEntity.objects.filter(
            afm__in=Company.objects.values_list("afm", flat=True)
        ).count()

        # 4. Count companies
        total_companies = Company.objects.count()

        # 5. Find entities needing attention
        entities_needing_lookup = (
            AFMEntity.objects.filter(
                Q(gemi_lookup_attempted__isnull=True) | Q(gemi_lookup_success=False)
            )
            .exclude(decision_relationships__role="organization")
            .count()
        )

        self.stdout.write(
            f"""
Entity Extraction Status Report:
================================
Decisions with extra fields: {decisions_with_efv:,}
Decisions with extracted entities: {decisions_with_entities:,}
Unprocessed decisions: {decisions_with_efv - decisions_with_entities:,}

AFM Entities:
- Total: {total_entities:,}
- With company data: {entities_with_company_data:,}
- Needing GEMI lookup: {entities_needing_lookup:,}

Companies in database: {total_companies:,}
        """
        )

        # Show sample of unprocessed decisions
        if decisions_with_efv > decisions_with_entities:
            unprocessed = Decision.objects.filter(
                extra_field_values_json__isnull=False
            ).exclude(
                ada__in=DecisionEntityRelationship.objects.values_list(
                    "decision__ada", flat=True
                )
            )[
                :5
            ]

            self.stdout.write("\nSample unprocessed decisions:")
            for decision in unprocessed:
                self.stdout.write(f"  - {decision.ada}: {decision.subject[:50]}...")
