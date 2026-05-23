from core.models.import_jobs import DateCoverage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Count, Min
from django.utils import timezone


class Command(BaseCommand):
    help = "Cleans up duplicate DateCoverage records by keeping the earliest created record"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be deleted without actually deleting",
        )

    def handle(self, *args, **options):
        start_time = timezone.now()
        dry_run = options.get("dry_run", False)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        self.stdout.write("Finding duplicate DateCoverage records...")

        # Find all duplicate groups
        duplicates = (
            DateCoverage.objects.values("date", "organization", "unit", "signer")
            .annotate(
                count=Count("id"),
                min_id=Min(
                    "id"
                ),  # Keep the record with the smallest ID (earliest created)
            )
            .filter(count__gt=1)
        )

        total_duplicates = duplicates.count()
        total_records_to_delete = 0

        self.stdout.write(f"Found {total_duplicates} groups of duplicate records")

        if total_duplicates == 0:
            self.stdout.write(self.style.SUCCESS("No duplicates found!"))
            return

        # Count total records to delete
        for dup_group in duplicates:
            records_in_group = DateCoverage.objects.filter(
                date=dup_group["date"],
                organization=dup_group["organization"],
                unit=dup_group["unit"],
                signer=dup_group["signer"],
            ).count()
            total_records_to_delete += records_in_group - 1  # Keep one, delete the rest

        self.stdout.write(f"Will delete {total_records_to_delete} duplicate records")

        if dry_run:
            # Show some examples
            self.stdout.write("\nExample duplicate groups:")
            for dup_group in duplicates[:5]:
                self.stdout.write(
                    f'  Date: {dup_group["date"]}, '
                    f'Org: {dup_group["organization"]}, '
                    f'Unit: {dup_group["unit"]}, '
                    f'Signer: {dup_group["signer"]}, '
                    f'Count: {dup_group["count"]}'
                )
            self.stdout.write(f"\n... and {max(0, total_duplicates - 5)} more groups")
            return

        # Actually delete duplicates
        deleted_count = 0
        with transaction.atomic():
            for dup_group in duplicates:
                # Get all records in this duplicate group
                records = DateCoverage.objects.filter(
                    date=dup_group["date"],
                    organization=dup_group["organization"],
                    unit=dup_group["unit"],
                    signer=dup_group["signer"],
                ).order_by(
                    "id"
                )  # Order by ID to keep the earliest

                # Delete all but the first record
                records_to_delete = records[1:]  # Skip the first one
                for record in records_to_delete:
                    record.delete()
                    deleted_count += 1

                if deleted_count % 100 == 0:  # Progress indicator
                    self.stdout.write(f"Deleted {deleted_count} records so far...")

        # Calculate runtime
        runtime = timezone.now() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Cleanup completed successfully! "
                f"Deleted {deleted_count} duplicate records in {runtime.total_seconds():.2f} seconds"
            )
        )
