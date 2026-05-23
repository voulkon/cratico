import time
from datetime import datetime

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models import Organization
from core.services.decision_ingestion_service import DecisionIngestionService
from django.core.management.base import BaseCommand
from django.db.models import Q
from loguru import logger


class Command(BaseCommand):
    help = "Import decisions from major government organizations in Greece"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            required=True,
            help="Start date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--end-date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            required=True,
            help="End date (YYYY-MM-DD)",
        )
        parser.add_argument(
            "--org-type",
            type=str,
            choices=["ministries", "municipalities", "regions", "all"],
            default="ministries",
            help="Organization type to fetch: ministries, municipalities, regions, or all",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of organizations to process",
        )
        parser.add_argument(
            "--skip",
            type=int,
            default=0,
            help="Skip the first N organizations",
        )
        parser.add_argument(
            "--distributed",
            action="store_true",
            help="Use Celery for distributed processing",
        )
        parser.add_argument(
            "--debug",
            action="store_true",
            help="Show debug information",
        )

    def handle(self, *args, **options):
        start_date = options["start_date"]
        end_date = options["end_date"]
        org_type = options["org_type"]
        limit = options["limit"]
        skip = options["skip"]
        distributed = options["distributed"]
        debug = options["debug"]

        # Query filters based on organization type
        filters = self._get_org_filters(org_type)

        # Get organizations matching the filter
        orgs = Organization.objects.filter(filters).order_by("label")

        # Apply skip and limit
        if skip:
            orgs = orgs[skip:]
        if limit:
            orgs = orgs[:limit]

        total_orgs = orgs.count()
        self.stdout.write(
            f"Found {total_orgs} organizations matching filter: {org_type}"
        )

        if not total_orgs:
            self.stdout.write(self.style.WARNING("No matching organizations found!"))
            return

        # Create service components
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter()
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        total_decisions = 0
        start_time = time.time()

        # Process each organization
        for i, org in enumerate(orgs):
            org_start_time = time.time()
            self.stdout.write(
                f"Processing {i+1}/{total_orgs}: {org.label} (UID: {org.uid})"
            )

            try:
                search_params = {"org": org.uid}
                decisions = service.fetch_decisions_for_period(
                    start_date=start_date,
                    end_date=end_date,
                    date_increment_days=30,  # Using a 30-day window
                    search_params=search_params,
                    distributed=distributed,
                    save_to_db=True,
                )

                count = len(decisions)
                total_decisions += count

                org_time = time.time() - org_start_time
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] Fetched {count} decisions for {org.label} ({org_time:.1f}s)"
                    )
                )

                if debug:
                    self.stdout.write(
                        f"  - Progress: {total_decisions} total decisions"
                    )
                    self.stdout.write(f"  - Elapsed: {time.time() - start_time:.1f}s")

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"[FAIL] Error processing {org.label}: {e}")
                )
                logger.error(f"Error processing organization {org.uid}: {e}")

        total_time = time.time() - start_time
        self.stdout.write(
            self.style.SUCCESS(
                f"Completed importing {total_decisions} decisions from {total_orgs} organizations in {total_time:.1f}s"
            )
        )

    def _get_org_filters(self, org_type):
        """Return Q objects for filtering organizations based on type"""
        if org_type == "ministries":
            return Q(label__startswith="ΥΠΟΥΡΓΕΙΟ")
        elif org_type == "municipalities":
            return Q(label__startswith="ΔΗΜΟΣ")
        elif org_type == "regions":
            return Q(label__startswith="ΠΕΡΙΦΕΡΕΙΑ")
        elif org_type == "all":
            return (
                Q(label__startswith="ΥΠΟΥΡΓΕΙΟ")
                | Q(label__startswith="ΔΗΜΟΣ")
                | Q(label__startswith="ΠΕΡΙΦΕΡΕΙΑ")
            )
        else:
            return Q()
