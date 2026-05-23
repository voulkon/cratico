"""
Management command to analyze decision discovery patterns.

Compares decisions found via default search vs. organization-specific searches
to identify coverage gaps and patterns.
"""

import json

from core.models.decisions import Decision
from core.models.organizations import Organization
from core.utils.discovery_tracking import DiscoverySource, analyze_discovery_overlap
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.db.models.functions import JSONLength
from loguru import logger


class Command(BaseCommand):
    help = "Analyze decision discovery patterns across different sources"

    def add_arguments(self, parser):
        parser.add_argument(
            "--mode",
            type=str,
            default="summary",
            choices=["summary", "gaps", "overlap", "by-org", "export"],
            help="Analysis mode to run",
        )
        parser.add_argument(
            "--org-uid", type=str, help="Organization UID for by-org analysis"
        )
        parser.add_argument(
            "--export-file",
            type=str,
            help="File path to export results (for export mode)",
        )
        parser.add_argument(
            "--limit", type=int, default=100, help="Limit number of results to display"
        )

    def handle(self, *args, **options):
        mode = options["mode"]

        if mode == "summary":
            self.show_summary()
        elif mode == "gaps":
            self.show_gaps(options["limit"])
        elif mode == "overlap":
            self.show_overlap(options["limit"])
        elif mode == "by-org":
            self.analyze_by_org(options.get("org_uid"), options["limit"])
        elif mode == "export":
            self.export_analysis(options["export_file"])

    def show_summary(self):
        """Show high-level summary of discovery sources"""
        self.stdout.write(self.style.SUCCESS("\n=== Decision Discovery Summary ===\n"))

        total = Decision.objects.count()
        self.stdout.write(f"Total decisions: {total:,}")

        # Decisions with tracking
        tracked = (
            Decision.objects.filter(discovery_sources__isnull=False)
            .exclude(discovery_sources=[])
            .count()
        )

        self.stdout.write(
            f"Decisions with discovery tracking: {tracked:,} ({tracked/total*100:.1f}%)"
        )

        # By first discovery source
        self.stdout.write("\n--- By First Discovery Source ---")
        source_counts = (
            Decision.objects.values("first_discovery_source")
            .annotate(count=Count("id"))
            .order_by("-count")
        )

        for item in source_counts:
            source = item["first_discovery_source"] or "Unknown"
            count = item["count"]
            pct = count / total * 100
            self.stdout.write(f"  {source}: {count:,} ({pct:.1f}%)")

        # Multiple sources
        multi_source = Decision.objects.annotate(
            source_count=JSONLength("discovery_sources")
        ).filter(source_count__gt=1)

        self.stdout.write(
            f"\nDecisions found in multiple sources: {multi_source.count():,} "
            f"({multi_source.count()/total*100:.1f}%)"
        )

        # Run detailed overlap analysis
        self.stdout.write("\n--- Detailed Overlap Analysis ---")
        overlap_stats = analyze_discovery_overlap()

        self.stdout.write(
            f"Only in default search: {overlap_stats['only_default_count']:,}"
        )
        self.stdout.write(
            f"Only in org-specific search: {overlap_stats['only_org_specific_count']:,}"
        )

    def show_gaps(self, limit):
        """Show decisions only found in one source (gaps in coverage)"""
        self.stdout.write(self.style.SUCCESS("\n=== Coverage Gaps ===\n"))

        # Decisions only in default search
        only_default = (
            Decision.objects.filter(
                first_discovery_source=DiscoverySource.DEFAULT_SEARCH
            )
            .annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count=1)[:limit]
        )

        self.stdout.write(
            self.style.WARNING(
                f"\n--- Decisions ONLY in Default Search (not in org-specific) ---"
            )
        )
        self.stdout.write(f"Total: {only_default.count():,}\n")

        for dec in only_default[:20]:  # Show first 20
            self.stdout.write(
                f"  ADA: {dec.ada} | Org: {dec.organization.label if dec.organization else 'N/A'} "
                f"| Date: {dec.issue_date.date()}"
            )

        # Decisions only in org-specific search
        only_org = (
            Decision.objects.filter(first_discovery_source=DiscoverySource.ORG_SPECIFIC)
            .annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count=1)[:limit]
        )

        self.stdout.write(
            self.style.WARNING(
                f"\n--- Decisions ONLY in Org-Specific Search (missed by default!) ---"
            )
        )
        self.stdout.write(f"Total: {only_org.count():,}\n")

        for dec in only_org[:20]:  # Show first 20
            self.stdout.write(
                f"  ADA: {dec.ada} | Org: {dec.organization.label if dec.organization else 'N/A'} "
                f"| Date: {dec.issue_date.date()}"
            )

        # Analyze patterns in org-only decisions
        if only_org.exists():
            self.stdout.write("\n--- Patterns in Org-Only Decisions ---")

            # By organization
            org_counts = (
                only_org.values("organization__label")
                .annotate(count=Count("id"))
                .order_by("-count")[:10]
            )

            self.stdout.write("Top 10 organizations with org-only decisions:")
            for item in org_counts:
                self.stdout.write(f"  {item['organization__label']}: {item['count']:,}")

    def show_overlap(self, limit):
        """Show decisions found in multiple sources"""
        self.stdout.write(self.style.SUCCESS("\n=== Source Overlap ===\n"))

        multi_source = (
            Decision.objects.annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count__gt=1)
            .select_related("organization")[:limit]
        )

        self.stdout.write(
            f"Total decisions in multiple sources: {multi_source.count():,}\n"
        )

        for dec in multi_source[:20]:
            sources = [s.get("source_type") for s in dec.discovery_sources]
            self.stdout.write(
                f"  ADA: {dec.ada} | Sources: {', '.join(sources)} | "
                f"Org: {dec.organization.label if dec.organization else 'N/A'}"
            )

    def analyze_by_org(self, org_uid, limit):
        """Analyze discovery patterns for a specific organization"""
        if not org_uid:
            self.stdout.write(
                self.style.ERROR("Error: --org-uid required for by-org mode")
            )
            return

        try:
            org = Organization.objects.get(uid=org_uid)
        except Organization.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Organization {org_uid} not found"))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\n=== Discovery Analysis for {org.label} ({org_uid}) ===\n"
            )
        )

        # All decisions for this org
        all_decisions = Decision.objects.filter(organization=org)
        total = all_decisions.count()
        self.stdout.write(f"Total decisions: {total:,}")

        # By discovery source
        default = all_decisions.filter(
            first_discovery_source=DiscoverySource.DEFAULT_SEARCH
        ).count()

        org_specific = all_decisions.filter(
            first_discovery_source=DiscoverySource.ORG_SPECIFIC
        ).count()

        untracked = all_decisions.filter(
            Q(first_discovery_source__isnull=True) | Q(discovery_sources=[])
        ).count()

        self.stdout.write(
            f"\nFirst discovered via default search: {default:,} ({default/total*100:.1f}%)"
        )
        self.stdout.write(
            f"First discovered via org-specific: {org_specific:,} ({org_specific/total*100:.1f}%)"
        )
        self.stdout.write(f"No tracking: {untracked:,} ({untracked/total*100:.1f}%)")

        # Show sample decisions only in org-specific
        only_org_specific = (
            all_decisions.filter(first_discovery_source=DiscoverySource.ORG_SPECIFIC)
            .annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count=1)[:limit]
        )

        if only_org_specific.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"\n--- Decisions ONLY found via org-specific search ---"
                )
            )
            self.stdout.write(f"Total: {only_org_specific.count():,}\n")

            for dec in only_org_specific[:10]:
                self.stdout.write(
                    f"  ADA: {dec.ada} | Date: {dec.issue_date.date()} | "
                    f"Subject: {dec.subject[:60]}..."
                )

    def export_analysis(self, export_file):
        """Export detailed analysis to JSON file"""
        if not export_file:
            self.stdout.write(
                self.style.ERROR("Error: --export-file required for export mode")
            )
            return

        self.stdout.write("Generating export...")

        # Gather all statistics
        overlap_stats = analyze_discovery_overlap()

        # Decisions only in each source
        only_default = (
            Decision.objects.filter(
                first_discovery_source=DiscoverySource.DEFAULT_SEARCH
            )
            .annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count=1)
            .values_list("ada", flat=True)
        )

        only_org = (
            Decision.objects.filter(first_discovery_source=DiscoverySource.ORG_SPECIFIC)
            .annotate(source_count=JSONLength("discovery_sources"))
            .filter(source_count=1)
            .values_list("ada", flat=True)
        )

        export_data = {
            "generated_at": logger.info("Export generated"),
            "summary": overlap_stats,
            "decisions_only_default": list(only_default),
            "decisions_only_org_specific": list(only_org),
            "counts": {
                "only_default": len(only_default),
                "only_org_specific": len(only_org),
                "total": Decision.objects.count(),
            },
        }

        with open(export_file, "w") as f:
            json.dump(export_data, f, indent=2, default=str)

        self.stdout.write(self.style.SUCCESS(f"Exported to {export_file}"))
