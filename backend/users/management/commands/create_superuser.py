import os

from core.services.feature_flag_service import feature_flags
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = "Creates or updates a superuser and adds them to the allowlist if stealth mode is enabled"

    def add_arguments(self, parser):
        parser.add_argument(
            "email", nargs="?", type=str, help="Email address for the superuser"
        )
        parser.add_argument(
            "username", nargs="?", type=str, help="Username for the superuser"
        )
        parser.add_argument(
            "password", nargs="?", type=str, help="Password for the superuser"
        )

    def handle(self, *args, **options):
        # Use command-line arguments if provided, otherwise use environment variables
        email = options.get("email") or os.environ.get(
            "DJANGO_SUPERUSER_EMAIL", "admin@example.com"
        )
        username = options.get("username") or os.environ.get(
            "DJANGO_SUPERUSER_USERNAME", "admin"
        )
        password = options.get("password") or os.environ.get(
            "DJANGO_SUPERUSER_PASSWORD", "password"
        )

        # Check if we should auto-update existing superuser (default: False for safety)
        auto_update = os.getenv("DJANGO_SUPERUSER_AUTO_UPDATE", "False").lower() in (
            "true",
            "1",
            "t",
        )

        # Check if stealth mode with allowlist is enabled (check DB first, then env)
        stealth_mode = feature_flags.is_enabled("STEALTH_MODE")
        stealth_allowlist = feature_flags.is_enabled("STEALTH_ALLOWLIST")

        # Check if a superuser already exists
        existing_superuser = User.objects.filter(is_superuser=True).first()

        if existing_superuser:
            if auto_update:
                # Update existing superuser
                existing_superuser.email = email
                existing_superuser.username = username
                existing_superuser.set_password(password)
                existing_superuser.save()

                self.stdout.write(
                    self.style.SUCCESS(
                        f'Superuser "{username}" updated successfully (email: {email})'
                    )
                )
                user = existing_superuser
            else:
                # Don't update, just ensure they're in allowlist if needed
                self.stdout.write(
                    self.style.WARNING(
                        f"Superuser already exists (username: {existing_superuser.username}). "
                        "Set DJANGO_SUPERUSER_AUTO_UPDATE=true to auto-update credentials."
                    )
                )
                user = existing_superuser
        else:
            # Create new superuser
            user = User.objects.create_superuser(
                username=username, email=email, password=password
            )

            self.stdout.write(
                self.style.SUCCESS(
                    f'Superuser "{username}" created successfully (email: {email})'
                )
            )

        # If stealth mode with allowlist is enabled, add superuser to allowlist
        if stealth_mode and stealth_allowlist:
            self._add_to_allowlist(user, email, username)

    def _add_to_allowlist(self, user, email, username):
        """Add user to the AllowedUser table if not already there"""
        try:
            from users.models import AllowedUser

            allowed_user, created = AllowedUser.objects.get_or_create(
                email=email,
                defaults={
                    "name": username,
                    "notes": "Auto-added superuser for admin access",
                    "is_active": True,
                    "clerk_user_id": None,
                },
            )

            if created:
                self.stdout.write(
                    self.style.SUCCESS(
                        f'Added "{email}" to allowlist (stealth mode with allowlist is enabled)'
                    )
                )
            else:
                # Ensure it's active
                if not allowed_user.is_active:
                    allowed_user.is_active = True
                    allowed_user.save()
                    self.stdout.write(
                        self.style.SUCCESS(f'Reactivated "{email}" in allowlist')
                    )
                else:
                    self.stdout.write(
                        self.style.WARNING(f'"{email}" already in allowlist')
                    )
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f"Failed to add superuser to allowlist: {str(e)}")
            )
