from core.models.document_analysis import DocumentExtraction, DocumentPage
from core.services.document_processor import TextExtractionProcessor
from django.core.management.base import BaseCommand
from django.db import transaction
from loguru import logger


class Command(BaseCommand):
    help = "Migrate existing document extractions to page-based model"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be migrated without making changes",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=10,
            help="Number of documents to process at once",
        )
        parser.add_argument(
            "--re-extract",
            action="store_true",
            help="Re-extract documents using TextExtractionProcessor (downloads files again)",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        batch_size = options["batch_size"]
        re_extract = options["re_extract"]

        # Get extractions that have raw_text but no pages
        extractions_to_migrate = DocumentExtraction.objects.filter(
            raw_text__isnull=False, pages__isnull=True, extraction_status="COMPLETED"
        ).distinct()

        total_count = extractions_to_migrate.count()
        logger.info(f"Found {total_count} extractions to migrate")

        if dry_run:
            logger.info("DRY RUN - No changes will be made")
            for extraction in extractions_to_migrate[:5]:  # Show first 5
                text_len = len(extraction.raw_text) if extraction.raw_text else 0
                pages = extraction.page_count or 1
                logger.info(
                    f"Would migrate: {extraction.decision.ada} ({text_len} chars, {pages} pages)"
                )
            return

        success_count = 0
        error_count = 0

        for i in range(0, total_count, batch_size):
            batch = extractions_to_migrate[i : i + batch_size]
            logger.info(f"Processing batch {i//batch_size + 1} ({len(batch)} items)")

            for extraction in batch:
                try:
                    if re_extract:
                        success = self.re_extract_with_processor(extraction)
                    else:
                        success = self.split_existing_text(extraction)

                    if success:
                        success_count += 1
                    else:
                        error_count += 1
                except Exception as e:
                    logger.error(f"Error migrating {extraction.decision.ada}: {e}")
                    error_count += 1

        logger.info(
            f"Migration complete: {success_count} successful, {error_count} errors"
        )

    def re_extract_with_processor(self, extraction: DocumentExtraction) -> bool:
        """Re-extract the document using TextExtractionProcessor"""
        try:
            logger.info(
                f"Re-extracting {extraction.decision.ada} with TextExtractionProcessor"
            )

            # Reset the extraction status so it gets re-processed
            extraction.extraction_status = "PENDING"
            extraction.save(update_fields=["extraction_status"])

            # Use the existing processor
            processor = TextExtractionProcessor()
            success = processor.process_document(extraction.decision)

            if success:
                logger.info(f"Successfully re-extracted {extraction.decision.ada}")
                return True
            else:
                logger.error(f"Failed to re-extract {extraction.decision.ada}")
                return False

        except Exception as e:
            logger.error(f"Re-extraction failed for {extraction.decision.ada}: {e}")
            return False

    def split_existing_text(self, extraction: DocumentExtraction) -> bool:
        """Split existing text into pages using simple rule of thumb"""
        try:
            logger.info(f"Splitting existing text for {extraction.decision.ada}")

            text = extraction.raw_text or ""
            page_count = extraction.page_count or 1

            if not text:
                logger.warning(f"No text to split for {extraction.decision.ada}")
                return False

            with transaction.atomic():
                if page_count == 1:
                    # Single page - easy case
                    DocumentPage.objects.create(
                        extraction=extraction,
                        page_number=1,
                        raw_text=text,
                        character_count=len(text),
                    )
                    logger.info(f"Created single page for {extraction.decision.ada}")
                else:
                    # Multi-page - split by estimated page size with word boundaries
                    chars_per_page = len(text) // page_count
                    current_pos = 0

                    for page_num in range(1, page_count + 1):
                        if page_num == page_count:
                            # Last page - take everything remaining
                            page_text = text[current_pos:].strip()
                        else:
                            # Find the ideal break point
                            ideal_end = current_pos + chars_per_page

                            # If we're at or past the end, take everything
                            if ideal_end >= len(text):
                                page_text = text[current_pos:].strip()
                                current_pos = len(text)  # Add this line
                            else:
                                # Find the best word boundary
                                # Look backward from ideal point for a good break
                                search_start = max(
                                    current_pos, ideal_end - 200
                                )  # Don't go too far back

                                # Look for sentence endings first (. ! ?)
                                sentence_break = -1
                                for i in range(ideal_end, search_start - 1, -1):
                                    if (
                                        text[i] in ".!?"
                                        and i + 1 < len(text)
                                        and text[i + 1] in " \n"
                                    ):
                                        sentence_break = i + 1
                                        break

                                if sentence_break > search_start:
                                    # Found a good sentence break
                                    end_pos = sentence_break
                                else:
                                    # Fall back to word boundary (space or newline)
                                    word_break = -1
                                    for i in range(ideal_end, search_start - 1, -1):
                                        if text[i] in " \n\t":
                                            word_break = i
                                            break

                                    if word_break > search_start:
                                        end_pos = word_break
                                    else:
                                        # If no good break found, look forward instead
                                        forward_search_end = min(
                                            len(text), ideal_end + 100
                                        )
                                        word_break = text.find(
                                            " ", ideal_end, forward_search_end
                                        )
                                        if word_break == -1:
                                            word_break = text.find(
                                                "\n", ideal_end, forward_search_end
                                            )

                                        end_pos = (
                                            word_break
                                            if word_break != -1
                                            else ideal_end
                                        )

                                page_text = text[current_pos:end_pos].strip()
                                current_pos = end_pos

                        # Skip empty pages
                        if page_text:
                            DocumentPage.objects.create(
                                extraction=extraction,
                                page_number=page_num,
                                raw_text=page_text,
                                character_count=len(page_text),
                            )

                    logger.info(
                        f"Split text into {page_count} pages for {extraction.decision.ada}"
                    )

            return True

        except Exception as e:
            logger.error(f"Text splitting failed for {extraction.decision.ada}: {e}")
            return False
