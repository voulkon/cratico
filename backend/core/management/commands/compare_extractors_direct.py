import json
import os
import time

from core.models.decisions import Decision
from core.services.document_processor import BaseDocumentProcessor
from core.services.extractors.docling import DoclingExtractor
from core.services.extractors.pymupdf import PyMuPDFExtractor
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Directly compare extractors on the same document PDF (more efficient)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ada",
            type=str,
            required=True,
            help="Decision ADA to compare extractors on",
        )
        parser.add_argument(
            "--no-chunks",
            action="store_true",
            help="Don't use Docling's chunking, just extract full text",
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Save the extraction results to JSON file",
        )

    def handle(self, *args, **options):
        ada = options["ada"]
        no_chunks = options.get("no_chunks", False)
        output_file = options.get("output_file")

        try:
            decision = Decision.objects.get(ada=ada)
        except Decision.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Decision with ADA {ada} not found"))
            return

        self.stdout.write(f"Comparing extractors for decision: {decision.ada}")
        self.stdout.write(f"Title: {decision.subject}")
        self.stdout.write(f"URL: {decision.document_url}")

        # Download the PDF once
        downloader = BaseDocumentProcessor()
        temp_path, success = downloader.download_pdf(decision.document_url)

        if not success or not temp_path:
            self.stdout.write(
                self.style.ERROR(f"Failed to download PDF for {decision.ada}")
            )
            return

        self.stdout.write(self.style.SUCCESS(f"Downloaded PDF to {temp_path}"))

        try:
            # Initialize extractors
            pymupdf_extractor = PyMuPDFExtractor()
            docling_extractor = DoclingExtractor(split_into_pages=not no_chunks)

            # Extract with PyMuPDF
            self.stdout.write("\nRunning PyMuPDF extractor...")
            start_time = time.time()
            pymupdf_result = pymupdf_extractor.extract_text(temp_path)
            pymupdf_time_ms = int((time.time() - start_time) * 1000)

            # Extract with Docling
            self.stdout.write("\nRunning Docling extractor...")
            start_time = time.time()
            docling_result = docling_extractor.extract_text(temp_path)
            docling_time_ms = int((time.time() - start_time) * 1000)

            # Display results
            self._display_extractor_result("PyMuPDF", pymupdf_result, pymupdf_time_ms)
            self._display_extractor_result("Docling", docling_result, docling_time_ms)

            # Compare text content
            self._compare_text_content(pymupdf_result.text, docling_result.text)

            # Save to file if requested
            if output_file:
                self._save_results(
                    decision.ada,
                    {
                        "decision_info": {
                            "ada": decision.ada,
                            "title": decision.subject,
                            "url": decision.document_url,
                        },
                        "pymupdf": {
                            "text": pymupdf_result.text,
                            "page_count": pymupdf_result.page_count,
                            "time_ms": pymupdf_time_ms,
                            "pages": (
                                pymupdf_result.pages_data
                                if hasattr(pymupdf_result, "pages_data")
                                else None
                            ),
                        },
                        "docling": {
                            "text": docling_result.text,
                            "page_count": docling_result.page_count,
                            "time_ms": docling_time_ms,
                            "pages": (
                                docling_result.pages_data
                                if hasattr(docling_result, "pages_data")
                                else None
                            ),
                            "metadata": docling_result.metadata,
                        },
                    },
                    output_file,
                )

        finally:
            # Clean up temp file
            downloader.cleanup_temp_file(temp_path)

    def _display_extractor_result(self, name, result, time_ms):
        """Display the results from a single extractor"""
        self.stdout.write(self.style.SUCCESS(f"\n=== {name} Results ==="))
        self.stdout.write(f"Time taken: {time_ms}ms")
        self.stdout.write(f"Page count: {result.page_count}")
        self.stdout.write(f"Text length: {len(result.text)} chars")
        self.stdout.write(f"Is scanned: {result.is_scanned}")

        # Show page details if available
        if hasattr(result, "pages_data") and result.pages_data:
            self.stdout.write(f"Pages/chunks extracted: {len(result.pages_data)}")
            for i, page in enumerate(result.pages_data[:3]):  # Show first 3 pages
                self.stdout.write(
                    f"  Page {page['page_number']} ({page['character_count']} chars)"
                )
                preview = (
                    page["text"][:100].replace("\n", " ") + "..."
                    if page["text"]
                    else "(empty)"
                )
                self.stdout.write(f"  Preview: {preview}")

            if len(result.pages_data) > 3:
                self.stdout.write(
                    f"  ... plus {len(result.pages_data) - 3} more pages/chunks"
                )

        # Show text sample
        if result.text:
            self.stdout.write("\nText sample (first 300 chars):")
            self.stdout.write(result.text[:300].replace("\n", " ") + "...")
        else:
            self.stdout.write("No text extracted")

    def _compare_text_content(self, text1, text2):
        """Compare the text content from the two extractors"""
        self.stdout.write(self.style.SUCCESS("\n=== Text Comparison ==="))

        # Basic comparison
        length1 = len(text1)
        length2 = len(text2)
        length_diff = abs(length1 - length2)
        length_diff_percent = (
            int((length_diff / max(length1, length2)) * 100)
            if max(length1, length2) > 0
            else 0
        )

        self.stdout.write(f"PyMuPDF: {length1} chars")
        self.stdout.write(f"Docling: {length2} chars")
        self.stdout.write(f"Difference: {length_diff} chars ({length_diff_percent}%)")

        # Line count comparison
        lines1 = text1.splitlines()
        lines2 = text2.splitlines()
        self.stdout.write(f"PyMuPDF: {len(lines1)} lines")
        self.stdout.write(f"Docling: {len(lines2)} lines")

        # Word count comparison
        words1 = text1.split()
        words2 = text2.split()
        self.stdout.write(f"PyMuPDF: {len(words1)} words")
        self.stdout.write(f"Docling: {len(words2)} words")

    def _save_results(self, ada, results, output_file):
        """Save extraction results to a JSON file"""
        # Ensure directory exists
        os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(f"\nResults saved to {output_file}"))
