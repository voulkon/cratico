import time  # Import time module for sleep

from core.models.decisions import Decision
from core.models.document_analysis import ProcessingStatus
from core.services.document_processor import DocumentAnalysisService
from django.core.management.base import BaseCommand
from django.db.models import Q
from tqdm import tqdm


class Command(BaseCommand):
    help = "Process PDF documents from decisions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Limit the number of documents to process",
        )
        parser.add_argument(
            "--async",
            action="store_true",
            help="Run the processing asynchronously using Celery tasks.",
        )
        parser.add_argument(
            "--ada", type=str, help="Process a specific decision by ADA"
        )
        parser.add_argument(
            "--unprocessed-only",
            action="store_true",
            help="Only process documents that haven't been processed yet",
        )
        parser.add_argument(
            "--from-date",
            type=str,  # Or use datetime.date.fromisoformat directly if desired
            help="Start date for filtering decisions (YYYY-MM-DD).",
        )
        parser.add_argument(
            "--to-date",
            type=str,
            help="End date for filtering decisions (YYYY-MM-DD).",
        )

    def handle(self, *args, **options):
        service = DocumentAnalysisService()
        limit = options["limit"]
        ada = options.get("ada")
        unprocessed_only = options.get("unprocessed_only", False)
        use_async = options.get("async", False)  # Get async flag
        from_date = options.get("from_date")  # Get date flags
        to_date = options.get("to_date")
        if ada:
            # --- Process Single ADA ---
            try:
                decision = Decision.objects.get(ada=ada)
                self.stdout.write(
                    f"Processing decision {decision.ada} {'asynchronously' if use_async else 'synchronously'}"
                )
                if use_async:
                    from core.tasks import process_document_task

                    task = process_document_task.delay(decision.ada)
                    self.stdout.write(
                        self.style.SUCCESS(f"Task queued with ID: {task.id}")
                    )
                else:
                    result = service.process_decision(decision)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Result: {result['success']} - Status: {result.get('extraction_status')}"
                        )
                    )
            except Decision.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Decision with ADA {ada} not found")
                )
            return  # Exit after processing single ADA

        # --- Process Batch ---
        self.stdout.write("Finding decisions for batch processing...")

        # Base query
        query = Decision.objects.filter(
            ~Q(document_url__isnull=True) & ~Q(document_url="")
        ).order_by("-publish_timestamp")

        # Apply filters
        if unprocessed_only:
            self.stdout.write("Filtering for unprocessed documents only.")
            # Exclude COMPLETED, filter for others or non-existent extraction
            query = query.exclude(
                text_extraction__extraction_status=ProcessingStatus.COMPLETED
            )

        if from_date:
            self.stdout.write(f"Filtering from date: {from_date}")
            query = query.filter(publish_timestamp__gte=from_date)
        if to_date:
            self.stdout.write(f"Filtering to date: {to_date}")
            query = query.filter(publish_timestamp__lte=to_date)

        # Get the list of ADAs within the limit
        ada_list = list(query.values_list("ada", flat=True)[:limit])
        total_found = len(ada_list)

        if total_found == 0:
            self.stdout.write(
                self.style.WARNING("No matching decisions found to process.")
            )
            return

        self.stdout.write(f"Found {total_found} decisions to process.")

        if use_async:
            # --- Async Batch Processing ---
            from core.tasks import process_document_batch

            # Reduce batch size to avoid overwhelming the server
            batch_size = min(limit, 50)  # Process in smaller batches

            if total_found > batch_size:
                self.stdout.write(
                    self.style.WARNING(
                        f"Found {total_found} decisions, but processing in batches of {batch_size} to avoid overwhelming the server."
                    )
                )

                # Process in chunks
                for i in range(0, len(ada_list), batch_size):
                    batch = ada_list[i : i + batch_size]
                    batch_num = (i // batch_size) + 1
                    total_batches = (len(ada_list) + batch_size - 1) // batch_size

                    self.stdout.write(
                        f"Starting batch {batch_num}/{total_batches} ({len(batch)} documents)"
                    )

                    task = process_document_batch.delay(batch)
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Batch {batch_num} queued with task ID: {task.id}"
                        )
                    )

                    # Small delay between batches to avoid overwhelming
                    time.sleep(1)
            else:
                # Single batch
                task = process_document_batch.delay(ada_list)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Started async batch processing for {total_found} documents with task ID: {task.id}"
                    )
                )
        else:
            # --- Synchronous Batch Processing ---
            self.stdout.write(f"Processing {total_found} decisions synchronously...")
            success_count = 0
            # Fetch decisions corresponding to the ada_list to avoid N+1 queries inside loop
            decisions_to_process = Decision.objects.filter(ada__in=ada_list)

            for decision in tqdm(
                decisions_to_process, total=total_found, desc="Processing Decisions"
            ):
                try:
                    # Log every 10th decision for progress tracking
                    if (success_count + 1) % 10 == 0:
                        self.stdout.write(
                            f"Processing decision #{success_count + 1}: {decision.ada}"
                        )

                    result = service.process_decision(decision)
                    if result["success"]:
                        success_count += 1
                        # Log successful extractions with brief info
                        if result.get("extraction_status") == "COMPLETED":
                            self.stdout.write(
                                self.style.SUCCESS(
                                    f"[OK] {decision.ada} - Extracted successfully"
                                )
                            )
                    else:
                        self.stdout.write(
                            self.style.ERROR(
                                f"[ERROR] Failed processing {decision.ada}"
                            )
                        )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(
                            f"[CRASH] Error processing {decision.ada}: {e}"
                        )
                    )
                time.sleep(0.5)  # 500ms delay between requests

            self.stdout.write(
                self.style.SUCCESS(
                    f"Synchronous processing complete. {success_count}/{total_found} successful."
                )
            )
