"""
Management command to add users to the stealth mode allowlist
"""

from django.core.management.base import BaseCommand
from users.models import AllowedUser


class Command(BaseCommand):
    help = "Add a user to the stealth mode allowlist"

    def add_arguments(self, parser):
        parser.add_argument(
            "email", type=str, help="Email address of the user to allow"
        )
        parser.add_argument(
            "--name", type=str, help="Full name of the user (optional)", default=""
        )
        parser.add_argument(
            "--notes", type=str, help="Internal notes (optional)", default=""
        )

    def handle(self, *args, **options):
        email = options["email"]
        name = options.get("name", "")
        notes = options.get("notes", "")

        # Check if user already exists
        if AllowedUser.objects.filter(email=email).exists():
            allowed_user = AllowedUser.objects.get(email=email)
            if allowed_user.is_active:
                self.stdout.write(
                    self.style.WARNING(
                        f"User {email} is already in the allowlist and active."
                    )
                )
            else:
                # Reactivate if they were deactivated
                allowed_user.is_active = True
                allowed_user.save()
                self.stdout.write(self.style.SUCCESS(f"[OK] Reactivated user: {email}"))
            return

        # Create new allowed user
        AllowedUser.objects.create(email=email, name=name, notes=notes, is_active=True)

        self.stdout.write(self.style.SUCCESS(f"[OK] Added user to allowlist: {email}"))

        if not name:
            self.stdout.write(
                self.style.WARNING(
                    '  Tip: Add --name "Full Name" to make it easier to identify users'
                )
            )
