import os
import random
import shutil

from core.models.decisions import Decision
from core.models.document_analysis import ExtractorComparison
from core.services.document_processor import BaseDocumentProcessor
from core.services.extractors.docling import DoclingExtractor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compare PYMUPDF vs DOCLING extractors side by side"

    def __init__(self):
        super().__init__()
        self.processor = BaseDocumentProcessor()
        self.pymupdf_extractor = PyMuPDFExtractor()
        self.docling_extractor = DoclingExtractor()

    def add_arguments(self, parser):
        parser.add_argument(
            "--sample-size", type=int, default=5, help="Number of decisions to compare"
        )
        parser.add_argument(
            "--ada",
            action="append",
            help="Specific ADA(s) to compare (can be specified multiple times)",
        )
        parser.add_argument(
            "--pdf-dir",
            type=str,
            default="/tmp/extractor_comparison_pdfs",
            help="Directory to store PDFs for inspection",
        )

    def handle(self, *args, **options):
        sample_size = options.get("sample_size")
        specific_adas = options.get("ada")
        pdf_dir = options.get("pdf_dir")

        # Create PDF storage directory
        os.makedirs(pdf_dir, exist_ok=True)
        self.stdout.write(f"PDFs will be stored in: {pdf_dir}")

        # Get decisions to compare
        if specific_adas:
            decisions = Decision.objects.filter(ada__in=specific_adas)
            self.stdout.write(f"Comparing specific ADAs: {specific_adas}")
        else:
            # Get decisions that have document URLs but no comparison yet
            decisions = Decision.objects.filter(document_url__isnull=False).exclude(
                extractor_comparisons__isnull=False
            )

            total_available = decisions.count()
            self.stdout.write(f"Found {total_available} decisions with document URLs")

            if sample_size and total_available > sample_size:
                decision_ids = list(decisions.values_list("id", flat=True))
                sampled_ids = random.sample(decision_ids, sample_size)
                decisions = Decision.objects.filter(id__in=sampled_ids)

        final_count = decisions.count()
        self.stdout.write(f"Will compare {final_count} decisions")

        if final_count == 0:
            self.stdout.write("No decisions to compare")
            return

        # Process each decision
        success_count = 0
        error_count = 0

        for i, decision in enumerate(decisions, 1):
            try:
                self.stdout.write(
                    f"\n--- Processing {i}/{final_count}: {decision.ada} ---"
                )

                # Download PDF
                temp_path, download_success = self.processor.download_pdf(
                    decision.document_url
                )
                if not download_success:
                    self.stdout.write(
                        f"[ERROR] Failed to download PDF for {decision.ada}"
                    )
                    error_count += 1
                    continue

                # Copy PDF to permanent location for inspection
                pdf_filename = f"{decision.ada}.pdf"
                permanent_pdf_path = os.path.join(pdf_dir, pdf_filename)
                shutil.copy2(
                    temp_path, permanent_pdf_path
                )  # nosec: B108 - Controlled paths from command-line and download
                self.stdout.write(f"[FILE] PDF saved: {permanent_pdf_path}")

                # Extract with PYMUPDF
                self.stdout.write("[CONFIG] Extracting with PYMUPDF...")
                try:
                    pymupdf_result = self.pymupdf_extractor.extract_text(temp_path)
                    text_before = pymupdf_result.text
                    self.stdout.write(f"[OK] PYMUPDF: {len(text_before)} characters")
                except Exception as e:
                    self.stdout.write(f"[ERROR] PYMUPDF failed: {e}")
                    text_before = f"ERROR: {str(e)}"

                # Extract with DOCLING
                self.stdout.write("[CONFIG] Extracting with DOCLING...")
                try:
                    docling_result = self.docling_extractor.extract_text(temp_path)
                    text_after = docling_result.text
                    self.stdout.write(f"[OK] DOCLING: {len(text_after)} characters")
                except Exception as e:
                    self.stdout.write(f"[ERROR] DOCLING failed: {e}")
                    text_after = f"ERROR: {str(e)}"

                # Calculate stats
                chars_before = len(text_before) if text_before else 0
                chars_after = len(text_after) if text_after else 0
                chars_diff = chars_after - chars_before

                # Store comparison
                comparison, created = ExtractorComparison.objects.get_or_create(
                    decision=decision,
                    defaults={
                        "text_before": text_before,
                        "text_after": text_after,
                        "chars_before": chars_before,
                        "chars_after": chars_after,
                        "chars_diff": chars_diff,
                        "pdf_path": permanent_pdf_path,
                    },
                )

                if created:
                    self.stdout.write(
                        f"[SAVE] Stored comparison: PYMUPDF={chars_before} chars, "
                        f"DOCLING={chars_after} chars, diff={chars_diff:+d}"
                    )
                    success_count += 1
                else:
                    self.stdout.write("ℹ️ Comparison already exists")

                # Clean up temp file
                self.processor.cleanup_temp_file(temp_path)

            except Exception as e:
                self.stdout.write(f"[ERROR] Error processing {decision.ada}: {str(e)}")
                error_count += 1

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("COMPARISON COMPLETE")
        self.stdout.write("=" * 60)
        self.stdout.write(f"Success: {success_count}")
        self.stdout.write(f"Errors: {error_count}")
        self.stdout.write(f"PDFs stored in: {pdf_dir}")

        # Show some stats
        self.show_quick_stats()

    def show_quick_stats(self):
        """Show quick comparison statistics"""
        comparisons = ExtractorComparison.objects.all()
        count = comparisons.count()

        if count == 0:
            return

        self.stdout.write(f"\n[CHART] QUICK STATS ({count} comparisons):")

        # Character differences
        diffs = [c.chars_diff for c in comparisons if c.chars_diff is not None]
        if diffs:
            avg_diff = sum(diffs) / len(diffs)
            self.stdout.write(f"Average char difference: {avg_diff:.1f}")
            self.stdout.write(f"Max difference: {max(diffs):+d}")
            self.stdout.write(f"Min difference: {min(diffs):+d}")

        # Show a few examples
        self.stdout.write(f"\n[NOTE] SAMPLE RESULTS:")
        for comp in comparisons[:3]:
            self.stdout.write(
                f"  {comp.decision.ada}: "
                f"PYMUPDF={comp.chars_before or 0}, "
                f"DOCLING={comp.chars_after or 0}, "
                f"diff={comp.chars_diff or 0:+d}"
            )
