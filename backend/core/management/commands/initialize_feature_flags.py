"""
Management command to initialize feature flags in the database.

This command reads all known feature flags from the FeatureFlagService
and creates database entries for them if they don't already exist.

Usage:
    python manage.py initialize_feature_flags
    python manage.py initialize_feature_flags --force  # Re-sync all flags
"""

from core.models.feature_flags import FeatureFlag
from core.services.feature_flag_service import feature_flags
from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger


class Command(BaseCommand):
    help = "Initialize feature flags in the database from KNOWN_FLAGS configuration"

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force update existing flags with current configuration",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be created/updated without making changes",
        )

    def handle(self, *args, **options):
        force = options["force"]
        dry_run = options["dry_run"]

        self.stdout.write(self.style.MIGRATE_HEADING("Initializing Feature Flags"))
        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No changes will be made")
            )

        created_count = 0
        updated_count = 0
        skipped_count = 0

        try:
            with transaction.atomic():
                for flag_key, flag_data in feature_flags.KNOWN_FLAGS.items():
                    try:
                        # Determine value type
                        value_type = flag_data.get("value_type", "boolean")

                        # Prepare defaults based on value type
                        defaults = {
                            "name": flag_data["name"],
                            "description": flag_data["description"],
                            "default_value": (
                                flag_data.get("default", False)
                                if value_type == "boolean"
                                else False
                            ),
                            "env_var_name": flag_data.get("env_var", ""),
                            "category": flag_data.get("category", "system"),
                            "requires_restart": flag_data.get(
                                "requires_restart", False
                            ),
                            "value_type": value_type,
                        }

                        # Set value based on type
                        if value_type == "boolean":
                            # Check if environment variable is set
                            env_value = feature_flags._get_from_environment(flag_key)
                            # Use env value if set, otherwise use default
                            initial_enabled = (
                                env_value
                                if env_value is not None
                                else flag_data["default"]
                            )
                            defaults["enabled"] = initial_enabled
                        elif value_type == "list":
                            defaults["list_value"] = flag_data.get("default", [])
                        elif value_type == "string":
                            defaults["string_value"] = flag_data.get("default", "")

                        flag, created = FeatureFlag.objects.get_or_create(
                            key=flag_key, defaults=defaults
                        )

                        if created:
                            created_count += 1
                            if value_type == "boolean":
                                source = "env" if env_value is not None else "default"
                                status = (
                                    "[RUNNING] ON"
                                    if defaults["enabled"]
                                    else "[PENDING] OFF"
                                )
                                self.stdout.write(
                                    self.style.SUCCESS(f"  [OK] Created: {flag_key}")
                                    + f' = {status} (from {source}) - {flag_data["name"]}'
                                )
                            elif value_type == "list":
                                count = (
                                    len(defaults["list_value"])
                                    if defaults["list_value"]
                                    else 0
                                )
                                self.stdout.write(
                                    self.style.SUCCESS(f"  [OK] Created: {flag_key}")
                                    + f' = [COPY] {count} items - {flag_data["name"]}'
                                )
                            else:
                                self.stdout.write(
                                    self.style.SUCCESS(f"  [OK] Created: {flag_key}")
                                    + f' - {flag_data["name"]}'
                                )
                        elif force:
                            # Update existing flag with current configuration
                            flag.name = flag_data["name"]
                            flag.description = flag_data["description"]
                            flag.default_value = (
                                flag_data.get("default", False)
                                if value_type == "boolean"
                                else False
                            )
                            flag.env_var_name = flag_data.get("env_var", "")
                            flag.category = flag_data.get("category", "system")
                            flag.requires_restart = flag_data.get(
                                "requires_restart", False
                            )
                            flag.value_type = value_type

                            if not dry_run:
                                flag.save()

                            updated_count += 1
                            self.stdout.write(
                                self.style.WARNING(f"  ↻ Updated: {flag_key}")
                                + f' - {flag_data["name"]}'
                            )
                        else:
                            skipped_count += 1
                            current_status = (
                                "[RUNNING] ON" if flag.enabled else "[PENDING] OFF"
                            )
                            self.stdout.write(
                                f'  - Exists: {flag_key} = {current_status} - {flag_data["name"]}'
                            )

                    except Exception as e:
                        self.stdout.write(
                            self.style.ERROR(
                                f"  [FAIL] Error with {flag_key}: {str(e)}"
                            )
                        )
                        logger.error(f"Error initializing flag {flag_key}: {e}")

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

        if created_count > 0:
            self.stdout.write(self.style.SUCCESS(f"  Created: {created_count} flag(s)"))

        if updated_count > 0:
            self.stdout.write(self.style.WARNING(f"  Updated: {updated_count} flag(s)"))

        if skipped_count > 0:
            self.stdout.write(f"  Skipped: {skipped_count} flag(s) (already exist)")

        self.stdout.write("=" * 70)

        if dry_run:
            self.stdout.write(
                self.style.WARNING("\nDRY RUN completed - no changes were made")
            )
        else:
            total_flags = FeatureFlag.objects.count()
            self.stdout.write(
                self.style.SUCCESS(f"\n[OK] Feature flags initialized successfully!")
            )
            self.stdout.write(f"  Total flags in database: {total_flags}")

            # Show how to access them
            self.stdout.write("\n" + self.style.MIGRATE_LABEL("Next steps:"))
            self.stdout.write("  • View flags in admin: /admin/core/featureflag/")
            self.stdout.write(
                '  • Check flag status: python manage.py shell -c "from core.services.feature_flag_service import feature_flags; print(feature_flags.get_all_flags())"'
            )
