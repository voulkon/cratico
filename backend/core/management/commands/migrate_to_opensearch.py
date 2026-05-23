import time

from core.models.document_analysis import DocumentExtraction
from core.services.opensearch_service import OpenSearchService
from django.core.management.base import BaseCommand
from django.db.models import Q
from loguru import logger


class Command(BaseCommand):
    help = "Migrate existing document extractions to OpenSearch"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of documents to process in each batch",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without actually doing it",
        )
        parser.add_argument(
            "--start-from-id",
            type=int,
            default=0,
            help="Start migration from a specific document ID",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        dry_run = options["dry_run"]
        start_from_id = options["start_from_id"]

        self.stdout.write(f"Migration settings:")
        self.stdout.write(f"  Batch size: {batch_size}")
        self.stdout.write(f"  Dry run: {dry_run}")
        self.stdout.write(f"  Start from ID: {start_from_id}")
        self.stdout.write("")

        # Get completed extractions with content
        base_filter = (
            Q(extraction_status="COMPLETED")
            & Q(raw_text__isnull=False)
            & ~Q(raw_text="")
        )

        # Add start_from_id filter only if it's greater than 0
        if start_from_id > 0:
            base_filter &= Q(id__gte=start_from_id)

        queryset = (
            DocumentExtraction.objects.filter(base_filter)
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
            .order_by("id")
        )

        total_count = queryset.count()

        self.stdout.write(f"Found {total_count} documents to migrate")

        if total_count == 0:
            self.stdout.write(
                self.style.WARNING("No documents found matching criteria")
            )
            return

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN - No actual migration will occur")
            )
            self.stdout.write("\nSample documents that would be migrated:")

            # Show sample of what would be migrated
            for i, extraction in enumerate(queryset[:5]):
                decision = extraction.decision
                content_preview = (
                    extraction.raw_text[:100] if extraction.raw_text else "No content"
                )

                self.stdout.write(f"  {i+1}. ID: {extraction.id}")
                self.stdout.write(f"     ADA: {decision.ada}")
                self.stdout.write(
                    f"     Subject: {decision.subject[:50] if decision.subject else 'No subject'}..."
                )
                self.stdout.write(f"     Organization: {decision.organization}")
                self.stdout.write(f"     Decision Type: {decision.decision_type}")
                self.stdout.write(f"     Content: {content_preview}...")
                self.stdout.write(f"     Characters: {extraction.character_count}")
                self.stdout.write("")

            if total_count > 5:
                self.stdout.write(f"... and {total_count - 5} more documents")

            return

        # Actual migration
        self.stdout.write(self.style.SUCCESS("Starting migration..."))

        opensearch_service = OpenSearchService()

        processed = 0
        errors = 0

        # Process in batches
        for batch_start in range(0, total_count, batch_size):
            batch_end = min(batch_start + batch_size, total_count)
            batch = queryset[batch_start:batch_end]

            self.stdout.write(
                f"Processing batch {batch_start//batch_size + 1}/{(total_count-1)//batch_size + 1} (documents {batch_start+1}-{batch_end})"
            )

            for extraction in batch:
                try:
                    decision = extraction.decision

                    # Prepare document data with correct field names
                    document_data = {
                        "decision_id": decision.id,
                        "ada": decision.ada,
                        "title": decision.subject or "",
                        "content": extraction.raw_text,  # Let the service handle truncation
                        "organization": (
                            str(decision.organization) if decision.organization else ""
                        ),  # Fixed!
                        "decision_type": (
                            str(decision.decision_type)
                            if decision.decision_type
                            else ""
                        ),  # Fixed!
                        "issue_date": (
                            decision.issue_date.isoformat()
                            if decision.issue_date
                            else None
                        ),
                        "extraction_date": (
                            extraction.extraction_date.isoformat()
                            if extraction.extraction_date
                            else None
                        ),
                        "character_count": extraction.character_count,
                        "page_count": extraction.page_count,
                        "migrated_at": time.time(),
                    }

                    success = opensearch_service.index_document(document_data)

                    if success:
                        processed += 1
                        if processed % 50 == 0:
                            self.stdout.write(
                                f"  Processed {processed}/{total_count} documents"
                            )
                    else:
                        errors += 1
                        logger.error(f"Failed to index document {decision.ada}")

                except Exception as e:
                    errors += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  Error processing document ID {extraction.id}: {e}"
                        )
                    )

            # Small delay between batches to avoid overwhelming OpenSearch
            if batch_end < total_count:  # Don't sleep after the last batch
                time.sleep(1)

        # Final summary
        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Migration completed!"))
        self.stdout.write(f"  Processed: {processed}")
        self.stdout.write(f"  Errors: {errors}")
        if processed + errors > 0:
            success_rate = processed / (processed + errors) * 100
            self.stdout.write(f"  Success rate: {success_rate:.1f}%")

        if errors > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\n{errors} documents failed to migrate. Check logs for details."
                )
            )
