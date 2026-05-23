"""
Management command to check feature flag status.
Useful for debugging feature flag issues in deployed environments.
"""

import os

from core.models.feature_flags import FeatureFlag
from core.services.feature_flag_service import feature_flags
from django.core.cache import cache
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check current status of feature flags (database, cache, environment)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--flag",
            type=str,
            help="Specific flag to check (default: checks all important flags)",
        )
        parser.add_argument(
            "--clear-cache",
            action="store_true",
            help="Clear the feature flag cache",
        )

    def handle(self, *args, **options):
        if options["clear_cache"]:
            self.stdout.write(self.style.WARNING("Clearing feature flag cache..."))
            feature_flags.clear_cache()
            cache.delete("feature_flags:all")
            self.stdout.write(self.style.SUCCESS("[OK] Cache cleared"))
            return

        flag_key = options.get("flag")

        if flag_key:
            flags_to_check = [flag_key]
        else:
            # Check important flags
            flags_to_check = [
                "STEALTH_MODE",
                "STEALTH_ALLOWLIST",
                "STEALTH_EXEMPT_PREFIXES",
                "INDEX_THE_OPENSEARCH",
                "HAVE_AFM_FETCH_JOB",
            ]

        self.stdout.write(self.style.SUCCESS("\n=== Feature Flag Status ===\n"))

        for flag in flags_to_check:
            self.stdout.write(self.style.HTTP_INFO(f"\n{flag}:"))

            # Check database
            try:
                db_flag = FeatureFlag.objects.filter(key=flag, is_active=True).first()
                if db_flag:
                    db_value = db_flag.get_value()
                    self.stdout.write(
                        f"  Database:    {self._format_value(db_value)} (type: {db_flag.value_type})"
                    )
                else:
                    self.stdout.write(f"  Database:    NOT SET")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  Database:    ERROR - {e}"))

            # Check cache
            cache_key = f"feature_flag:{flag}"
            cached = cache.get(cache_key)
            if cached is not None:
                self.stdout.write(f"  Cache:       {self._format_value(cached)}")
            else:
                self.stdout.write(f"  Cache:       NOT CACHED")

            # Check environment
            env_value = os.getenv(flag)
            if env_value:
                self.stdout.write(f"  Environment: {env_value}")
            else:
                self.stdout.write(f"  Environment: NOT SET")

            # Check final computed value
            final_value = feature_flags.get_value(flag)
            self.stdout.write(
                self.style.SUCCESS(f"  → Final:     {self._format_value(final_value)}")
            )

            # Get detailed info
            info = feature_flags.get_flag_info(flag)
            if info:
                self.stdout.write(f'  Source:      {info.get("source")}')

        self.stdout.write("\n")

        # Check Clerk configuration
        clerk_key = os.getenv("CLERK_JWT_PUBLIC_KEY")
        if clerk_key:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[WARN]️  Clerk is ACTIVE (CLERK_JWT_PUBLIC_KEY is set)"
                )
            )
            self.stdout.write(
                "   If not using Clerk, remove CLERK_JWT_PUBLIC_KEY from environment\n"
            )
        else:
            self.stdout.write(self.style.SUCCESS("\n[OK] Clerk is NOT configured\n"))

    def _format_value(self, value):
        """Format a value for display."""
        if isinstance(value, bool):
            return (
                self.style.SUCCESS("[OK] TRUE")
                if value
                else self.style.ERROR("[FAIL] FALSE")
            )
        elif isinstance(value, list):
            count = len(value)
            return f"[{count} items] {value}"
        else:
            return str(value)
