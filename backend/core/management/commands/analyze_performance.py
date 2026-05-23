"""
Management command to analyze performance monitoring data.
This helps identify bottlenecks and optimization opportunities.
"""

import json
import os

from core.utils.performance_monitoring import (
    export_performance_data,
    performance_monitor,
)
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Analyze performance monitoring data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--export",
            action="store_true",
            help="Export performance data to JSON file",
        )
        parser.add_argument(
            "--summary",
            action="store_true",
            help="Show performance summary",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear all performance data",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="performance_data.json",
            help="Output file for export (default: performance_data.json)",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            performance_monitor.metrics.clear()
            self.stdout.write(
                self.style.SUCCESS("Performance monitoring data cleared.")
            )
            return

        if options["summary"]:
            self.stdout.write(self.style.SUCCESS("Performance Monitoring Summary:"))
            self.stdout.write("=" * 50)

            summary = performance_monitor.get_performance_summary()
            if not summary:
                self.stdout.write("No performance data collected yet.")
                return

            # Sort by average time
            sorted_functions = sorted(
                summary.items(), key=lambda x: x[1].get("avg_time", 0), reverse=True
            )

            for func_name, metrics in sorted_functions:
                slow_pct = (
                    (metrics["slow_calls"] / metrics["total_calls"] * 100)
                    if metrics["total_calls"] > 0
                    else 0
                )

                status_color = (
                    self.style.ERROR
                    if slow_pct > 50
                    else self.style.WARNING if slow_pct > 10 else self.style.SUCCESS
                )

                self.stdout.write(f"{func_name}:")
                self.stdout.write(f"  Calls: {metrics['total_calls']}")
                self.stdout.write(f"  Avg Time: {metrics['avg_time']:.3f}s")
                self.stdout.write(f"  Max Time: {metrics['max_time']:.3f}s")
                self.stdout.write(
                    status_color(
                        f"  Slow Calls: {metrics['slow_calls']} ({slow_pct:.1f}%)"
                    )
                )
                self.stdout.write("")

        if options["export"]:
            export_data = export_performance_data()
            output_file = options["output"]

            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(output_file)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir)

            with open(output_file, "w") as f:
                f.write(export_data)

            self.stdout.write(
                self.style.SUCCESS(f"Performance data exported to {output_file}")
            )

            # Also provide some quick analysis
            data = json.loads(export_data)
            self.stdout.write("\nQuick Analysis:")
            self.stdout.write("-" * 30)

            total_functions = len(data)
            slow_functions = sum(
                1
                for func_data in data.values()
                if func_data["summary"]["slow_calls"] > 0
            )

            self.stdout.write(f"Total functions monitored: {total_functions}")
            self.stdout.write(f"Functions with slow calls: {slow_functions}")

            if slow_functions > 0:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n[WARN]️  {slow_functions} functions have slow calls. "
                        "Consider optimization."
                    )
                )

                # Show top 3 problematic functions
                problematic = sorted(
                    data.items(),
                    key=lambda x: x[1]["summary"]["slow_calls"],
                    reverse=True,
                )[:3]

                self.stdout.write("\nTop problematic functions:")
                for func_name, func_data in problematic:
                    if func_data["summary"]["slow_calls"] > 0:
                        self.stdout.write(
                            f"  {func_name}: {func_data['summary']['slow_calls']} slow calls"
                        )
            else:
                self.stdout.write(
                    self.style.SUCCESS("[OK] No slow function calls detected!")
                )
