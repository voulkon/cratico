from core.services.seed_service import SeedService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Debug organization detail seeding for a specific organization"

    def add_arguments(self, parser):
        parser.add_argument(
            "organization_uid",
            type=str,
            help="UID of the organization to seed details for",
        )
        parser.add_argument(
            "--verbose", action="store_true", help="Print extra debug information"
        )

    def handle(self, *args, **options):
        organization_uid = options["organization_uid"]
        verbose = options["verbose"]

        if verbose:
            self.stdout.write(
                f"Starting debug seeding for organization {organization_uid}"
            )
            # Set debug breakpoint flag to make it easier to find in your IDE
            debug_here = True  # You can set a breakpoint on this line

        service = SeedService()

        # Debug point before calling seed_organization_details
        before_seed = True  # Set breakpoint here

        # Call the method
        results = service.seed_organization_details(organization_uid)

        # Debug point after getting results
        after_seed = True  # Set breakpoint here

        # Print results
        self.stdout.write(self.style.SUCCESS(f"Results: {results}"))

        # Return successes/failures
        if "error" in results:
            self.stdout.write(self.style.ERROR(f"Error: {results['error']}"))
            return

        # Additional debug information
        if verbose:
            from core.models.organizations import Position, SignerUnit

            # Count SignerUnits for this organization
            signer_units = SignerUnit.objects.filter(
                signer__organization__uid=organization_uid
            ).count()

            # Count Positions used in SignerUnits
            position_ids = (
                SignerUnit.objects.filter(signer__organization__uid=organization_uid)
                .values_list("position_id", flat=True)
                .distinct()
            )
            positions = Position.objects.filter(uid__in=position_ids).count()

            self.stdout.write(
                f"SignerUnits: {signer_units}, Unique Position IDs: {len(position_ids)}, Actual Positions: {positions}"
            )
