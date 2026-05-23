"""
Management command to refresh stale health check records.
Use this after fixing underlying data issues (like DateCoverage backfill).
"""

from datetime import timedelta

from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.services.decision_health_service import DecisionHealthService
from django.core.management.base import BaseCommand
from django.utils import timezone
from loguru import logger


class Command(BaseCommand):
    help = "Refresh stale health check records to reflect current data state"

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help="Refresh ALL health checks regardless of age",
        )
        parser.add_argument(
            "--component",
            type=str,
            help="Only refresh checks with issues in this component (e.g., coverage, opensearch)",
        )
        parser.add_argument(
            "--status",
            type=str,
            choices=["WARNING", "ERROR", "UNKNOWN"],
            help="Only refresh checks with this status",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit number of checks to refresh (for testing)",
        )
        parser.add_argument(
            "--older-than-hours",
            type=int,
            default=24,
            help="Only refresh checks older than this many hours (default: 24)",
        )

    def handle(self, *args, **options):
        self.stdout.write("=== Refreshing Health Checks ===\n")

        # Build queryset
        queryset = DecisionHealthCheck.objects.select_related("decision")

        if options["all"]:
            self.stdout.write("Refreshing ALL health checks...")
        else:
            # Filter by age
            cutoff_time = timezone.now() - timedelta(hours=options["older_than_hours"])
            queryset = queryset.filter(last_checked_at__lt=cutoff_time)
            self.stdout.write(
                f'Refreshing checks older than {options["older_than_hours"]} hours...'
            )

        # Filter by component status
        if options["component"]:
            component = options["component"]
            filter_field = f"{component}_status__in"
            queryset = queryset.filter(
                **{
                    filter_field: [
                        HealthStatus.WARNING,
                        HealthStatus.ERROR,
                        HealthStatus.UNKNOWN,
                    ]
                }
            )
            self.stdout.write(f"Filtering by component: {component}")

        # Filter by overall status
        if options["status"]:
            queryset = queryset.filter(overall_status=options["status"])
            self.stdout.write(f'Filtering by status: {options["status"]}')

        # Apply limit
        if options["limit"]:
            queryset = queryset[: options["limit"]]
            self.stdout.write(f'Limiting to first {options["limit"]} checks')

        total_checks = queryset.count()
        self.stdout.write(f"\nFound {total_checks} checks to refresh\n")

        if total_checks == 0:
            self.stdout.write(self.style.SUCCESS("No checks need refreshing!"))
            return

        # Confirm for large batches
        if total_checks > 100 and not options["limit"]:
            confirm = input(
                f"About to refresh {total_checks} checks. Continue? [y/N]: "
            )
            if confirm.lower() != "y":
                self.stdout.write("Aborted.")
                return

        # Refresh checks
        service = DecisionHealthService()
        refreshed = 0
        errors = 0

        # Track status changes
        status_changes = {
            "now_healthy": 0,
            "now_warning": 0,
            "now_error": 0,
        }

        for health_check in queryset:
            try:
                old_status = health_check.overall_status
                fresh_check = service.check_decision_health(
                    health_check.decision, force_refresh=True
                )
                refreshed += 1

                # Track status changes
                if fresh_check.overall_status == HealthStatus.HEALTHY:
                    status_changes["now_healthy"] += 1
                elif fresh_check.overall_status == HealthStatus.WARNING:
                    status_changes["now_warning"] += 1
                elif fresh_check.overall_status == HealthStatus.ERROR:
                    status_changes["now_error"] += 1

                # Log if status changed
                if old_status != fresh_check.overall_status:
                    self.stdout.write(
                        f"  {health_check.decision.ada}: {old_status} → {fresh_check.overall_status}"
                    )

                # Progress indicator
                if refreshed % 50 == 0:
                    self.stdout.write(f"Refreshed {refreshed}/{total_checks}...")

            except Exception as e:
                errors += 1
                logger.error(f"Error refreshing {health_check.decision.ada}: {e}")
                self.stdout.write(
                    self.style.ERROR(
                        f"  Error refreshing {health_check.decision.ada}: {str(e)}"
                    )
                )

        # Summary
        self.stdout.write("\n=== Summary ===")
        self.stdout.write(self.style.SUCCESS(f"[OK] Refreshed: {refreshed}"))
        if errors > 0:
            self.stdout.write(self.style.ERROR(f"[ERROR] Errors: {errors}"))

        self.stdout.write("\nStatus after refresh:")
        self.stdout.write(f'  [OK] Healthy: {status_changes["now_healthy"]}')
        self.stdout.write(f'  [WARN]️  Warning: {status_changes["now_warning"]}')
        self.stdout.write(f'  [ERROR] Error: {status_changes["now_error"]}')

        self.stdout.write(self.style.SUCCESS("\nDone!"))
