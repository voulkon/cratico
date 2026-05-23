import json
from datetime import timedelta

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.services.decision_health_service import DecisionHealthService
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone


class Command(BaseCommand):
    help = "Run health checks on decisions to identify pipeline issues"

    def add_arguments(self, parser):
        parser.add_argument("--ada", type=str, help="Check a specific decision by ADA")

        parser.add_argument(
            "--days",
            type=int,
            default=7,
            help="Check decisions from the last N days (default: 7)",
        )

        parser.add_argument(
            "--organization", type=str, help="Filter by organization UID"
        )

        parser.add_argument(
            "--limit",
            type=int,
            default=100,
            help="Maximum number of decisions to check (default: 100)",
        )

        parser.add_argument(
            "--component",
            choices=[
                "ingestion",
                "relations",
                "entities",
                "document_extraction",
                "opensearch",
                "coverage",
            ],
            help="Focus on a specific component",
        )

        parser.add_argument(
            "--status",
            choices=["HEALTHY", "WARNING", "ERROR", "UNKNOWN"],
            help="Filter by health status",
        )

        parser.add_argument(
            "--force-refresh",
            action="store_true",
            help="Force refresh of existing health checks",
        )

        parser.add_argument(
            "--problems-only",
            action="store_true",
            help="Only check decisions with known problems",
        )

        parser.add_argument(
            "--export-json", type=str, help="Export results to JSON file"
        )

        parser.add_argument(
            "--verbose",
            action="store_true",
            help="Show detailed findings for each decision",
        )

    def handle(self, *args, **options):
        health_service = DecisionHealthService()

        # Single decision check
        if options["ada"]:
            return self._check_single_decision(health_service, options["ada"], options)

        # Bulk decision check
        return self._check_multiple_decisions(health_service, options)

    def _check_single_decision(self, health_service, ada, options):
        """Check health for a single decision"""
        try:
            decision = Decision.objects.get(ada=ada)
        except Decision.DoesNotExist:
            raise CommandError(f'Decision with ADA "{ada}" does not exist.')

        self.stdout.write(f"Checking health for decision {ada}...")

        health_check = health_service.check_decision_health(
            decision, force_refresh=options["force_refresh"]
        )

        self._display_single_result(health_check, options["verbose"])

        if options["export_json"]:
            self._export_single_result(health_check, options["export_json"])

    def _check_multiple_decisions(self, health_service, options):
        """Check health for multiple decisions"""
        # Build query
        queryset = self._build_decision_query(options)

        decisions = list(queryset[: options["limit"]])
        total_count = len(decisions)

        if total_count == 0:
            self.stdout.write(
                self.style.WARNING("No decisions found matching the criteria.")
            )
            return

        self.stdout.write(f"Checking health for {total_count} decisions...")

        # Progress tracking
        def progress_callback(current, total, ada):
            if current % 10 == 0 or current == total:
                self.stdout.write(f"Progress: {current}/{total} - Current: {ada}")

        # Run health checks
        results = health_service.bulk_check_decisions(decisions, progress_callback)

        # Display results
        self._display_bulk_results(results, options)

        # Export if requested
        if options["export_json"]:
            self._export_bulk_results(results, options["export_json"])

    def _build_decision_query(self, options):
        """Build Django ORM query based on options"""
        queryset = Decision.objects.select_related("organization", "decision_type")

        # Date filter
        if options["days"]:
            start_date = timezone.now() - timedelta(days=options["days"])
            queryset = queryset.filter(issue_date__gte=start_date)

        # Organization filter
        if options["organization"]:
            queryset = queryset.filter(organization__uid=options["organization"])

        # Problems only filter
        if options["problems_only"]:
            # Get decisions that have health checks with issues
            problem_decisions = DecisionHealthCheck.objects.filter(
                Q(has_errors=True) | Q(has_warnings=True)
            ).values_list("decision_id", flat=True)
            queryset = queryset.filter(id__in=problem_decisions)

        # Component-specific filter
        if options["component"] and options["status"]:
            # Filter by specific component status
            component_filter = f"{options['component']}_status"
            health_checks = DecisionHealthCheck.objects.filter(
                **{component_filter: options["status"]}
            ).values_list("decision_id", flat=True)
            queryset = queryset.filter(id__in=health_checks)

        return queryset.order_by("-issue_date")

    def _display_single_result(self, health_check, verbose=False):
        """Display results for a single decision"""
        status_colors = {
            HealthStatus.HEALTHY: self.style.SUCCESS,
            HealthStatus.WARNING: self.style.WARNING,
            HealthStatus.ERROR: self.style.ERROR,
            HealthStatus.UNKNOWN: lambda x: x,
        }

        color_func = status_colors.get(health_check.overall_status, lambda x: x)

        self.stdout.write(color_func(f"Overall Status: {health_check.overall_status}"))

        # Component status summary
        self.stdout.write("\nComponent Status:")
        for component, status in health_check.component_statuses.items():
            color_func = status_colors.get(status, lambda x: x)
            self.stdout.write(
                f"  {component.replace('_', ' ').title()}: {color_func(status)}"
            )

        # Detailed findings if verbose or if there are issues
        if verbose or health_check.overall_status != HealthStatus.HEALTHY:
            self.stdout.write("\nDetailed Findings:")
            for component, finding in health_check.findings.items():
                status = finding.get("status", "UNKNOWN")
                message = finding.get("message", "No message")
                details = finding.get("details", {})

                self.stdout.write(f"\n  {component.title()}:")
                self.stdout.write(f"    Status: {status}")
                self.stdout.write(f"    Message: {message}")

                if details and verbose:
                    self.stdout.write(f"    Details: {json.dumps(details, indent=6)}")

    def _display_bulk_results(self, results, options):
        """Display results for bulk health check"""
        summary = results["summary"]
        component_stats = results["component_stats"]

        # Summary statistics
        self.stdout.write(f"\nHealth Check Summary:")
        self.stdout.write(f"  Total Checked: {summary['total_checked']}")
        self.stdout.write(self.style.SUCCESS(f"  Healthy: {summary['healthy']}"))
        self.stdout.write(self.style.WARNING(f"  Warnings: {summary['warnings']}"))
        self.stdout.write(self.style.ERROR(f"  Errors: {summary['errors']}"))
        self.stdout.write(f"  Unknown: {summary['unknown']}")

        # Component breakdown
        self.stdout.write(f"\nComponent Breakdown:")
        for component, stats in component_stats.items():
            self.stdout.write(f"  {component.replace('_', ' ').title()}:")
            self.stdout.write(f"    Healthy: {stats['healthy']}")
            self.stdout.write(f"    Warnings: {stats['warnings']}")
            self.stdout.write(f"    Errors: {stats['errors']}")

        # Show problematic decisions
        problematic = [
            hc
            for hc in results["health_checks"]
            if hc.overall_status in [HealthStatus.ERROR, HealthStatus.WARNING]
        ]

        if problematic:
            self.stdout.write(f"\nProblematic Decisions ({len(problematic)} found):")
            for health_check in problematic[:20]:  # Show first 20
                status_symbol = (
                    "[ERROR]"
                    if health_check.overall_status == HealthStatus.ERROR
                    else "[WARN]️"
                )
                failed_components = ", ".join(health_check.failed_components)
                warning_components = ", ".join(health_check.warning_components)

                components_info = []
                if failed_components:
                    components_info.append(f"Errors: {failed_components}")
                if warning_components:
                    components_info.append(f"Warnings: {warning_components}")

                components_str = " | ".join(components_info)

                self.stdout.write(
                    f"  {status_symbol} {health_check.decision.ada} - {components_str}"
                )

            if len(problematic) > 20:
                self.stdout.write(f"  ... and {len(problematic) - 20} more")

    def _export_single_result(self, health_check, filename):
        """Export single health check result to JSON"""
        data = {
            "ada": health_check.decision.ada,
            "overall_status": health_check.overall_status,
            "component_statuses": health_check.component_statuses,
            "findings": health_check.findings,
            "last_checked": health_check.last_checked_at.isoformat(),
            "check_duration_ms": health_check.check_duration_ms,
        }

        with open(filename, "w") as f:
            json.dump(data, f, indent=2)

        self.stdout.write(f"Results exported to {filename}")

    def _export_bulk_results(self, results, filename):
        """Export bulk health check results to JSON"""
        export_data = {
            "summary": results["summary"],
            "component_stats": results["component_stats"],
            "checked_at": timezone.now().isoformat(),
            "health_checks": [
                {
                    "ada": hc.decision.ada,
                    "overall_status": hc.overall_status,
                    "component_statuses": hc.component_statuses,
                    "findings": hc.findings,
                    "last_checked": hc.last_checked_at.isoformat(),
                }
                for hc in results["health_checks"]
            ],
        }

        with open(filename, "w") as f:
            json.dump(export_data, f, indent=2)

        self.stdout.write(f"Results exported to {filename}")
