"""
# Start with a test run on smaller parameters
python manage.py analyze_text_statistics_efficient \
    --batch-size 25 \
    --temp-db-size 500 \
    --min-occurrence 3 \
    --top-n 1000

# Or go full scale
python manage.py analyze_text_statistics_efficient \
    --batch-size 50 \
    --temp-db-size 1000 \
    --min-occurrence 5 \
    --top-n 2000 \
    --output-dir "greek_text_analysis_$(date +%Y%m%d)"
"""

import csv
import json
import os
import re
import sqlite3
import tempfile
import time  # Add this import
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List

from core.models.document_analysis import DocumentExtraction
from core.services.text_preprocessor import TextPreprocessor  # Add this import
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Memory-efficient analysis of word, bi-gram, and tri-gram statistics"

    # Whitelist of allowed table names for n-gram types
    VALID_NGRAM_TYPES = {"words", "bigrams", "trigrams"}

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            default="text_analysis_results",
            help="Directory to save analysis results",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=50,  # Smaller batch size
            help="Number of documents to process at once",
        )
        parser.add_argument(
            "--temp-db-size",
            type=int,
            default=1000,  # Flush to temp DB every N documents
            help="Number of documents to process before flushing to temp storage",
        )
        parser.add_argument(
            "--min-occurrence",
            type=int,
            default=3,
            help="Minimum occurrences to include in final results",
        )
        parser.add_argument(
            "--top-n",
            type=int,
            default=1000,
            help="Number of top items to include in reports",
        )

    def _validate_and_quote_table(self, table_name: str) -> str:
        """Validate table name against whitelist and quote it for SQLite.

        This prevents SQL injection by ensuring only whitelisted table names
        are used in SQL queries.
        """
        if table_name not in self.VALID_NGRAM_TYPES:
            raise ValueError(f"Invalid table name: {table_name}")
        # SQLite uses double quotes for identifiers
        return f'"{table_name}"'

    def handle(self, *args, **options):
        self.options = options
        self.setup_directories(options["output_dir"])

        # Create temporary SQLite database for intermediate storage
        self.temp_db_path = self.create_temp_database()

        try:
            total_docs = self.get_total_document_count()
            if total_docs == 0:
                self.stdout.write(self.style.ERROR("No documents found."))
                return

            self.stdout.write(
                f"[SCAN] Analyzing {total_docs} documents with memory-efficient processing..."
            )

            # Process documents in memory-conscious batches
            self.process_documents_streaming(total_docs)

            # Generate final statistics from temp database
            self.generate_final_reports(total_docs)

            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] Analysis complete! Results in: {self.output_dir}"
                )
            )

        finally:
            # Cleanup temp database
            if os.path.exists(self.temp_db_path):
                os.unlink(self.temp_db_path)

    def setup_directories(self, output_dir: str):
        """Create output directories."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        (self.output_dir / "csv").mkdir(exist_ok=True)
        (self.output_dir / "json").mkdir(exist_ok=True)
        (self.output_dir / "reports").mkdir(exist_ok=True)

    def create_temp_database(self) -> str:
        """Create temporary SQLite database for intermediate storage."""
        temp_dir = tempfile.gettempdir()
        temp_db_path = os.path.join(temp_dir, f"text_analysis_{os.getpid()}.db")

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # Create tables for each n-gram type
        for ngram_type in ["words", "bigrams", "trigrams"]:
            quoted_table = self._validate_and_quote_table(ngram_type)
            cursor.execute(
                f"""
                CREATE TABLE {quoted_table} (
                    item TEXT PRIMARY KEY,
                    total_count INTEGER DEFAULT 0,
                    doc_count INTEGER DEFAULT 0,
                    doc_ids TEXT DEFAULT ''
                )
            """
            )

            # Create index for faster lookups
            cursor.execute(
                f"CREATE INDEX idx_{ngram_type}_item ON {quoted_table}(item)"
            )

        conn.commit()
        conn.close()

        self.stdout.write(f"[DIR] Created temporary database: {temp_db_path}")
        return temp_db_path

    def get_total_document_count(self) -> int:
        """Get count of documents with text content."""
        return (
            DocumentExtraction.objects.exclude(raw_text__isnull=True)
            .exclude(raw_text="")
            .count()
        )

    def extract_greek_words(self, text: str) -> List[str]:
        """Extract Greek words from text."""
        if not text:
            return []
        words = re.findall(r"[Α-ΩΆΈΉΊΌΎΏΪΫα-ωάέήίόύώϊϋΐΰ]+", text.lower())
        return [word for word in words if len(word) >= 2]

    def generate_ngrams(self, words: List[str]) -> Dict[str, List[str]]:
        """Generate n-grams from word list."""
        result = {"words": words, "bigrams": [], "trigrams": []}

        if len(words) >= 2:
            result["bigrams"] = [
                f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)
            ]

        if len(words) >= 3:
            result["trigrams"] = [
                f"{words[i]} {words[i+1]} {words[i+2]}" for i in range(len(words) - 2)
            ]

        return result

    def process_documents_streaming(self, total_docs: int):
        """Process documents in memory-efficient streaming fashion."""
        batch_size = self.options["batch_size"]
        temp_flush_size = self.options["temp_db_size"]

        # In-memory counters for current batch
        current_batch_data = {
            "words": defaultdict(lambda: {"count": 0, "docs": set()}),
            "bigrams": defaultdict(lambda: {"count": 0, "docs": set()}),
            "trigrams": defaultdict(lambda: {"count": 0, "docs": set()}),
        }

        processed_count = 0
        docs_since_flush = 0

        # Process documents in small batches
        queryset = (
            DocumentExtraction.objects.exclude(raw_text__isnull=True)
            .exclude(raw_text="")
            .only("id", "raw_text")
        )

        for i in range(0, total_docs, batch_size):
            batch = list(
                queryset[i : i + batch_size]
            )  # Convert to list to avoid re-querying

            for extraction in batch:
                self.process_single_document_efficient(
                    extraction, current_batch_data, processed_count + 1
                )
                processed_count += 1
                docs_since_flush += 1

                # Flush to temp database periodically to free memory
                if docs_since_flush >= temp_flush_size:
                    self.flush_to_temp_database(current_batch_data)
                    current_batch_data = self.reset_batch_data()
                    docs_since_flush = 0
                    self.stdout.write(
                        f"[SAVE] Flushed to temp DB. Processed {processed_count}/{total_docs}"
                    )

            # Progress update
            if processed_count % (batch_size * 10) == 0:
                self.stdout.write(
                    f"[CHART] Processed {processed_count}/{total_docs} documents..."
                )

        # Final flush
        if docs_since_flush > 0:
            self.flush_to_temp_database(current_batch_data)
            self.stdout.write(
                f"[SAVE] Final flush completed. Total processed: {processed_count}"
            )

    def reset_batch_data(self):
        """Reset batch data structure."""
        return {
            "words": defaultdict(lambda: {"count": 0, "docs": set()}),
            "bigrams": defaultdict(lambda: {"count": 0, "docs": set()}),
            "trigrams": defaultdict(lambda: {"count": 0, "docs": set()}),
        }

    def process_single_document_efficient(
        self, extraction, batch_data: Dict, doc_id: int
    ):
        """Process a single document and update batch data."""
        words = self.extract_greek_words(extraction.raw_text)
        if not words:
            return

        ngrams = self.generate_ngrams(words)

        for ngram_type, items in ngrams.items():
            # Count total occurrences
            item_counts = Counter(items)

            # Update batch data
            for item, count in item_counts.items():
                batch_data[ngram_type][item]["count"] += count
                batch_data[ngram_type][item]["docs"].add(doc_id)

    def flush_to_temp_database(self, batch_data: Dict):
        """Flush current batch data to temporary SQLite database."""
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        for ngram_type, items in batch_data.items():
            quoted_table = self._validate_and_quote_table(ngram_type)
            for item, data in items.items():
                total_count = data["count"]
                doc_count = len(data["docs"])
                doc_ids = ",".join(map(str, sorted(data["docs"])))

                # Check if item already exists
                cursor.execute(
                    f"SELECT total_count, doc_count, doc_ids FROM {quoted_table} WHERE item = ?",
                    (item,),  # nosec: B608 - Table name validated against whitelist
                )
                existing = cursor.fetchone()

                if existing:
                    # Merge with existing data
                    existing_total, existing_doc_count, existing_doc_ids = existing
                    new_total = existing_total + total_count

                    # Merge document IDs (avoid duplicates)
                    existing_docs = (
                        set(existing_doc_ids.split(",")) if existing_doc_ids else set()
                    )
                    new_docs = set(map(str, data["docs"]))
                    all_docs = existing_docs | new_docs
                    all_docs.discard("")  # Remove empty strings
                    merged_doc_ids = ",".join(sorted(all_docs, key=int))
                    new_doc_count = len(all_docs)

                    cursor.execute(
                        f"""
                        UPDATE {quoted_table}
                        SET total_count = ?, doc_count = ?, doc_ids = ?
                        WHERE item = ?
                    """,
                        (
                            new_total,
                            new_doc_count,
                            merged_doc_ids,
                            item,
                        ),  # nosec: B608 - Table name validated against whitelist
                    )
                else:
                    # Insert new item
                    cursor.execute(
                        f"""
                        INSERT INTO {quoted_table} (item, total_count, doc_count, doc_ids)
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            item,
                            total_count,
                            doc_count,
                            doc_ids,
                        ),  # nosec: B608 - Table name validated against whitelist
                    )

        conn.commit()
        conn.close()

    def generate_final_reports(self, total_docs: int):
        """Generate final reports from temporary database."""
        self.stdout.write(
            "[METRIC] Generating final statistics from temporary database..."
        )

        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        stats = {}
        min_occurrence = self.options["min_occurrence"]
        top_n = self.options["top_n"]

        for ngram_type in ["words", "bigrams", "trigrams"]:
            quoted_table = self._validate_and_quote_table(ngram_type)
            # Get filtered and sorted data
            cursor.execute(
                f"""
                SELECT item, total_count, doc_count
                FROM {quoted_table}
                WHERE total_count >= ?
                ORDER BY total_count DESC
                LIMIT ?
            """,
                (
                    min_occurrence,
                    top_n,
                ),  # nosec: B608 - Table name validated against whitelist
            )

            results = cursor.fetchall()

            # Calculate statistics
            type_stats = []
            for rank, (item, total_count, doc_count) in enumerate(results, 1):
                doc_percentage = (doc_count / total_docs) * 100
                avg_per_doc = total_count / doc_count if doc_count > 0 else 0

                type_stats.append(
                    {
                        "item": item,
                        "total_occurrences": total_count,
                        "document_count": doc_count,
                        "document_percentage": round(doc_percentage, 2),
                        "avg_occurrences_per_doc": round(avg_per_doc, 2),
                        "frequency_rank": rank,
                    }
                )

            # Get total unique items count
            cursor.execute(
                f"SELECT COUNT(*) FROM {quoted_table} WHERE total_count >= ?",
                (
                    min_occurrence,
                ),  # nosec: B608 - Table name validated against whitelist
            )
            total_unique = cursor.fetchone()[0]

            # Get total occurrences
            cursor.execute(
                f"SELECT SUM(total_count) FROM {quoted_table} WHERE total_count >= ?",
                (
                    min_occurrence,
                ),  # nosec: B608 - Table name validated against whitelist
            )
            total_occurrences = cursor.fetchone()[0] or 0

            stats[ngram_type] = {
                "total_unique_items": total_unique,
                "total_occurrences": total_occurrences,
                "items": type_stats,
            }

        conn.close()

        # Generate all reports using the same methods as before
        self.generate_summary_report(stats, total_docs, total_docs)
        self.generate_csv_reports(stats)
        self.generate_json_reports(stats)
        self.generate_high_frequency_analysis(stats, total_docs)

    # Include the same report generation methods from the previous command
    # (generate_summary_report, generate_csv_reports, etc.)
    # ... [Previous report generation methods here]

    # Add all the missing report generation methods:
    def generate_summary_report(
        self, stats: Dict, processed_docs: int, total_docs: int
    ):
        """Generate a human-readable summary report."""
        report_path = self.output_dir / "reports" / "summary_report.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[CHART] TEXT ANALYSIS SUMMARY REPORT (Memory-Efficient)\n")
            f.write("=" * 55 + "\n\n")

            f.write(f"Documents processed: {processed_docs:,}\n")
            f.write(f"Total documents: {total_docs:,}\n")
            f.write(f"Batch size: {self.options['batch_size']}\n")
            f.write(f"Temp DB flush size: {self.options['temp_db_size']}\n")
            f.write(f"Minimum occurrences: {self.options['min_occurrence']}\n\n")

            # Overview statistics
            for ngram_type in ["words", "bigrams", "trigrams"]:
                type_stats = stats[ngram_type]
                f.write(f"{ngram_type.upper()} STATISTICS:\n")
                f.write(
                    f"  Unique {ngram_type}: {type_stats['total_unique_items']:,}\n"
                )
                f.write(f"  Total occurrences: {type_stats['total_occurrences']:,}\n")

                if type_stats["items"]:
                    top_item = type_stats["items"][0]
                    f.write(
                        f"  Most frequent: '{top_item['item']}' ({top_item['total_occurrences']:,} times)\n"
                    )
                f.write("\n")

            # Top items summary
            f.write("[FATAL] TOP 20 MOST FREQUENT ITEMS BY CATEGORY:\n")
            f.write("=" * 50 + "\n\n")

            for ngram_type in ["words", "bigrams", "trigrams"]:
                f.write(f"{ngram_type.upper()}:\n")
                f.write("-" * 30 + "\n")

                for i, item in enumerate(stats[ngram_type]["items"][:20], 1):
                    f.write(
                        f"{i:2d}. {item['item']:<25} | {item['total_occurrences']:>6,} times | {item['document_percentage']:>5.1f}% docs\n"
                    )
                f.write("\n")

    def generate_csv_reports(self, stats: Dict):
        """Generate detailed CSV files for each n-gram type."""
        for ngram_type in ["words", "bigrams", "trigrams"]:
            csv_path = self.output_dir / "csv" / f"{ngram_type}_analysis.csv"

            with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
                fieldnames = [
                    "rank",
                    "item",
                    "total_occurrences",
                    "document_count",
                    "document_percentage",
                    "avg_occurrences_per_doc",
                ]
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                writer.writeheader()
                for item_stat in stats[ngram_type]["items"]:
                    writer.writerow(
                        {
                            "rank": item_stat["frequency_rank"],
                            "item": item_stat["item"],
                            "total_occurrences": item_stat["total_occurrences"],
                            "document_count": item_stat["document_count"],
                            "document_percentage": item_stat["document_percentage"],
                            "avg_occurrences_per_doc": item_stat[
                                "avg_occurrences_per_doc"
                            ],
                        }
                    )

    def generate_json_reports(self, stats: Dict):
        """Generate JSON files with complete data."""
        # Complete statistics
        json_path = self.output_dir / "json" / "complete_analysis.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)

        # Separate files for each type
        for ngram_type in ["words", "bigrams", "trigrams"]:
            type_path = self.output_dir / "json" / f"{ngram_type}_data.json"
            with open(type_path, "w", encoding="utf-8") as f:
                json.dump(stats[ngram_type], f, ensure_ascii=False, indent=2)

    def generate_high_frequency_analysis(self, stats: Dict, total_docs: int):
        """Generate analysis of items that appear in high percentage of documents."""
        report_path = self.output_dir / "reports" / "high_frequency_candidates.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[TARGET] HIGH-FREQUENCY STOPWORD CANDIDATES\n")
            f.write("=" * 50 + "\n\n")

            f.write(
                "Items that appear in a high percentage of documents are potential stopword candidates.\n"
            )
            f.write(
                "Review these carefully as they might not add much value for search/analysis.\n\n"
            )

            # Different thresholds for analysis
            thresholds = [95, 90, 80, 70, 60, 50]

            for threshold in thresholds:
                f.write(f"[METRIC] ITEMS APPEARING IN >{threshold}% OF DOCUMENTS:\n")
                f.write("-" * 40 + "\n")

                found_any = False
                for ngram_type in ["words", "bigrams", "trigrams"]:
                    candidates = [
                        item
                        for item in stats[ngram_type]["items"]
                        if item["document_percentage"] > threshold
                    ]

                    if candidates:
                        found_any = True
                        f.write(f"\n{ngram_type.capitalize()}:\n")
                        for item in candidates:
                            f.write(
                                f"  • {item['item']:<30} | {item['document_percentage']:>5.1f}% | {item['total_occurrences']:>6,} times\n"
                            )

                if not found_any:
                    f.write("  (No items found at this threshold)\n")
                f.write("\n")

    def generate_stopwords_comparison(self, stats: Dict, total_docs: int):
        """Compare findings with existing stopwords in TextPreprocessor."""
        report_path = self.output_dir / "reports" / "stopwords_comparison.txt"

        # Get existing stopwords
        preprocessor = TextPreprocessor()
        existing_stopwords = set()
        for stopword in preprocessor.greek_stopwords:
            # Add both original and lowercase versions
            existing_stopwords.add(stopword.lower())
            # Also add individual words from multi-word stopwords
            words = stopword.lower().split()
            existing_stopwords.update(words)

        # Add common words
        existing_stopwords.update(preprocessor.common_greek_words)

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[SCAN] STOPWORDS COMPARISON ANALYSIS\n")
            f.write("=" * 50 + "\n\n")

            # Analyze how well current stopwords cover high-frequency words
            word_items = stats["words"]["items"]

            already_covered = []
            new_candidates = []

            for word_stat in word_items[:100]:
                word = word_stat["item"]
                if word in existing_stopwords:
                    already_covered.append(word_stat)
                else:
                    new_candidates.append(word_stat)

            f.write(f"ANALYSIS OF TOP 100 MOST FREQUENT WORDS:\n")
            f.write(
                f"Already covered by existing stopwords: {len(already_covered)}/100\n"
            )
            f.write(f"New potential candidates: {len(new_candidates)}/100\n\n")

            f.write("[OK] ALREADY COVERED (Top 20):\n")
            f.write("-" * 30 + "\n")
            for item in already_covered[:20]:
                f.write(
                    f"  {item['item']:<20} | {item['document_percentage']:>5.1f}% | {item['total_occurrences']:>6,} times\n"
                )

            f.write(f"\n🆕 NEW CANDIDATES (Top 30):\n")
            f.write("-" * 30 + "\n")
            for item in new_candidates[:30]:
                f.write(
                    f"  {item['item']:<20} | {item['document_percentage']:>5.1f}% | {item['total_occurrences']:>6,} times\n"
                )

            # Generate suggested code
            f.write(f"\n[CLIENT] SUGGESTED ADDITIONS TO TextPreprocessor:\n")
            f.write("=" * 50 + "\n")
            f.write(
                "# Add these to self.greek_stopwords or self.common_greek_words:\n\n"
            )

            high_freq_candidates = [
                item["item"]
                for item in new_candidates[:20]
                if item["document_percentage"] > 60  # Only very high frequency
            ]

            if high_freq_candidates:
                f.write("high_frequency_stopwords = {\n")
                for word in high_freq_candidates:
                    doc_pct = next(
                        item["document_percentage"]
                        for item in new_candidates
                        if item["item"] == word
                    )
                    f.write(f'    "{word.upper()}",  # {doc_pct:.1f}% of documents\n')
                f.write("}\n")
                f.write("self.greek_stopwords.update(high_frequency_stopwords)\n")
