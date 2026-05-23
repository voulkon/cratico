"""
# Small test to make sure everything works
python manage.py explore_afm_patterns \
    --batch-size 50 \
    --temp-db-flush-size 200 \
    --sample-size 10 \
    --progress-interval 500

# Full-scale analysis on all your decisions
python manage.py explore_afm_patterns \
    --batch-size 100 \
    --temp-db-flush-size 500 \
    --sample-size 50 \
    --progress-interval 1000 \
    --output-dir "afm_analysis_$(date +%Y%m%d_%H%M)"

# Optimized for maximum performance
python manage.py explore_afm_patterns \
    --batch-size 200 \
    --temp-db-flush-size 1000 \
    --sample-size 30 \
    --progress-interval 2000 \
    --output-dir "afm_patterns_full_analysis"
"""

import json
import os
import sqlite3
import tempfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from core.models.decisions import Decision
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Explore AFM patterns in ALL Decision extra_field_values_json entries (with temp DB)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--output-dir",
            type=str,
            default="afm_analysis_results",
            help="Directory to save analysis results",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of decisions to process at once",
        )
        parser.add_argument(
            "--temp-db-flush-size",
            type=int,
            default=500,
            help="Number of patterns to accumulate before flushing to temp DB",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=50,
            help="Number of examples to save per pattern",
        )
        parser.add_argument(
            "--progress-interval",
            type=int,
            default=1000,
            help="How often to show progress updates",
        )
        parser.add_argument(
            "--debug-afm",
            action="store_true",
            help="Enable debug output for AFM detection",
        )

    def handle(self, *args, **options):
        self.options = options
        self.debug_afm = options.get("debug_afm", False)
        self.setup_directories(options["output_dir"])

        # Create temporary SQLite database for pattern storage
        self.temp_db_path = self.create_temp_database()

        # In-memory counters for current batch (periodically flushed)
        self.reset_batch_counters()

        try:
            total_decisions = self.get_total_decision_count()
            if total_decisions == 0:
                self.stdout.write(
                    self.style.ERROR("No decisions with extra_field_values_json found.")
                )
                return

            self.stdout.write(
                f"[SCAN] Exploring AFM patterns in ALL {total_decisions:,} decisions..."
            )
            self.stdout.write(f"[DIR] Using temporary database: {self.temp_db_path}")

            if self.debug_afm:
                self.stdout.write(
                    "[BUG] Debug mode enabled - will show first few AFM detections"
                )

            processed_count = self.process_all_decisions(total_decisions)

            # Final flush
            self.flush_to_temp_database()

            # Generate reports from temp database
            self.generate_comprehensive_reports_from_db(processed_count)

            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] AFM pattern exploration complete! Results in: {self.output_dir}"
                )
            )

        finally:
            # Cleanup temp database
            if os.path.exists(self.temp_db_path):
                os.unlink(self.temp_db_path)
                self.stdout.write(f"[PURGE]️ Cleaned up temporary database")

    def setup_directories(self, output_dir: str):
        """Create output directories."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def create_temp_database(self) -> str:
        """Create temporary SQLite database for pattern storage."""
        temp_dir = tempfile.gettempdir()
        temp_db_path = os.path.join(temp_dir, f"afm_patterns_{os.getpid()}.db")

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # Table for parent key statistics
        cursor.execute(
            """
            CREATE TABLE parent_key_stats (
                parent_key TEXT PRIMARY KEY,
                total_count INTEGER DEFAULT 0,
                unique_afm_count INTEGER DEFAULT 0
            )
        """
        )

        # Table for inner key patterns
        cursor.execute(
            """
            CREATE TABLE inner_key_patterns (
                parent_key TEXT,
                inner_key TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (parent_key, inner_key)
            )
        """
        )

        # Table for AFM field name variations
        cursor.execute(
            """
            CREATE TABLE afm_field_names (
                field_name TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """
        )

        # Table for AFM values by parent
        cursor.execute(
            """
            CREATE TABLE afm_values (
                parent_key TEXT,
                afm_value TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (parent_key, afm_value)
            )
        """
        )

        # Table for AFM length distribution
        cursor.execute(
            """
            CREATE TABLE afm_length_distribution (
                length INTEGER PRIMARY KEY,
                count INTEGER DEFAULT 0
            )
        """
        )

        # Table for structure examples
        cursor.execute(
            """
            CREATE TABLE structure_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_key TEXT,
                decision_ada TEXT,
                afm_fields TEXT,  -- JSON array of AFM field names
                raw_data TEXT,    -- JSON of complete structure
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Table for decision-level statistics
        cursor.execute(
            """
            CREATE TABLE decision_stats (
                decision_ada TEXT PRIMARY KEY,
                afm_count INTEGER DEFAULT 0,
                parent_keys TEXT  -- JSON array of parent keys found
            )
        """
        )

        # Create indexes for better performance
        cursor.execute(
            "CREATE INDEX idx_inner_key_parent ON inner_key_patterns(parent_key)"
        )
        cursor.execute("CREATE INDEX idx_afm_values_parent ON afm_values(parent_key)")
        cursor.execute(
            "CREATE INDEX idx_examples_parent ON structure_examples(parent_key)"
        )

        conn.commit()
        conn.close()

        self.stdout.write(f"[DIR] Created temporary database: {temp_db_path}")
        return temp_db_path

    def reset_batch_counters(self):
        """Reset in-memory batch counters."""
        self.batch_parent_key_stats = Counter()
        self.batch_inner_key_patterns = defaultdict(lambda: defaultdict(int))
        self.batch_afm_field_names = Counter()
        self.batch_afm_values = defaultdict(set)
        self.batch_afm_length_distribution = Counter()
        self.batch_structure_examples = defaultdict(list)
        self.batch_decision_stats = {}
        self.patterns_since_flush = 0
        self.debug_count = 0  # For debug output

    def get_total_decision_count(self) -> int:
        """Get count of ALL decisions with extra_field_values_json data."""
        count = (
            Decision.objects.exclude(extra_field_values_json__isnull=True)
            .exclude(extra_field_values_json={})
            .count()
        )

        self.stdout.write(
            f"[COPY] Found {count:,} decisions with extra_field_values_json data"
        )
        return count

    def process_all_decisions(self, total_decisions: int) -> int:
        """Process ALL decisions to find AFM patterns."""
        batch_size = self.options["batch_size"]
        progress_interval = self.options["progress_interval"]
        flush_size = self.options["temp_db_flush_size"]
        processed_count = 0

        queryset = (
            Decision.objects.exclude(extra_field_values_json__isnull=True)
            .exclude(extra_field_values_json={})
            .only("ada", "extra_field_values_json")
        )

        self.stdout.write(
            "[LAUNCH] Starting AFM pattern analysis with database storage..."
        )

        for i in range(0, total_decisions, batch_size):
            batch = list(queryset[i : i + batch_size])

            for decision in batch:
                self.analyze_decision_afm_patterns(decision)
                processed_count += 1

                # Check if we need to flush to database
                if self.patterns_since_flush >= flush_size:
                    self.flush_to_temp_database()
                    self.reset_batch_counters()

                # Progress updates
                if processed_count % progress_interval == 0:
                    self.show_progress(processed_count, total_decisions)

            # Clear the batch from memory
            del batch

        self.stdout.write(
            f"[TARGET] Completed processing {processed_count:,} decisions"
        )
        return processed_count

    def analyze_decision_afm_patterns(self, decision: Decision) -> int:
        """Analyze a single decision for AFM patterns. Returns count of AFMs found."""
        if not decision.extra_field_values_json:
            return 0

        decision_afm_count = 0
        decision_parent_keys = set()

        # Debug: Show first few decisions' structure if debug mode is on
        if self.debug_afm and self.debug_count < 5:
            self.stdout.write(f"[BUG] DEBUG - Decision {decision.ada}:")
            self.stdout.write(
                f"   extra_field_values_json type: {type(decision.extra_field_values_json)}"
            )
            self.stdout.write(
                f"   Content preview: {str(decision.extra_field_values_json)[:200]}..."
            )
            self.debug_count += 1

        # Find all AFM patterns in this decision
        afm_patterns = self.find_afm_patterns_in_data(
            decision.extra_field_values_json, decision.ada
        )

        if self.debug_afm and afm_patterns and self.debug_count < 10:
            self.stdout.write(
                f"[TARGET] Found {len(afm_patterns)} AFM patterns in decision {decision.ada}"
            )
            for pattern in afm_patterns[:2]:  # Show first 2 patterns
                self.stdout.write(f"   Pattern: {pattern}")

        for pattern in afm_patterns:
            self.record_afm_pattern_batch(pattern, decision.ada)
            decision_afm_count += len(pattern["afm_fields"])
            decision_parent_keys.add(pattern["parent_key"])
            self.patterns_since_flush += 1

        # Record decision-level stats
        if decision_afm_count > 0:
            self.batch_decision_stats[decision.ada] = {
                "afm_count": decision_afm_count,
                "parent_keys": list(decision_parent_keys),
            }

        return decision_afm_count

    def find_afm_patterns_in_data(
        self, data: Any, decision_ada: str, parent_path: str = ""
    ) -> List[Dict]:
        """Recursively find AFM patterns and return as structured list."""
        patterns = []

        if isinstance(data, dict):
            # Check if this dict contains AFM-like fields
            afm_indicators = self.detect_afm_in_dict(data)

            if afm_indicators:
                # This dict contains AFM data
                parent_key = parent_path.split(".")[-1] if parent_path else "root"
                patterns.append(
                    {
                        "parent_key": parent_key,
                        "afm_fields": afm_indicators,
                        "data": data,
                        "path": parent_path,
                    }
                )

            # Continue recursing through all nested structures
            for key, value in data.items():
                new_path = f"{parent_path}.{key}" if parent_path else key
                patterns.extend(
                    self.find_afm_patterns_in_data(value, decision_ada, new_path)
                )

        elif isinstance(data, list):
            # Recurse into list items
            for i, item in enumerate(data):
                new_path = f"{parent_path}[{i}]" if parent_path else f"[{i}]"
                patterns.extend(
                    self.find_afm_patterns_in_data(item, decision_ada, new_path)
                )

        return patterns

    def detect_afm_in_dict(self, data: Dict[str, Any]) -> List[str]:
        """Detect if a dictionary contains AFM-related fields - FIXED VERSION."""
        afm_indicators = []

        if not isinstance(data, dict):
            return afm_indicators

        for key, value in data.items():
            if not isinstance(key, str):
                continue

            # Check for AFM field variations (more comprehensive and case-insensitive)
            key_lower = key.lower()
            afm_keywords = ["afm", "αφμ", "tax", "vat", "tin", "taxid", "vatid"]

            # Check if any AFM keyword is in the field name
            if any(afm_term in key_lower for afm_term in afm_keywords):
                # Validate it looks like a Greek AFM
                if self.is_valid_afm_format(value):
                    afm_indicators.append(key)

                    # Track AFM length for debugging and analysis
                    afm_value = str(value).strip()
                    cleaned_afm = self.clean_afm_value(afm_value)
                    if cleaned_afm.isdigit():
                        self.batch_afm_length_distribution[len(cleaned_afm)] += 1

                    # Debug output for first few detections
                    if self.debug_afm and len(afm_indicators) <= 3:
                        self.stdout.write(
                            f"[TARGET] AFM DETECTED: field='{key}', value='{value}', cleaned='{cleaned_afm}'"
                        )

        return afm_indicators

    def clean_afm_value(self, value: Any) -> str:
        """Clean AFM value for validation."""
        if value is None:
            return ""

        # Convert to string and clean
        afm_str = str(value).strip()

        # Remove common prefixes and separators
        cleaned = (
            afm_str.replace("EL", "")
            .replace("GR", "")
            .replace("-", "")
            .replace(" ", "")
            .replace(".", "")
        )

        return cleaned

    def is_valid_afm_format(self, value: Any) -> bool:
        """Check if a value looks like a valid AFM - ENHANCED VERSION."""
        if value is None:
            return False

        # Handle different data types
        if isinstance(value, (int, float)):
            # Numeric AFM - check if it's in reasonable range
            return 100000000 <= value <= 999999999

        if not isinstance(value, str):
            value = str(value)

        cleaned = self.clean_afm_value(value)

        # Check for Greek AFM patterns:
        # - Must be numeric after cleaning
        # - Must be reasonable length (8-12 digits to handle edge cases)
        if cleaned.isdigit():
            length = len(cleaned)
            return 8 <= length <= 12

        return False

    def record_afm_pattern_batch(self, pattern: Dict, decision_ada: str):
        """Record a discovered AFM pattern in batch counters."""
        parent_key = pattern["parent_key"]
        data = pattern["data"]
        afm_fields = pattern["afm_fields"]

        # Update batch counters
        self.batch_parent_key_stats[parent_key] += 1

        # Record inner keys
        for inner_key in data.keys():
            self.batch_inner_key_patterns[parent_key][inner_key] += 1

        # Record AFM field names and values
        for afm_field in afm_fields:
            self.batch_afm_field_names[afm_field] += 1
            afm_value = self.clean_afm_value(data[afm_field])
            self.batch_afm_values[parent_key].add(afm_value)

        # Store structure example if needed
        if len(self.batch_structure_examples[parent_key]) < self.options["sample_size"]:
            self.batch_structure_examples[parent_key].append(
                {"decision_ada": decision_ada, "afm_fields": afm_fields, "data": data}
            )

    def flush_to_temp_database(self):
        """Flush current batch data to temporary SQLite database."""
        if self.patterns_since_flush == 0:
            return

        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        try:
            # Flush parent key stats
            for parent_key, count in self.batch_parent_key_stats.items():
                unique_afms = len(self.batch_afm_values[parent_key])
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO parent_key_stats (parent_key, total_count, unique_afm_count)
                    VALUES (?,
                        COALESCE((SELECT total_count FROM parent_key_stats WHERE parent_key = ?), 0) + ?,
                        COALESCE((SELECT unique_afm_count FROM parent_key_stats WHERE parent_key = ?), 0) + ?)
                """,
                    (parent_key, parent_key, count, parent_key, unique_afms),
                )

            # Flush inner key patterns
            for parent_key, inner_keys in self.batch_inner_key_patterns.items():
                for inner_key, count in inner_keys.items():
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO inner_key_patterns (parent_key, inner_key, count)
                        VALUES (?, ?,
                            COALESCE((SELECT count FROM inner_key_patterns WHERE parent_key = ? AND inner_key = ?), 0) + ?)
                    """,
                        (parent_key, inner_key, parent_key, inner_key, count),
                    )

            # Flush AFM field names
            for field_name, count in self.batch_afm_field_names.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO afm_field_names (field_name, count)
                    VALUES (?,
                        COALESCE((SELECT count FROM afm_field_names WHERE field_name = ?), 0) + ?)
                """,
                    (field_name, field_name, count),
                )

            # Flush AFM values
            for parent_key, afm_set in self.batch_afm_values.items():
                for afm_value in afm_set:
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO afm_values (parent_key, afm_value, count)
                        VALUES (?, ?,
                            COALESCE((SELECT count FROM afm_values WHERE parent_key = ? AND afm_value = ?), 0) + 1)
                    """,
                        (parent_key, afm_value, parent_key, afm_value),
                    )

            # Flush AFM length distribution
            for length, count in self.batch_afm_length_distribution.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO afm_length_distribution (length, count)
                    VALUES (?,
                        COALESCE((SELECT count FROM afm_length_distribution WHERE length = ?), 0) + ?)
                """,
                    (length, length, count),
                )

            # Flush structure examples
            for parent_key, examples in self.batch_structure_examples.items():
                for example in examples:
                    cursor.execute(
                        """
                        INSERT INTO structure_examples (parent_key, decision_ada, afm_fields, raw_data)
                        VALUES (?, ?, ?, ?)
                    """,
                        (
                            parent_key,
                            example["decision_ada"],
                            json.dumps(example["afm_fields"]),
                            json.dumps(example["data"], ensure_ascii=False),
                        ),
                    )

            # Flush decision stats
            for decision_ada, stats in self.batch_decision_stats.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO decision_stats (decision_ada, afm_count, parent_keys)
                    VALUES (?, ?, ?)
                """,
                    (
                        decision_ada,
                        stats["afm_count"],
                        json.dumps(stats["parent_keys"]),
                    ),
                )

            conn.commit()
            self.stdout.write(
                f"[SAVE] Flushed {self.patterns_since_flush} patterns to temp database"
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error flushing to database: {e}"))
            conn.rollback()
        finally:
            conn.close()

    def show_progress(self, processed: int, total: int):
        """Show detailed progress information."""
        percentage = (processed / total) * 100

        # Get quick stats from temp database
        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM parent_key_stats")
        unique_parents = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(total_count) FROM parent_key_stats")
        total_structures = cursor.fetchone()[0] or 0

        cursor.execute("SELECT COUNT(*) FROM decision_stats")
        decisions_with_afms = cursor.fetchone()[0]

        conn.close()

        self.stdout.write(
            f"[CHART] Progress: {processed:,}/{total:,} ({percentage:.1f}%) | "
            f"AFM decisions: {decisions_with_afms:,} | "
            f"Parent keys: {unique_parents} | "
            f"AFM structures: {total_structures:,}"
        )

    def generate_comprehensive_reports_from_db(self, processed_count: int):
        """Generate all reports from the temporary database."""
        self.stdout.write("[METRIC] Generating comprehensive reports from database...")

        conn = sqlite3.connect(self.temp_db_path)

        try:
            self.generate_executive_summary_from_db(conn, processed_count)
            self.generate_parent_key_analysis_from_db(conn)
            self.generate_data_quality_report_from_db(conn)
            self.generate_structure_examples_from_db(conn)
            self.generate_extraction_strategy_from_db(conn)
            self.generate_json_exports_from_db(conn)

        finally:
            conn.close()

    def generate_executive_summary_from_db(
        self, conn: sqlite3.Connection, processed_count: int
    ):
        """Generate executive summary from database - FIXED SQL."""
        cursor = conn.cursor()

        # Get key metrics
        cursor.execute("SELECT COUNT(*) FROM decision_stats")
        decisions_with_afms = cursor.fetchone()[0]

        cursor.execute("SELECT SUM(total_count) FROM parent_key_stats")
        total_structures = cursor.fetchone()[0] or 0

        # FIXED: Use proper SQLite syntax for counting unique combinations
        cursor.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT parent_key, afm_value FROM afm_values)"
        )
        unique_afms = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM parent_key_stats")
        unique_parents = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM afm_field_names")
        field_variations = cursor.fetchone()[0]

        # Get top insights
        cursor.execute(
            "SELECT parent_key, total_count FROM parent_key_stats ORDER BY total_count DESC LIMIT 1"
        )
        top_parent = cursor.fetchone()

        cursor.execute(
            "SELECT field_name, count FROM afm_field_names ORDER BY count DESC LIMIT 1"
        )
        top_field = cursor.fetchone()

        cursor.execute(
            "SELECT length, count FROM afm_length_distribution ORDER BY count DESC LIMIT 1"
        )
        top_length = cursor.fetchone()

        # Write report
        report_path = self.output_dir / "EXECUTIVE_SUMMARY.txt"
        afm_coverage = (
            (decisions_with_afms / processed_count) * 100 if processed_count > 0 else 0
        )

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[TARGET] AFM PATTERN EXPLORATION - EXECUTIVE SUMMARY\n")
            f.write("=" * 60 + "\n\n")

            f.write("[CHART] KEY METRICS:\n")
            f.write("-" * 20 + "\n")
            f.write(f"Total decisions processed: {processed_count:,}\n")
            f.write(
                f"Decisions containing AFMs: {decisions_with_afms:,} ({afm_coverage:.1f}%)\n"
            )
            f.write(f"Total AFM structures found: {total_structures:,}\n")
            f.write(f"Unique AFM values discovered: {unique_afms:,}\n")
            f.write(f"Unique parent key patterns: {unique_parents}\n")
            f.write(f"AFM field name variations: {field_variations}\n\n")

            f.write("[SCAN] TOP INSIGHTS:\n")
            f.write("-" * 20 + "\n")
            if top_parent:
                f.write(
                    f"Most common parent key: '{top_parent[0]}' ({top_parent[1]:,} occurrences)\n"
                )
            if top_field:
                f.write(
                    f"Most common AFM field name: '{top_field[0]}' ({top_field[1]:,} uses)\n"
                )
            if top_length:
                f.write(
                    f"Most common AFM length: {top_length[0]} digits ({top_length[1]:,} AFMs)\n"
                )

            f.write("\n[LAUNCH] RECOMMENDED NEXT STEPS:\n")
            f.write("-" * 25 + "\n")
            f.write("1. Review detailed pattern analysis\n")
            f.write("2. Design extraction strategy based on findings\n")
            f.write("3. Implement entity extraction command\n")
            f.write("4. Set up AFM validation pipeline\n")

    def generate_parent_key_analysis_from_db(self, conn: sqlite3.Connection):
        """Generate detailed parent key analysis."""
        cursor = conn.cursor()

        report_path = self.output_dir / "parent_key_detailed_analysis.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[DIR_OPEN] PARENT KEY DETAILED ANALYSIS\n")
            f.write("=" * 50 + "\n\n")

            # Get all parent keys ordered by frequency
            cursor.execute(
                """
                SELECT parent_key, total_count, unique_afm_count
                FROM parent_key_stats
                ORDER BY total_count DESC
            """
            )

            for parent_key, total_count, unique_afm_count in cursor.fetchall():
                f.write(
                    f"[AUTH] PARENT KEY: '{parent_key}' ({total_count:,} occurrences)\n"
                )
                f.write("-" * 50 + "\n")
                f.write(f"Unique AFM values: {unique_afm_count:,}\n\n")

                # Get inner key patterns for this parent
                cursor.execute(
                    """
                    SELECT inner_key, count
                    FROM inner_key_patterns
                    WHERE parent_key = ?
                    ORDER BY count DESC
                """,
                    (parent_key,),
                )

                f.write("Inner key frequency:\n")
                for inner_key, count in cursor.fetchall():
                    percentage = (count / total_count) * 100
                    f.write(f"  {inner_key:<25} | {count:>6,} ({percentage:>5.1f}%)\n")

                f.write("\n" + "=" * 50 + "\n\n")

    def generate_data_quality_report_from_db(self, conn: sqlite3.Connection):
        """Generate data quality analysis from database."""
        cursor = conn.cursor()

        report_path = self.output_dir / "data_quality_analysis.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[COPY] AFM DATA QUALITY ANALYSIS\n")
            f.write("=" * 40 + "\n\n")

            # AFM length distribution
            f.write("[SCALE] AFM LENGTH DISTRIBUTION:\n")
            f.write("-" * 30 + "\n")

            cursor.execute(
                "SELECT length, count FROM afm_length_distribution ORDER BY length"
            )
            total_afms = 0
            length_data = cursor.fetchall()

            for _, count in length_data:
                total_afms += count

            for length, count in length_data:
                percentage = (count / total_afms) * 100 if total_afms > 0 else 0
                quality = (
                    "[OK] Standard"
                    if length == 9
                    else (
                        "[WARN]️ Non-standard"
                        if 8 <= length <= 12
                        else "[ERROR] Invalid"
                    )
                )
                f.write(
                    f"{length:2d} digits: {count:>8,} AFMs ({percentage:>5.1f}%) {quality}\n"
                )

            # Coverage by parent key
            f.write(f"\n[METRIC] COVERAGE BY PARENT KEY:\n")
            f.write("-" * 30 + "\n")

            cursor.execute("SELECT SUM(total_count) FROM parent_key_stats")
            total_structures = cursor.fetchone()[0] or 1  # Avoid division by zero

            cursor.execute(
                """
                SELECT parent_key, total_count, unique_afm_count
                FROM parent_key_stats
                ORDER BY total_count DESC
            """
            )

            for parent_key, count, unique_afms in cursor.fetchall():
                percentage = (count / total_structures) * 100
                f.write(
                    f"{parent_key:<20} | {count:>6,} ({percentage:>5.1f}%) | {unique_afms:>6,} unique AFMs\n"
                )

    def generate_structure_examples_from_db(self, conn: sqlite3.Connection):
        """Generate structure examples from database."""
        cursor = conn.cursor()

        report_path = self.output_dir / "structure_examples.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[COPY] ENTITY STRUCTURE EXAMPLES\n")
            f.write("=" * 50 + "\n\n")

            # Get examples for each parent key
            cursor.execute(
                "SELECT DISTINCT parent_key FROM structure_examples ORDER BY parent_key"
            )
            parent_keys = [row[0] for row in cursor.fetchall()]

            for parent_key in parent_keys:
                f.write(f"[AUTH] PARENT KEY: '{parent_key}'\n")
                f.write("-" * 30 + "\n")

                cursor.execute(
                    """
                    SELECT decision_ada, afm_fields, raw_data
                    FROM structure_examples
                    WHERE parent_key = ?
                    LIMIT 5
                """,
                    (parent_key,),
                )

                for i, (decision_ada, afm_fields_json, raw_data_json) in enumerate(
                    cursor.fetchall(), 1
                ):
                    afm_fields = json.loads(afm_fields_json)
                    raw_data = json.loads(raw_data_json)

                    f.write(f"Example {i} (Decision: {decision_ada}):\n")
                    f.write(f"AFM Fields: {afm_fields}\n")
                    f.write("Structure:\n")

                    for key, value in raw_data.items():
                        if isinstance(value, str) and len(value) > 50:
                            value = value[:47] + "..."
                        f.write(f"  {key}: {value}\n")
                    f.write("\n")

                f.write("=" * 50 + "\n\n")

    def generate_extraction_strategy_from_db(self, conn: sqlite3.Connection):
        """Generate extraction strategy recommendations."""
        cursor = conn.cursor()

        guide_path = self.output_dir / "EXTRACTION_STRATEGY_GUIDE.txt"

        # Get key data for recommendations
        cursor.execute(
            "SELECT parent_key, total_count FROM parent_key_stats ORDER BY total_count DESC LIMIT 10"
        )
        top_parents = cursor.fetchall()

        cursor.execute(
            "SELECT field_name, count FROM afm_field_names ORDER BY count DESC LIMIT 10"
        )
        top_fields = cursor.fetchall()

        with open(guide_path, "w", encoding="utf-8") as f:
            f.write("[TARGET] AFM EXTRACTION STRATEGY GUIDE\n")
            f.write("=" * 45 + "\n\n")

            f.write("[CONFIG] RECOMMENDED EXTRACTION APPROACH:\n\n")

            f.write("1. PRIORITY PARENT KEYS (focus extraction here):\n")
            for parent_key, count in top_parents:
                f.write(f"   • {parent_key}: {count:,} occurrences\n")

            f.write(f"\n2. RELIABLE AFM FIELD NAMES:\n")
            for field_name, count in top_fields:
                f.write(f"   • '{field_name}': {count:,} uses\n")

            f.write(f"\n3. IMPLEMENTATION STRATEGY:\n")
            f.write("   • Use temporary database for large-scale extraction\n")
            f.write("   • Process in batches to handle memory efficiently\n")
            f.write("   • Validate AFMs using checksum algorithms\n")
            f.write("   • Store extraction metadata for auditing\n")

    def generate_json_exports_from_db(self, conn: sqlite3.Connection):
        """Export key data as JSON for further analysis."""
        cursor = conn.cursor()

        # Export parent key stats
        cursor.execute(
            "SELECT parent_key, total_count, unique_afm_count FROM parent_key_stats"
        )
        parent_stats = {
            row[0]: {"count": row[1], "unique_afms": row[2]}
            for row in cursor.fetchall()
        }

        # Export AFM field names
        cursor.execute("SELECT field_name, count FROM afm_field_names")
        field_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # Export length distribution
        cursor.execute("SELECT length, count FROM afm_length_distribution")
        length_stats = {row[0]: row[1] for row in cursor.fetchall()}

        # Combine and export
        export_data = {
            "parent_key_statistics": parent_stats,
            "afm_field_names": field_stats,
            "afm_length_distribution": length_stats,
            "analysis_metadata": {
                "database_used": True,
                "temp_db_path": self.temp_db_path,
                "batch_size": self.options["batch_size"],
                "flush_size": self.options["temp_db_flush_size"],
            },
        }

        json_path = self.output_dir / "complete_analysis_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)
