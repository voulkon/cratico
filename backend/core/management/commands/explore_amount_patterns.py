"""
Explore amount patterns in Decision extra_field_values_json entries, with focus on orphaned amounts and comparisons.

# Quick test
python manage.py explore_amount_patterns \
    --batch-size 50 \
    --temp-db-flush-size 200 \
    --sample-size 10 \
    --progress-interval 500

# Full analysis
python manage.py explore_amount_patterns \
    --batch-size 100 \
    --temp-db-flush-size 500 \
    --sample-size 50 \
    --progress-interval 1000 \
    --output-dir "amount_analysis_$(date +%Y%m%d_%H%M)"
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
    help = "Explore amount patterns in ALL Decision extra_field_values_json entries, with orphaned and comparison analysis"

    def add_arguments(self, parser):
        parser.add_argument("--output-dir", type=str, default="amount_analysis_results")
        parser.add_argument("--batch-size", type=int, default=100)
        parser.add_argument("--temp-db-flush-size", type=int, default=500)
        parser.add_argument("--sample-size", type=int, default=50)
        parser.add_argument("--progress-interval", type=int, default=1000)
        parser.add_argument("--debug-amounts", action="store_true")

    def handle(self, *args, **options):
        self.options = options
        self.debug_amounts = options.get("debug_amounts", False)
        self.setup_directories(options["output_dir"])

        # Create temporary SQLite database for pattern storage
        self.temp_db_path = self.create_temp_database()
        self.reset_batch_counters()

        try:
            total_decisions = self.get_total_decision_count()
            if total_decisions == 0:
                self.stdout.write(
                    self.style.ERROR("No decisions with extra_field_values_json found.")
                )
                return

            self.stdout.write(
                f"[COST] Exploring amount patterns in {total_decisions:,} decisions..."
            )
            self.stdout.write(f"[DIR] Using temporary database: {self.temp_db_path}")

            processed_count = self.process_all_decisions(total_decisions)

            # Final flush
            self.flush_to_temp_database()

            # Generate reports
            self.generate_comprehensive_reports_from_db(processed_count)

            self.stdout.write(
                self.style.SUCCESS(
                    f"[OK] Amount pattern exploration complete! Results in: {self.output_dir}"
                )
            )

        finally:
            if os.path.exists(self.temp_db_path):
                os.unlink(self.temp_db_path)
                self.stdout.write(f"[PURGE]️ Cleaned up temporary database")

    def setup_directories(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def create_temp_database(self) -> str:
        temp_dir = tempfile.gettempdir()
        temp_db_path = os.path.join(temp_dir, f"amount_patterns_{os.getpid()}.db")

        conn = sqlite3.connect(temp_db_path)
        cursor = conn.cursor()

        # Table for amount field patterns
        cursor.execute(
            """
            CREATE TABLE amount_field_patterns (
                field_name TEXT PRIMARY KEY,
                total_count INTEGER DEFAULT 0,
                structure_type TEXT,  -- 'nested_object', 'plain_numeric', 'other'
                sample_values TEXT    -- JSON array of sample values
            )
        """
        )

        # Table for parent path analysis
        cursor.execute(
            """
            CREATE TABLE amount_parent_paths (
                parent_path TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                has_currency_info BOOLEAN DEFAULT FALSE,
                avg_amount REAL,
                min_amount REAL,
                max_amount REAL
            )
        """
        )

        # Table for amount-AFM relationships
        cursor.execute(
            """
            CREATE TABLE amount_afm_relationships (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_ada TEXT,
                parent_path TEXT,
                amount_value REAL,
                currency TEXT,
                related_afm TEXT,
                afm_field_path TEXT
            )
        """
        )

        # Table for structure examples
        cursor.execute(
            """
            CREATE TABLE amount_structure_examples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                parent_path TEXT,
                decision_ada TEXT,
                amount_field TEXT,
                structure_type TEXT,
                raw_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Table for currency patterns
        cursor.execute(
            """
            CREATE TABLE currency_patterns (
                currency TEXT PRIMARY KEY,
                count INTEGER DEFAULT 0,
                avg_amount REAL
            )
        """
        )

        # Table for orphaned amount analysis
        cursor.execute(
            """
            CREATE TABLE orphaned_amounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_ada TEXT,
                parent_path TEXT,
                field_name TEXT,
                amount_value REAL,
                currency TEXT,
                structure_type TEXT,
                raw_data TEXT
            )
        """
        )

        # Table for amount comparisons (e.g., kae vs expense)
        cursor.execute(
            """
            CREATE TABLE amount_comparisons (
                decision_ada TEXT PRIMARY KEY,
                has_multiple_types BOOLEAN,
                kae_amount REAL,
                expense_amount REAL,
                difference REAL,
                ratio REAL
            )
        """
        )

        conn.commit()
        conn.close()

        return temp_db_path

    def reset_batch_counters(self):
        self.batch_amount_fields = Counter()
        self.batch_parent_paths = defaultdict(list)  # Store amounts for avg/min/max
        self.batch_currency_patterns = Counter()
        self.batch_amount_afm_relationships = []
        self.batch_structure_examples = defaultdict(list)
        self.batch_orphaned_amounts = []  # NEW
        self.batch_amount_comparisons = (
            {}
        )  # NEW: dict of decision_ada to comparison data
        self.patterns_since_flush = 0
        self.debug_count = 0

    def get_total_decision_count(self) -> int:
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
        batch_size = self.options["batch_size"]
        progress_interval = self.options["progress_interval"]
        flush_size = self.options["temp_db_flush_size"]
        processed_count = 0

        queryset = (
            Decision.objects.exclude(extra_field_values_json__isnull=True)
            .exclude(extra_field_values_json={})
            .only("ada", "extra_field_values_json")
        )

        self.stdout.write("[LAUNCH] Starting amount pattern analysis...")

        for i in range(0, total_decisions, batch_size):
            batch = list(queryset[i : i + batch_size])

            for decision in batch:
                self.analyze_decision_amount_patterns(decision)
                processed_count += 1

                if self.patterns_since_flush >= flush_size:
                    self.flush_to_temp_database()
                    self.reset_batch_counters()

                if processed_count % progress_interval == 0:
                    self.show_progress(processed_count, total_decisions)

            del batch

        self.stdout.write(
            f"[TARGET] Completed processing {processed_count:,} decisions"
        )
        return processed_count

    def analyze_decision_amount_patterns(self, decision: Decision):
        if not decision.extra_field_values_json:
            return

        if self.debug_amounts and self.debug_count < 5:
            self.stdout.write(f"[BUG] DEBUG - Decision {decision.ada}")
            self.stdout.write(
                f"   Content preview: {str(decision.extra_field_values_json)[:200]}..."
            )
            self.debug_count += 1

        # Find all amount patterns in this decision
        amount_patterns = self.find_amount_patterns_in_data(
            decision.extra_field_values_json, decision.ada
        )

        if self.debug_amounts and amount_patterns and self.debug_count < 10:
            self.stdout.write(
                f"[COST] Found {len(amount_patterns)} amount patterns in decision {decision.ada}"
            )
            for pattern in amount_patterns[:2]:
                self.stdout.write(
                    f"   Pattern: {pattern['parent_path']} -> {pattern['amount_info']}"
                )

        for pattern in amount_patterns:
            self.record_amount_pattern_batch(pattern, decision.ada)
            self.patterns_since_flush += 1

    def find_amount_patterns_in_data(
        self, data: Any, decision_ada: str, parent_path: str = ""
    ) -> List[Dict]:
        patterns = []

        if isinstance(data, dict):
            # Check if this dict contains amount-like fields
            amount_info = self.detect_amounts_in_dict(data, parent_path)

            if amount_info:
                patterns.append(
                    {
                        "parent_path": parent_path or "root",
                        "amount_info": amount_info,
                        "raw_data": data,
                    }
                )

            # Recurse through nested structures
            for key, value in data.items():
                new_path = f"{parent_path}.{key}" if parent_path else key
                patterns.extend(
                    self.find_amount_patterns_in_data(value, decision_ada, new_path)
                )

        elif isinstance(data, list):
            for i, item in enumerate(data):
                new_path = f"{parent_path}[{i}]" if parent_path else f"[{i}]"
                patterns.extend(
                    self.find_amount_patterns_in_data(item, decision_ada, new_path)
                )

        return patterns

    def detect_amounts_in_dict(
        self, data: Dict[str, Any], parent_path: str
    ) -> Dict[str, Any]:
        amount_info = {
            "fields_found": [],
            "structure_types": [],
            "amounts": [],
            "currencies": [],
            "related_afms": [],
            "is_orphaned": False,  # NEW
        }

        amount_keywords = [
            "amount",
            "expenseAmount",
            "awardAmount",
            "amountWithVAT",
            "value",
            "cost",
            "price",
            "sum",
            "total",
            "ποσο",
            "αξια",
        ]

        for key, value in data.items():
            key_lower = key.lower()
            if any(amt_term in key_lower for amt_term in amount_keywords):
                amount_info["fields_found"].append(key)
                if isinstance(value, dict):
                    amount_info["structure_types"].append("nested_object")
                    if "amount" in value:
                        amt = value["amount"]
                        if amt is not None:
                            try:
                                amount_info["amounts"].append(float(amt))
                            except (ValueError, TypeError):
                                pass  # Ignore non-numeric
                    if "currency" in value and value["currency"] is not None:
                        amount_info["currencies"].append(value["currency"])
                elif isinstance(value, (int, float)):
                    amount_info["structure_types"].append("plain_numeric")
                    amount_info["amounts"].append(float(value))
                else:
                    amount_info["structure_types"].append("other")
                    try:
                        if value is not None:
                            numeric_value = float(str(value).replace(",", ""))
                            amount_info["amounts"].append(numeric_value)
                    except (ValueError, TypeError):
                        pass

        # Look for related AFMs in the same structure
        for key, value in data.items():
            if "afm" in key.lower() and isinstance(value, str):
                amount_info["related_afms"].append(value)
            elif isinstance(value, dict) and "afm" in value:
                amount_info["related_afms"].append(value["afm"])

        # NEW: Check if orphaned (no related AFMs in this context)
        if amount_info["fields_found"] and not amount_info["related_afms"]:
            amount_info["is_orphaned"] = True

        return amount_info if amount_info["fields_found"] else {}

    def record_amount_pattern_batch(self, pattern: Dict, decision_ada: str):
        parent_path = pattern["parent_path"]
        amount_info = pattern["amount_info"]
        raw_data = pattern["raw_data"]

        # Record amount fields
        for field in amount_info["fields_found"]:
            self.batch_amount_fields[field] += 1

        # Record parent path stats
        if amount_info["amounts"]:
            self.batch_parent_paths[parent_path].extend(amount_info["amounts"])

        # Record currency patterns
        for currency in amount_info["currencies"]:
            self.batch_currency_patterns[currency] += 1

        # Record amount-AFM relationships
        for amount in amount_info["amounts"]:
            for afm in amount_info["related_afms"]:
                self.batch_amount_afm_relationships.append(
                    {
                        "decision_ada": decision_ada,
                        "parent_path": parent_path,
                        "amount_value": amount,
                        "currency": (
                            amount_info["currencies"][0]
                            if amount_info["currencies"]
                            else None
                        ),
                        "related_afm": afm,
                        "afm_field_path": parent_path,  # Simplified for now
                    }
                )

        # Store structure examples
        if (
            len(self.batch_structure_examples[parent_path])
            < self.options["sample_size"]
        ):
            self.batch_structure_examples[parent_path].append(
                {
                    "decision_ada": decision_ada,
                    "amount_fields": amount_info["fields_found"],
                    "structure_types": amount_info["structure_types"],
                    "raw_data": raw_data,
                }
            )

        # NEW: Record orphaned amounts
        if pattern["amount_info"]["is_orphaned"]:
            for i, amount in enumerate(pattern["amount_info"]["amounts"]):
                self.batch_orphaned_amounts.append(
                    {
                        "decision_ada": decision_ada,
                        "parent_path": pattern["parent_path"],
                        "field_name": (
                            pattern["amount_info"]["fields_found"][i]
                            if i < len(pattern["amount_info"]["fields_found"])
                            else None
                        ),
                        "amount_value": amount,
                        "currency": (
                            pattern["amount_info"]["currencies"][i]
                            if i < len(pattern["amount_info"]["currencies"])
                            else None
                        ),
                        "structure_type": (
                            pattern["amount_info"]["structure_types"][i]
                            if i < len(pattern["amount_info"]["structure_types"])
                            else None
                        ),
                        "raw_data": json.dumps(pattern["raw_data"], ensure_ascii=False),
                    }
                )

        # NEW: Record for comparisons (e.g., kae vs expense)
        if decision_ada not in self.batch_amount_comparisons:
            self.batch_amount_comparisons[decision_ada] = {"kae": None, "expense": None}

        for field, amt in zip(
            pattern["amount_info"]["fields_found"], pattern["amount_info"]["amounts"]
        ):
            field_lower = field.lower()
            # Expanded kae-like: budget/total/kae
            if any(term in field_lower for term in ["kae", "budget", "total"]):
                self.batch_amount_comparisons[decision_ada]["kae"] = amt
            # Expanded expense-like: expense/award/cost/value/ποσο (add Greek if needed)
            elif any(
                term in field_lower
                for term in ["expense", "award", "cost", "value", "ποσο"]
            ):
                self.batch_amount_comparisons[decision_ada]["expense"] = amt

    def flush_to_temp_database(self):
        if self.patterns_since_flush == 0:
            return

        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        try:
            # Flush amount field patterns
            for field_name, count in self.batch_amount_fields.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO amount_field_patterns (field_name, total_count)
                    VALUES (?,
                        COALESCE((SELECT total_count FROM amount_field_patterns WHERE field_name = ?), 0) + ?)
                """,
                    (field_name, field_name, count),
                )

            # Flush parent path stats with amount aggregations
            for parent_path, amounts in self.batch_parent_paths.items():
                if amounts:
                    avg_amount = sum(amounts) / len(amounts)
                    min_amount = min(amounts)
                    max_amount = max(amounts)

                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO amount_parent_paths
                        (parent_path, count, avg_amount, min_amount, max_amount)
                        VALUES (?,
                            COALESCE((SELECT count FROM amount_parent_paths WHERE parent_path = ?), 0) + ?,
                            ?, ?, ?)
                    """,
                        (
                            parent_path,
                            parent_path,
                            len(amounts),
                            avg_amount,
                            min_amount,
                            max_amount,
                        ),
                    )

            # Flush currency patterns
            for currency, count in self.batch_currency_patterns.items():
                cursor.execute(
                    """
                    INSERT OR REPLACE INTO currency_patterns (currency, count)
                    VALUES (?,
                        COALESCE((SELECT count FROM currency_patterns WHERE currency = ?), 0) + ?)
                """,
                    (currency, currency, count),
                )

            # Flush amount-AFM relationships
            for rel in self.batch_amount_afm_relationships:
                cursor.execute(
                    """
                    INSERT INTO amount_afm_relationships
                    (decision_ada, parent_path, amount_value, currency, related_afm, afm_field_path)
                    VALUES (?, ?, ?, ?, ?, ?)
                """,
                    (
                        rel["decision_ada"],
                        rel["parent_path"],
                        rel["amount_value"],
                        rel["currency"],
                        rel["related_afm"],
                        rel["afm_field_path"],
                    ),
                )

            # Flush structure examples
            for parent_path, examples in self.batch_structure_examples.items():
                for example in examples:
                    cursor.execute(
                        """
                        INSERT INTO amount_structure_examples
                        (parent_path, decision_ada, amount_field, structure_type, raw_data)
                        VALUES (?, ?, ?, ?, ?)
                    """,
                        (
                            parent_path,
                            example["decision_ada"],
                            json.dumps(example["amount_fields"]),
                            json.dumps(example["structure_types"]),
                            json.dumps(example["raw_data"], ensure_ascii=False),
                        ),
                    )

            # Flush orphaned amounts
            for orphaned in self.batch_orphaned_amounts:
                cursor.execute(
                    """
                    INSERT INTO orphaned_amounts
                    (decision_ada, parent_path, field_name, amount_value, currency, structure_type, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        orphaned["decision_ada"],
                        orphaned["parent_path"],
                        orphaned["field_name"],
                        orphaned["amount_value"],
                        orphaned["currency"],
                        orphaned["structure_type"],
                        orphaned["raw_data"],
                    ),
                )

            # Flush comparisons
            for ada, comp in self.batch_amount_comparisons.items():
                if comp["kae"] is not None and comp["expense"] is not None:
                    diff = comp["kae"] - comp["expense"]
                    ratio = (
                        comp["kae"] / comp["expense"] if comp["expense"] != 0 else None
                    )
                    cursor.execute(
                        """
                        INSERT OR REPLACE INTO amount_comparisons
                        (decision_ada, has_multiple_types, kae_amount, expense_amount, difference, ratio)
                        VALUES (?, TRUE, ?, ?, ?, ?)
                    """,
                        (ada, comp["kae"], comp["expense"], diff, ratio),
                    )

            conn.commit()
            self.stdout.write(
                f"[SAVE] Flushed {self.patterns_since_flush} amount patterns to temp database"
            )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error flushing to database: {e}"))
            conn.rollback()
        finally:
            conn.close()

    def show_progress(self, processed: int, total: int):
        percentage = (processed / total) * 100

        conn = sqlite3.connect(self.temp_db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM amount_field_patterns")
        unique_fields = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM amount_parent_paths")
        unique_paths = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(*) FROM amount_afm_relationships")
        amount_afm_links = cursor.fetchone()[0]

        conn.close()

        self.stdout.write(
            f"[CHART] Progress: {processed:,}/{total:,} ({percentage:.1f}%) | "
            f"Amount fields: {unique_fields} | "
            f"Parent paths: {unique_paths} | "
            f"Amount-AFM links: {amount_afm_links:,}"
        )

    def generate_comprehensive_reports_from_db(self, processed_count: int):
        self.stdout.write(
            "[METRIC] Generating comprehensive amount analysis reports..."
        )

        conn = sqlite3.connect(self.temp_db_path)

        try:
            self.generate_amount_field_analysis(conn, processed_count)
            self.generate_amount_afm_relationships_report(conn)
            self.generate_extraction_strategy_report(conn)
            self.generate_json_exports(conn)
            self.generate_orphaned_amounts_report(conn, processed_count)
            self.generate_amount_comparisons_report(conn)

        finally:
            conn.close()

    def generate_amount_field_analysis(
        self, conn: sqlite3.Connection, processed_count: int
    ):
        cursor = conn.cursor()

        report_path = self.output_dir / "AMOUNT_FIELD_ANALYSIS.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[COST] AMOUNT FIELD ANALYSIS REPORT\n")
            f.write("=" * 50 + "\n\n")

            # Top amount field names
            f.write("[SCAN] MOST COMMON AMOUNT FIELD NAMES:\n")
            f.write("-" * 35 + "\n")

            cursor.execute(
                "SELECT field_name, total_count FROM amount_field_patterns ORDER BY total_count DESC LIMIT 20"
            )
            for field_name, count in cursor.fetchall():
                f.write(f"{field_name:<25} | {count:>8,} occurrences\n")

            # Parent path analysis
            f.write(f"\n[LOC] AMOUNT DISTRIBUTION BY PARENT PATH:\n")
            f.write("-" * 40 + "\n")

            cursor.execute(
                """
                SELECT parent_path, count, avg_amount, min_amount, max_amount
                FROM amount_parent_paths
                ORDER BY count DESC LIMIT 15
            """
            )

            for parent_path, count, avg_amt, min_amt, max_amt in cursor.fetchall():
                f.write(f"\n{parent_path}:\n")
                f.write(f"  Occurrences: {count:,}\n")
                f.write(f"  Avg Amount: €{avg_amt:,.2f}\n")
                f.write(f"  Range: €{min_amt:,.2f} - €{max_amt:,.2f}\n")

            # Currency analysis
            f.write(f"\n[FX] CURRENCY DISTRIBUTION:\n")
            f.write("-" * 25 + "\n")

            cursor.execute(
                "SELECT currency, count FROM currency_patterns ORDER BY count DESC"
            )
            for currency, count in cursor.fetchall():
                f.write(f"{currency:<10} | {count:>8,} occurrences\n")

    def generate_amount_afm_relationships_report(self, conn: sqlite3.Connection):
        cursor = conn.cursor()

        report_path = self.output_dir / "AMOUNT_AFM_RELATIONSHIPS.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[LINK] AMOUNT-AFM RELATIONSHIP ANALYSIS\n")
            f.write("=" * 45 + "\n\n")

            # Top AFMs by amount
            f.write("[COST] TOP AFMs BY TOTAL AMOUNT:\n")
            f.write("-" * 30 + "\n")

            cursor.execute(
                """
                SELECT related_afm, COUNT(*) as transaction_count,
                       SUM(amount_value) as total_amount,
                       AVG(amount_value) as avg_amount
                FROM amount_afm_relationships
                GROUP BY related_afm
                ORDER BY total_amount DESC
                LIMIT 20
            """
            )

            for afm, tx_count, total_amt, avg_amt in cursor.fetchall():
                f.write(f"AFM: {afm}\n")
                f.write(f"  Transactions: {tx_count:,}\n")
                f.write(f"  Total Amount: €{total_amt:,.2f}\n")
                f.write(f"  Average: €{avg_amt:,.2f}\n\n")

            # Parent path distribution
            f.write("[LOC] AMOUNT DISTRIBUTION BY PARENT PATH:\n")
            f.write("-" * 35 + "\n")

            cursor.execute(
                """
                SELECT parent_path, COUNT(*) as count, SUM(amount_value) as total
                FROM amount_afm_relationships
                GROUP BY parent_path
                ORDER BY total DESC
            """
            )

            for parent_path, count, total in cursor.fetchall():
                f.write(f"{parent_path:<30} | {count:>6,} | €{total:>12,.2f}\n")

    def generate_extraction_strategy_report(self, conn: sqlite3.Connection):
        cursor = conn.cursor()

        report_path = self.output_dir / "AMOUNT_EXTRACTION_STRATEGY.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[TARGET] AMOUNT EXTRACTION STRATEGY\n")
            f.write("=" * 40 + "\n\n")

            f.write("[CONFIG] RECOMMENDED EXTRACTION APPROACH:\n\n")

            # Priority fields
            cursor.execute(
                "SELECT field_name, total_count FROM amount_field_patterns ORDER BY total_count DESC LIMIT 10"
            )
            f.write("1. PRIORITY AMOUNT FIELDS:\n")
            for field_name, count in cursor.fetchall():
                f.write(f"   • {field_name}: {count:,} occurrences\n")

            # Priority paths
            cursor.execute(
                "SELECT parent_path, count FROM amount_parent_paths ORDER BY count DESC LIMIT 10"
            )
            f.write(f"\n2. PRIORITY PARENT PATHS:\n")
            for parent_path, count in cursor.fetchall():
                f.write(f"   • {parent_path}: {count:,} occurrences\n")

            f.write(f"\n3. IMPLEMENTATION PLAN:\n")
            f.write("   • Add amount fields to DecisionEntityRelationship model\n")
            f.write("   • Extract amounts during entity extraction process\n")
            f.write("   • Handle both nested and plain numeric formats\n")
            f.write("   • Store currency information when available\n")
            f.write("   • Link amounts to AFM entities for financial analysis\n")

    def generate_json_exports(self, conn: sqlite3.Connection):
        cursor = conn.cursor()

        # Export field patterns
        cursor.execute("SELECT field_name, total_count FROM amount_field_patterns")
        field_patterns = {row[0]: row[1] for row in cursor.fetchall()}

        # Export parent path stats
        cursor.execute("SELECT parent_path, count, avg_amount FROM amount_parent_paths")
        path_stats = {
            row[0]: {"count": row[1], "avg_amount": row[2]} for row in cursor.fetchall()
        }

        export_data = {
            "amount_field_patterns": field_patterns,
            "parent_path_statistics": path_stats,
            "analysis_metadata": {
                "batch_size": self.options["batch_size"],
                "flush_size": self.options["temp_db_flush_size"],
            },
        }

        json_path = self.output_dir / "amount_analysis_data.json"
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(export_data, f, ensure_ascii=False, indent=2)

    # NEW: Report for orphaned amounts
    def generate_orphaned_amounts_report(
        self, conn: sqlite3.Connection, total_decisions: int
    ):
        cursor = conn.cursor()

        report_path = self.output_dir / "ORPHANED_AMOUNTS_ANALYSIS.txt"

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[AUDIT]️ ORPHANED AMOUNTS ANALYSIS (Amounts without nearby AFMs)\n")
            f.write("=" * 60 + "\n\n")

            # Prevalence
            cursor.execute("SELECT COUNT(DISTINCT decision_ada) FROM orphaned_amounts")
            orphaned_decisions = cursor.fetchone()[0]
            percentage = (
                (orphaned_decisions / total_decisions) * 100
                if total_decisions > 0
                else 0
            )
            f.write(
                f"[CHART] Prevalence: {orphaned_decisions:,} decisions have orphaned amounts ({percentage:.2f}% of total)\n\n"
            )

            # Common fields/paths
            f.write("[SCAN] MOST COMMON FIELDS FOR ORPHANED AMOUNTS:\n")
            cursor.execute(
                """
                SELECT field_name, COUNT(*) as count
                FROM orphaned_amounts
                GROUP BY field_name
                ORDER BY count DESC LIMIT 10
            """
            )
            for field, count in cursor.fetchall():
                f.write(f"{field:<25} | {count:>8,} occurrences\n")

            f.write("\n[LOC] MOST COMMON PATHS FOR ORPHANED AMOUNTS:\n")
            cursor.execute(
                """
                SELECT parent_path, COUNT(*) as count
                FROM orphaned_amounts
                GROUP BY parent_path
                ORDER BY count DESC LIMIT 10
            """
            )
            for path, count in cursor.fetchall():
                f.write(f"{path:<30} | {count:>8,} occurrences\n")

            # Examples
            f.write("\n[NOTE] SAMPLE ORPHANED STRUCTURES (up to 5):\n")
            cursor.execute("SELECT raw_data FROM orphaned_amounts LIMIT 5")
            for raw in cursor.fetchall():
                f.write(f"{json.dumps(json.loads(raw[0]), indent=2)}\n\n")

    # NEW: Report for amount comparisons/domain patterns
    def generate_amount_comparisons_report(self, conn: sqlite3.Connection):
        cursor = conn.cursor()
        report_path = self.output_dir / "AMOUNT_COMPARISONS_ANALYSIS.txt"
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("[CHART] AMOUNT COMPARISONS & DOMAIN PATTERNS\n")
            f.write("=" * 45 + "\n\n")
            cursor.execute(
                "SELECT COUNT(*) FROM amount_comparisons WHERE has_multiple_types = TRUE"
            )
            multi_count = cursor.fetchone()[0]
            f.write(
                f"Decisions with multiple amount types (e.g., kae + expense): {multi_count:,}\n\n"
            )
            cursor.execute("SELECT AVG(difference), AVG(ratio) FROM amount_comparisons")
            avg_diff, avg_ratio = cursor.fetchone()
            if avg_diff is not None:
                f.write(f"Average difference (kae - expense): €{avg_diff:,.2f}\n")
            else:
                f.write("Average difference (kae - expense): N/A\n")
            if avg_ratio is not None:
                f.write(f"Average ratio (kae / expense): {avg_ratio:.2f}x\n\n")
            else:
                f.write("Average ratio (kae / expense): N/A\n\n")
            cursor.execute(
                "SELECT COUNT(*) FROM amount_comparisons WHERE difference > 0"
            )
            kae_larger = cursor.fetchone()[0]
            if multi_count > 0:
                f.write(
                    f"Cases where kaeAmount > expenseAmount: {kae_larger:,} ({(kae_larger / multi_count * 100):.2f}% of multi-type decisions)\n"
                )
            else:
                f.write("Cases where kaeAmount > expenseAmount: N/A\n")
            f.write("\n[NOTE] SAMPLE COMPARISONS (up to 5):\n")
            cursor.execute(
                "SELECT decision_ada, kae_amount, expense_amount, difference FROM amount_comparisons LIMIT 5"
            )
            for ada, kae, exp, diff in cursor.fetchall():
                f.write(
                    f"{ada}: KAE €{kae:,.2f} | Expense €{exp:,.2f} | Diff €{diff:,.2f}\n"
                )
