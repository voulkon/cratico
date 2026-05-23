"""
Management command to sync feature flags with environment variables.

This command updates existing feature flags in the database to match
the current environment variable values.

Usage:
    python manage.py sync_feature_flags
    python manage.py sync_feature_flags --dry-run  # Show what would change
"""

from core.models.feature_flags import FeatureFlag, FeatureFlagAuditLog
from core.services.feature_flag_service import feature_flags
from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger


class Command(BaseCommand):
    help = "Sync feature flags with environment variables"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be changed without making changes",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.MIGRATE_HEADING("Syncing Feature Flags with Environment")
        )
        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        updated_count = 0
        no_change_count = 0

        try:
            with transaction.atomic():
                for flag in FeatureFlag.objects.filter(is_active=True):
                    try:
                        # Get current value from environment
                        env_value = feature_flags._get_from_environment(flag.key)

                        if env_value is None:
                            # No env var set, keep current database value
                            self.stdout.write(
                                f"  - {flag.key}: Keeping DB value "
                                f'{"[RUNNING] ON" if flag.enabled else "[PENDING] OFF"} '
                                f"(no env var)"
                            )
                            no_change_count += 1
                            continue

                        if flag.enabled == env_value:
                            # Already in sync
                            self.stdout.write(
                                f"  [OK] {flag.key}: Already synced "
                                f'{"[RUNNING] ON" if flag.enabled else "[PENDING] OFF"}'
                            )
                            no_change_count += 1
                            continue

                        # Need to update
                        old_value = flag.enabled
                        new_value = env_value

                        self.stdout.write(
                            self.style.WARNING(
                                f"  ↻ {flag.key}: "
                                f'{"[RUNNING] ON" if old_value else "[PENDING] OFF"} → '
                                f'{"[RUNNING] ON" if new_value else "[PENDING] OFF"} '
                                f"(from env)"
                            )
                        )

                        if not dry_run:
                            flag.enabled = new_value
                            flag.save()

                            # Create audit log
                            FeatureFlagAuditLog.objects.create(
                                feature_flag=flag,
                                changed_by="sync_feature_flags",
                                change_type="enabled" if new_value else "disabled",
                                old_value=old_value,
                                new_value=new_value,
                                notes="Synced with environment variable",
                            )

                        updated_count += 1

                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [FAIL] Error with {flag.key}: {str(e)}"
                            )
                        )
                        logger.error(f"Error syncing flag {flag.key}: {e}")

                if dry_run:
                    # Rollback the transaction in dry-run mode
                    raise Exception("Dry run - rolling back")

        except Exception as e:
            if not dry_run:
                self.stdout.write(self.style.ERROR(f"\nError occurred: {str(e)}"))
                return

        # Summary
        self.stdout.write("=" * 70)
        self.stdout.write(self.style.MIGRATE_HEADING("Summary:"))

        if updated_count > 0:
            self.stdout.write(self.style.SUCCESS(f"  Updated: {updated_count} flag(s)"))

        if no_change_count > 0:
            self.stdout.write(f"  No change: {no_change_count} flag(s)")

        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN completed - no changes were made")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\n[OK] Feature flags synced successfully!")
            )
