"""
Management command to analyze historical decision counts by day of week.

This helps establish baseline thresholds for validating whether daily imports
are complete or need re-importing.

Usage:
    python manage.py analyze_decision_counts --start-date 2025-12-01 --end-date 2026-01-25
    python manage.py analyze_decision_counts --days 60  # Last 60 days
"""

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta

from core.models.decisions import Decision
from core.models.import_thresholds import ImportThreshold
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Analyze decision counts by day of week to establish import validation thresholds"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="Start date for analysis (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="End date for analysis (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--days",
            type=int,
            default=60,
            help="Number of days to analyze (defaults to 60). Used if start/end dates not provided.",
        )
        parser.add_argument(
            "--export-csv",
            type=str,
            help="Export results to CSV file (optional)",
        )

    def handle(self, *args, **options):
        # Determine date range
        if options.get("start_date") and options.get("end_date"):
            start_date = options["start_date"]
            end_date = options["end_date"]
        else:
            end_date = date.today()
            start_date = end_date - timedelta(days=options["days"])

        self.stdout.write(f"\n{'='*80}")
        self.stdout.write(
            f"[CHART] Decision Count Analysis: {start_date} to {end_date}"
        )
        self.stdout.write(f"{'='*80}\n")

        # Collect data by day
        day_counts = defaultdict(list)  # Key: day_of_week (0=Monday, 6=Sunday)
        daily_data = []  # For CSV export

        current_date = start_date
        while current_date <= end_date:
            # Count decisions for this day (make timezone-aware)
            day_start = timezone.make_aware(
                datetime.combine(current_date, datetime.min.time())
            )
            day_end = timezone.make_aware(
                datetime.combine(current_date, datetime.max.time())
            )

            count = Decision.objects.filter(
                issue_date__gte=day_start, issue_date__lte=day_end
            ).count()

            day_of_week = current_date.weekday()  # 0=Monday, 6=Sunday
            day_counts[day_of_week].append(count)

            daily_data.append(
                {
                    "date": current_date,
                    "day_of_week": day_of_week,
                    "day_name": current_date.strftime("%A"),
                    "count": count,
                }
            )

            # Print daily detail
            self.stdout.write(
                f"{current_date.strftime('%Y-%m-%d')} ({current_date.strftime('%A'):9s}): "
                f"{count:6,d} decisions"
            )

            current_date += timedelta(days=1)

        # Analyze statistics by day of week
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("[METRIC] Statistics by Day of Week")
        self.stdout.write(f"{'='*80}\n")

        day_names = [
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ]

        summary_stats = []
        for day_num in range(7):
            counts = day_counts[day_num]
            if not counts:
                continue

            stats = {
                "day_name": day_names[day_num],
                "samples": len(counts),
                "mean": statistics.mean(counts),
                "median": statistics.median(counts),
                "min": min(counts),
                "max": max(counts),
                "stdev": statistics.stdev(counts) if len(counts) > 1 else 0,
                "p10": self._percentile(counts, 10),
                "p25": self._percentile(counts, 25),
                "p75": self._percentile(counts, 75),
                "p90": self._percentile(counts, 90),
            }

            summary_stats.append(stats)

            self.stdout.write(f"\n{stats['day_name']} ({stats['samples']} samples):")
            self.stdout.write(f"  Mean:     {stats['mean']:10,.0f}")
            self.stdout.write(f"  Median:   {stats['median']:10,.0f}")
            self.stdout.write(f"  Min:      {stats['min']:10,d}")
            self.stdout.write(f"  Max:      {stats['max']:10,d}")
            self.stdout.write(f"  Std Dev:  {stats['stdev']:10,.0f}")
            self.stdout.write(f"  P10:      {stats['p10']:10,.0f}")
            self.stdout.write(f"  P25:      {stats['p25']:10,.0f}")
            self.stdout.write(f"  P75:      {stats['p75']:10,.0f}")
            self.stdout.write(f"  P90:      {stats['p90']:10,.0f}")

        # Suggest thresholds
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("[INFO] Current Configured Thresholds")
        self.stdout.write(f"{'='*80}\n")

        # Show current database configuration
        try:
            threshold_config = ImportThreshold.get_instance()
            self.stdout.write(
                f"Weekday threshold:  {threshold_config.weekday_threshold:10,d} (configured in admin)"
            )
            self.stdout.write(
                f"Saturday threshold: {threshold_config.saturday_threshold:10,d} (configured in admin)"
            )
            self.stdout.write(
                f"Sunday threshold:   {threshold_config.sunday_threshold:10,d} (configured in admin)"
            )
            if threshold_config.notes:
                self.stdout.write(f"\nNotes: {threshold_config.notes}")
        except Exception as e:
            self.stdout.write(
                self.style.WARNING(f"Could not load configured thresholds: {e}")
            )

        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("[CHART] Suggested Thresholds Based on Analysis")
        self.stdout.write(f"{'='*80}\n")

        # Check if data looks incomplete (lots of zeros)
        all_counts = []
        for day_num in range(7):
            all_counts.extend(day_counts[day_num])

        zero_count = sum(1 for c in all_counts if c == 0)
        zero_percentage = (zero_count / len(all_counts)) * 100 if all_counts else 0

        if zero_percentage > 30:
            self.stdout.write(
                self.style.WARNING(
                    f"[WARN]️  WARNING: {zero_percentage:.1f}% of days have 0 decisions!\n"
                    f"   This suggests most days haven't been imported properly.\n"
                    f"   The P10 thresholds below are based on INCOMPLETE data and not useful.\n"
                    f"   Use expected values from complete import days instead.\n"
                )
            )

        # Calculate conservative thresholds (P10 percentile for safety)
        weekday_counts = []
        weekend_counts = []
        saturday_counts = day_counts[5]  # Saturday
        sunday_counts = day_counts[6]  # Sunday

        for day_num in range(5):  # Monday-Friday
            weekday_counts.extend(day_counts[day_num])
        for day_num in range(5, 7):  # Saturday-Sunday
            weekend_counts.extend(day_counts[day_num])

        if weekday_counts:
            weekday_threshold = self._percentile(weekday_counts, 10)
            self.stdout.write(
                f"Weekdays (Mon-Fri): {weekday_threshold:10,.0f} decisions "
                f"(P10 percentile, conservative)"
            )
            self.stdout.write(
                f"                    Mean: {statistics.mean(weekday_counts):,.0f}, "
                f"Median: {statistics.median(weekday_counts):,.0f}"
            )

        if saturday_counts:
            saturday_threshold = self._percentile(saturday_counts, 10)
            self.stdout.write(
                f"\nSaturday:           {saturday_threshold:10,.0f} decisions "
                f"(P10 percentile)"
            )
            self.stdout.write(
                f"                    Mean: {statistics.mean(saturday_counts):,.0f}, "
                f"Median: {statistics.median(saturday_counts):,.0f}"
            )

        if sunday_counts:
            sunday_threshold = self._percentile(sunday_counts, 10)
            self.stdout.write(
                f"\nSunday:             {sunday_threshold:10,.0f} decisions "
                f"(P10 percentile)"
            )
            self.stdout.write(
                f"                    Mean: {statistics.mean(sunday_counts):,.0f}, "
                f"Median: {statistics.median(sunday_counts):,.0f}"
            )

        # Code snippet for use
        self.stdout.write(f"\n{'='*80}")
        self.stdout.write("[SYS]️  How to Update Thresholds")
        self.stdout.write(f"{'='*80}\n")

        self.stdout.write(
            """
Go to Django Admin > Import Threshold Configuration to update the values.
The validation system will automatically use the configured thresholds.

Or use Python to update programmatically:
"""
        )

        if weekday_counts and saturday_counts and sunday_counts:
            self.stdout.write(
                f"""
from core.models.import_thresholds import ImportThreshold

config = ImportThreshold.get_instance()
config.weekday_threshold = {int(weekday_threshold)}
config.saturday_threshold = {int(saturday_threshold)}
config.sunday_threshold = {int(sunday_threshold)}
config.notes = "Updated based on analysis from {{start}} to {{end}}"
config.save()
"""
            )

        # Export to CSV if requested
        if options.get("export_csv"):
            import csv

            csv_path = options["export_csv"]

            with open(csv_path, "w", newline="") as csvfile:
                fieldnames = ["date", "day_of_week", "day_name", "count"]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for row in daily_data:
                    writer.writerow(
                        {
                            "date": row["date"].isoformat(),
                            "day_of_week": row["day_of_week"],
                            "day_name": row["day_name"],
                            "count": row["count"],
                        }
                    )

            self.stdout.write(f"\n[OK] Exported to: {csv_path}")

        self.stdout.write(f"\n{'='*80}\n")

    def _percentile(self, data, percentile):
        """Calculate percentile of a list of numbers."""
        if not data:
            return 0
        sorted_data = sorted(data)
        index = (len(sorted_data) - 1) * percentile / 100
        lower = int(index)
        upper = lower + 1
        weight = index - lower

        if upper >= len(sorted_data):
            return sorted_data[-1]

        return sorted_data[lower] * (1 - weight) + sorted_data[upper] * weight
