from datetime import date

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.services.decision_ingestion_service import DecisionIngestionService
from core.tasks import process_fetch_period
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Queue tasks to fetch decisions from Diavgeia API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--start-date",
            type=str,
            help="Start date in YYYY-MM-DD format",
            required=True,
        )
        parser.add_argument(
            "--end-date", type=str, help="End date in YYYY-MM-DD format", required=True
        )
        parser.add_argument(
            "--local",
            action="store_true",
            help="Run processing locally instead of distributing to workers",
        )
        parser.add_argument(
            "--increment",
            type=int,
            default=30,
            help="Date increment days (default: 30)",
        )
        parser.add_argument("--org", type=str, help="Organization ID or latin name")
        parser.add_argument("--signer", type=str, help="Signer ID")

    def handle(self, *args, **options):
        start_date_str = options["start_date"]
        end_date_str = options["end_date"]

        # Validate dates
        try:
            start_date = date.fromisoformat(start_date_str)
            end_date = date.fromisoformat(end_date_str)
        except ValueError:
            self.stderr.write(self.style.ERROR("Invalid date format. Use YYYY-MM-DD."))
            return

        if start_date > end_date:
            self.stderr.write(self.style.ERROR("Start date must be before end date"))
            return

        # Build search params from command args
        search_params = {}
        if options["org"]:
            search_params["org"] = options["org"]
        if options["signer"]:
            search_params["signer"] = options["signer"]

        # Choose execution mode
        if options["local"]:
            # Run synchronously
            self.stdout.write("Running in local mode...")
            fetcher = DiavgeiaFetcher()
            service = DecisionIngestionService(fetcher)
            decisions = service.fetch_decisions_for_period(
                start_date, end_date, options["increment"], search_params
            )
            self.stdout.write(
                self.style.SUCCESS(f"Fetched {len(decisions)} decisions locally")
            )
        else:
            # Run distributed via Celery
            self.stdout.write("Running in distributed mode...")
            result = process_fetch_period.delay(
                start_date_str, end_date_str, options["increment"], search_params
            )
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully queued decision fetch tasks with ID: {result.id}"
                )
            )
