import time

from core.models.document_analysis import DocumentExtraction, ProcessingStatus
from core.services.opensearch_service import OpenSearchService
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Backfill OpenSearch index from existing DocumentExtraction records"

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of documents to process in each batch (default: 100)",
        )
        parser.add_argument(
            "--limit",
            type=int,
            help="Maximum number of documents to process (for testing)",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be indexed without actually indexing",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force reindexing even if document already exists in OpenSearch",
        )
        parser.add_argument(
            "--organization",
            type=str,
            help="Only index documents from specific organization (by label)",
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        limit = options.get("limit")
        dry_run = options["dry_run"]
        options["force"]
        organization_filter = options.get("organization")

        self.stdout.write(self.style.WARNING("=" * 60))
        self.stdout.write(self.style.WARNING("OPENSEARCH BACKFILL STARTING"))
        self.stdout.write(self.style.WARNING("=" * 60))

        # Initialize OpenSearch service
        opensearch_service = OpenSearchService()

        # Build the queryset
        queryset = (
            DocumentExtraction.objects.filter(
                extraction_status=ProcessingStatus.COMPLETED, raw_text__isnull=False
            )
            .exclude(raw_text="")
            .select_related(
                "decision", "decision__organization", "decision__decision_type"
            )
        )

        # Apply organization filter if provided
        if organization_filter:
            queryset = queryset.filter(
                decision__organization__label__icontains=organization_filter
            )
            self.stdout.write(f"Filtering by organization: {organization_filter}")

        # Apply limit if provided
        if limit:
            queryset = queryset[:limit]

        total_count = queryset.count()
        self.stdout.write(f"Found {total_count} DocumentExtraction records to process")

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN MODE - No actual indexing will occur")
            )

        if total_count == 0:
            self.stdout.write(self.style.ERROR("No documents found to index!"))
            return

        # Process in batches
        processed = 0
        success_count = 0
        error_count = 0
        batch_number = 1

        while processed < total_count:
            start_idx = processed
            end_idx = min(processed + batch_size, total_count)

            batch = queryset[start_idx:end_idx]

            self.stdout.write(
                f"\\nProcessing batch {batch_number} ({start_idx + 1}-{end_idx} of {total_count})"
            )

            batch_start_time = time.time()
            batch_success = 0
            batch_errors = 0

            for extraction in batch:
                try:
                    # Prepare document data (same as signal)
                    document_data = {
                        "decision_id": extraction.decision.id,
                        "ada": extraction.decision.ada,
                        "title": extraction.decision.subject or "",
                        "content": extraction.raw_text,
                        "organization": (
                            str(extraction.decision.organization)
                            if extraction.decision.organization
                            else ""
                        ),
                        "decision_type": (
                            str(extraction.decision.decision_type)
                            if extraction.decision.decision_type
                            else ""
                        ),
                        "issue_date": (
                            extraction.decision.issue_date.isoformat()
                            if extraction.decision.issue_date
                            else None
                        ),
                        "extraction_date": (
                            extraction.extraction_date.isoformat()
                            if extraction.extraction_date
                            else None
                        ),
                        "character_count": extraction.character_count,
                        "page_count": extraction.page_count,
                    }

                    if dry_run:
                        self.stdout.write(
                            f"  Would index: {extraction.decision.ada} - {document_data['title'][:50]}..."
                        )
                        batch_success += 1
                    else:
                        # Index the document
                        success = opensearch_service.index_document(document_data)

                        if success:
                            batch_success += 1
                            if batch_success <= 3:  # Show first few successes
                                self.stdout.write(
                                    f"  [OK] Indexed: {extraction.decision.ada}"
                                )
                        else:
                            batch_errors += 1
                            self.stdout.write(
                                self.style.ERROR(
                                    f"  [ERROR] Failed: {extraction.decision.ada}"
                                )
                            )

                except Exception as e:
                    batch_errors += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [ERROR] Error indexing {extraction.decision.ada}: {e}"
                        )
                    )

            # Batch summary
            batch_time = time.time() - batch_start_time
            success_count += batch_success
            error_count += batch_errors
            processed += len(batch)

            self.stdout.write(
                f"  Batch {batch_number} complete: {batch_success} success, {batch_errors} errors ({batch_time:.2f}s)"
            )

            batch_number += 1

            # Small delay between batches to avoid overwhelming OpenSearch
            if not dry_run and processed < total_count:
                time.sleep(0.5)

        # Final summary
        self.stdout.write("\\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS("BACKFILL COMPLETE"))
        self.stdout.write("=" * 60)
        self.stdout.write(f"Total processed: {processed}")
        self.stdout.write(f"Successful: {success_count}")
        self.stdout.write(f"Errors: {error_count}")

        if not dry_run:
            # Force refresh the index to make documents searchable immediately
            try:
                opensearch_service._force_refresh()
                self.stdout.write("[OK] OpenSearch index refreshed")
            except:
                self.stdout.write("[WARN]️ Could not refresh OpenSearch index")

        if error_count > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"[WARN]️ {error_count} documents failed to index - check logs for details"
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("[EVENT] All documents indexed successfully!")
            )
