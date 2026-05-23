import random
import time

from core.models.decisions import Decision
from core.models.import_jobs import DateCoverage
from core.models.organizations import Organization, Signer
from core.tests.utils import create_db_decision  # Import the utility
from django.core.management.base import BaseCommand
from django.utils import timezone


class Command(BaseCommand):
    help = "Tests if signals are correctly updating the DateCoverage table"

    def handle(self, *args, **options):
        self.stdout.write("Testing DateCoverage signals...")

        # 1. Clear test data from DateCoverage
        test_date = timezone.now().date()
        DateCoverage.objects.filter(date=test_date).delete()
        self.stdout.write(f"Cleared DateCoverage records for {test_date}")

        # 2. Check DateCoverage count before changes
        before_count = DateCoverage.objects.filter(date=test_date).count()
        self.stdout.write(f"DateCoverage records before test: {before_count}")

        # 3. Find an organization to use
        organization = Organization.objects.first()
        if not organization:
            self.stdout.write(
                self.style.ERROR("No organizations found. Cannot create test decision.")
            )
            return

        # 4. Find a signer to use
        signer = Signer.objects.first()
        if not signer:
            self.stdout.write(
                self.style.WARNING(
                    "No signers found, testing only organization signals"
                )
            )

        # 5. Create a test decision using the utility
        try:
            self.stdout.write(f"Creating test decision for org: {organization.uid}")
            # Create the decision using our utility
            test_ada = f"TEST{random.randint(10000, 99999)}"
            decision_id = create_db_decision(
                as_model=True,  # This doesn't actually return a model
                ada=test_ada,
                org_id=organization.uid,
                signer_ids=[signer.uid] if signer else [],
                unit_ids=[],  # Don't include test units
                extra_attributes={
                    "issueDate": timezone.now(),  # Use today's date
                },
            )

            # Get the actual Decision instance using the returned ID
            decision = (
                Decision.objects.get(id=decision_id)
                if isinstance(decision_id, int)
                else decision_id
            )

            self.stdout.write(f"Created test decision with ID: {decision.id}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error creating test decision: {e}"))
            import traceback

            self.stdout.write(self.style.ERROR(traceback.format_exc()))
            return

        # 6. Wait a moment for signals to process
        self.stdout.write("Waiting for signals to process...")
        time.sleep(1)

        # 7. Check if DateCoverage was created via signal
        self.stdout.write("Checking if signals created DateCoverage records...")

        # Check for organization coverage
        org_coverage = DateCoverage.objects.filter(
            date=test_date, organization=organization
        ).first()

        if org_coverage:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] SUCCESS: Organization coverage created! Count: {org_coverage.decision_count}"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "[ERROR] FAIL: No organization coverage record was created via signal"
                )
            )

        # Check for signer coverage if we had a signer
        if signer:
            signer_coverage = DateCoverage.objects.filter(
                date=test_date, signer=signer
            ).first()

            if signer_coverage:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] SUCCESS: Signer coverage created! Count: {signer_coverage.decision_count}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        "[ERROR] FAIL: No signer coverage record was created via signal"
                    )
                )

        # 8. Delete the test decision and check if signals update DateCoverage
        self.stdout.write("Testing delete signal...")
        decision.delete()

        time.sleep(1)

        # Check if DateCoverage was updated after deletion
        org_coverage_after = DateCoverage.objects.filter(
            date=test_date, organization=organization
        ).first()

        if org_coverage_after is None:
            self.stdout.write(
                self.style.SUCCESS(
                    "[OK] SUCCESS: Organization coverage was removed after deletion"
                )
            )
        elif org_coverage_after.decision_count < org_coverage.decision_count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] SUCCESS: Organization coverage was updated after deletion (count: {org_coverage_after.decision_count})"
                )
            )
        else:
            self.stdout.write(
                self.style.ERROR(
                    "[ERROR] FAIL: Organization coverage was not updated after deletion"
                )
            )

        self.stdout.write(self.style.SUCCESS("Signal test completed"))
