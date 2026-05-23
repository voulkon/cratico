"""
Django management command to comprehensively diagnose database performance.
Tests connection behavior, query performance, I/O, network latency, and PostgreSQL config.

Designed to diagnose why Docker-Compose DB may be slower than native local DB.

Usage:
    python manage.py test_db_connections              # Full diagnostic suite
    python manage.py test_db_connections --quick      # Quick connection test only
    python manage.py test_db_connections --benchmark  # Query benchmarks only
    python manage.py test_db_connections --config     # PostgreSQL config analysis only
    python manage.py test_db_connections --io         # I/O performance tests only
    python manage.py test_db_connections --network    # Network latency tests only
    python manage.py test_db_connections --all        # Everything (verbose)
"""

import socket
import statistics
import threading
import time
from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import connection, connections
from django.http import HttpRequest

from backend.api.views.version import version_check as health_check


class LoadTestStats:
    """Thread-safe statistics collector."""

    def __init__(self):
        self.lock = threading.Lock()
        self.successful = 0
        self.failed = 0
        self.total_duration = 0.0
        self.durations = []
        self.errors = defaultdict(int)

    def record_success(self, duration):
        with self.lock:
            self.successful += 1
            self.total_duration += duration
            self.durations.append(duration)

    def record_failure(self, error):
        with self.lock:
            self.failed += 1
            self.errors[str(error)] += 1

    def get_stats(self):
        with self.lock:
            if self.durations:
                sorted_durations = sorted(self.durations)
                p50 = sorted_durations[int(len(sorted_durations) * 0.5)]
                p95 = sorted_durations[int(len(sorted_durations) * 0.95)]
                p99 = (
                    sorted_durations[int(len(sorted_durations) * 0.99)]
                    if len(sorted_durations) > 100
                    else sorted_durations[-1]
                )
            else:
                p50 = p95 = p99 = 0

            return {
                "successful": self.successful,
                "failed": self.failed,
                "avg_duration": (
                    self.total_duration / self.successful if self.successful > 0 else 0
                ),
                "p50": p50,
                "p95": p95,
                "p99": p99,
                "min": min(self.durations) if self.durations else 0,
                "max": max(self.durations) if self.durations else 0,
                "errors": dict(self.errors),
            }


class Command(BaseCommand):
    help = "Comprehensive database performance diagnostic tool for Docker vs Local comparison"

    def add_arguments(self, parser):
        parser.add_argument(
            "--quick",
            action="store_true",
            help="Run quick connection test only (50 requests, 5 concurrent)",
        )
        parser.add_argument(
            "--benchmark",
            action="store_true",
            help="Run query benchmarks only",
        )
        parser.add_argument(
            "--config",
            action="store_true",
            help="Show PostgreSQL configuration analysis only",
        )
        parser.add_argument(
            "--io",
            action="store_true",
            help="Run I/O performance tests only",
        )
        parser.add_argument(
            "--network",
            action="store_true",
            help="Run network latency tests only",
        )
        parser.add_argument(
            "--all",
            action="store_true",
            help="Run all tests with verbose output",
        )

    def handle(self, *args, **options):
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.SUCCESS("[SCAN] DATABASE PERFORMANCE DIAGNOSTIC TOOL")
        )
        self.stdout.write(
            self.style.SUCCESS("   For Docker vs Local PostgreSQL Comparison")
        )
        self.stdout.write("=" * 80 + "\n")

        # Show current configuration
        self.show_config()

        # Determine which tests to run
        run_all = options["all"] or not any(
            [
                options["quick"],
                options["benchmark"],
                options["config"],
                options["io"],
                options["network"],
            ]
        )

        if options["quick"]:
            self.run_test("Quick Test", num_requests=50, concurrent=5)
        elif options["config"]:
            self.run_postgresql_config_analysis()
        elif options["benchmark"]:
            self.run_query_benchmarks()
        elif options["io"]:
            self.run_io_benchmarks()
        elif options["network"]:
            self.run_network_latency_tests()
        elif run_all:
            # Run comprehensive diagnostic suite
            self.stdout.write(
                self.style.WARNING("\n[COPY] Running full diagnostic suite...\n")
            )

            # 1. Network Latency
            self.run_network_latency_tests()

            # 2. Connection Establishment
            self.run_connection_establishment_tests()

            # 3. PostgreSQL Configuration
            self.run_postgresql_config_analysis()

            # 4. Query Benchmarks
            self.run_query_benchmarks()

            # 5. I/O Benchmarks
            self.run_io_benchmarks()

            # 6. pg_stat_statements analysis
            self.run_pg_stat_statements_analysis()

            # 7. Connection Pool Load Tests
            self.stdout.write("\n" + "=" * 80)
            self.stdout.write(
                self.style.HTTP_INFO("[CHART] CONNECTION POOL LOAD TESTS")
            )
            self.stdout.write("=" * 80)

            self.run_test("Test 1: Low Concurrency", num_requests=50, concurrent=3)
            time.sleep(1)
            self.run_test("Test 2: Medium Concurrency", num_requests=100, concurrent=10)
            time.sleep(1)
            self.run_test("Test 3: High Concurrency", num_requests=150, concurrent=20)

            # 8. Final Summary
            self.print_diagnostic_summary()

        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.SUCCESS("[OK] Diagnostic complete!"))
        self.stdout.write("=" * 80 + "\n")

    def show_config(self):
        """Display current database configuration."""
        db_config = connections["default"].settings_dict
        conn_max_age = db_config.get("CONN_MAX_AGE", 0)
        conn_health_checks = db_config.get("CONN_HEALTH_CHECKS", False)

        self.stdout.write(self.style.WARNING("[PIN] Django Database Configuration:"))
        self.stdout.write(f"  CONN_MAX_AGE: {conn_max_age} seconds")
        self.stdout.write(f"  CONN_HEALTH_CHECKS: {conn_health_checks}")
        self.stdout.write(f"  Database: {db_config.get('NAME')}")
        self.stdout.write(f"  Host: {db_config.get('HOST', 'localhost')}")
        self.stdout.write(f"  Port: {db_config.get('PORT', 5432)}")
        self.stdout.write("")

    # =========================================================================
    # NETWORK LATENCY TESTS
    # =========================================================================
    def run_network_latency_tests(self):
        """Test raw network latency to the database server."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO("[NET] NETWORK LATENCY TESTS"))
        self.stdout.write("=" * 80)

        db_config = connections["default"].settings_dict
        host = db_config.get("HOST", "localhost")
        port = int(db_config.get("PORT", 5432))

        self.stdout.write(f"\n  Testing connection to {host}:{port}")

        # TCP Socket Connect Latency
        self.stdout.write(
            self.style.WARNING("\n  1. TCP Socket Connect Latency (10 samples):")
        )
        tcp_times = []
        for i in range(10):
            try:
                start = time.perf_counter()
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5)
                sock.connect((host, port))
                elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
                tcp_times.append(elapsed)
                sock.close()
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     Socket connect failed: {e}"))

        if tcp_times:
            self.stdout.write(f"     Min: {min(tcp_times):.2f}ms")
            self.stdout.write(f"     Max: {max(tcp_times):.2f}ms")
            self.stdout.write(f"     Avg: {statistics.mean(tcp_times):.2f}ms")
            self.stdout.write(
                f"     Std Dev: {statistics.stdev(tcp_times):.2f}ms"
                if len(tcp_times) > 1
                else ""
            )

            if statistics.mean(tcp_times) > 1.0:
                self.stdout.write(
                    self.style.ERROR(
                        f"\n     [WARN]️  HIGH LATENCY: Avg {statistics.mean(tcp_times):.2f}ms > 1ms"
                    )
                )
                self.stdout.write(
                    self.style.ERROR(
                        "         This suggests network overhead (Docker NAT, bridge network, etc.)"
                    )
                )

        # Simple Query Round Trip Time
        self.stdout.write(
            self.style.WARNING("\n  2. Simple Query Round Trip Time (SELECT 1):")
        )
        query_times = []
        for i in range(20):
            start = time.perf_counter()
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            elapsed = (time.perf_counter() - start) * 1000
            query_times.append(elapsed)

        self.stdout.write(f"     Min: {min(query_times):.2f}ms")
        self.stdout.write(f"     Max: {max(query_times):.2f}ms")
        self.stdout.write(f"     Avg: {statistics.mean(query_times):.2f}ms")
        self.stdout.write(
            f"     P95: {sorted(query_times)[int(len(query_times)*0.95)]:.2f}ms"
        )

        # Compare network vs query overhead
        if tcp_times and query_times:
            network_overhead = statistics.mean(tcp_times)
            total_query = statistics.mean(query_times)
            db_processing = total_query - network_overhead
            self.stdout.write(self.style.WARNING(f"\n  3. Overhead Analysis:"))
            self.stdout.write(
                f"     Network (TCP connect): {network_overhead:.2f}ms ({network_overhead/total_query*100:.1f}%)"
            )
            self.stdout.write(
                f"     DB Processing: {db_processing:.2f}ms ({db_processing/total_query*100:.1f}%)"
            )

    # =========================================================================
    # CONNECTION ESTABLISHMENT TESTS
    # =========================================================================
    def run_connection_establishment_tests(self):
        """Test time to establish new database connections."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO("[CONN] CONNECTION ESTABLISHMENT TESTS"))
        self.stdout.write("=" * 80)

        self.stdout.write(
            self.style.WARNING("\n  1. New Connection Overhead (10 samples):")
        )

        from django.db import connection as default_conn

        new_conn_times = []
        for i in range(10):
            # Force close current connection
            default_conn.close()

            start = time.perf_counter()
            # Force new connection by executing query
            with default_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            elapsed = (time.perf_counter() - start) * 1000
            new_conn_times.append(elapsed)

        self.stdout.write(f"     Min: {min(new_conn_times):.2f}ms")
        self.stdout.write(f"     Max: {max(new_conn_times):.2f}ms")
        self.stdout.write(f"     Avg: {statistics.mean(new_conn_times):.2f}ms")

        # Reused connection comparison
        self.stdout.write(self.style.WARNING("\n  2. Reused Connection (10 samples):"))
        reused_times = []
        for i in range(10):
            start = time.perf_counter()
            with default_conn.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            elapsed = (time.perf_counter() - start) * 1000
            reused_times.append(elapsed)

        self.stdout.write(f"     Min: {min(reused_times):.2f}ms")
        self.stdout.write(f"     Max: {max(reused_times):.2f}ms")
        self.stdout.write(f"     Avg: {statistics.mean(reused_times):.2f}ms")

        overhead = statistics.mean(new_conn_times) - statistics.mean(reused_times)
        self.stdout.write(
            self.style.WARNING(
                f"\n  3. Connection Establishment Overhead: {overhead:.2f}ms"
            )
        )

        if overhead > 10:
            self.stdout.write(
                self.style.ERROR(
                    f"\n     [WARN]️  HIGH OVERHEAD: New connections take {overhead:.2f}ms extra"
                )
            )
            self.stdout.write(
                self.style.ERROR(
                    "         Consider setting CONN_MAX_AGE > 0 for connection reuse"
                )
            )

    # =========================================================================
    # POSTGRESQL CONFIGURATION ANALYSIS
    # =========================================================================
    def run_postgresql_config_analysis(self):
        """Analyze PostgreSQL configuration for performance issues."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.HTTP_INFO("[SYS]️  POSTGRESQL CONFIGURATION ANALYSIS")
        )
        self.stdout.write("=" * 80)

        # Key performance settings to check
        settings_to_check = [
            # Memory settings
            ("shared_buffers", "128MB", "Should be ~25% of RAM"),
            ("effective_cache_size", "4GB", "Should be ~75% of RAM"),
            ("work_mem", "4MB", "Per-operation memory"),
            ("maintenance_work_mem", "64MB", "For VACUUM, CREATE INDEX"),
            # Connection settings
            ("max_connections", "100", "Max allowed connections"),
            # WAL settings
            ("wal_buffers", "16MB", "WAL buffer size"),
            ("checkpoint_completion_target", "0.9", "Checkpoint spread"),
            # Query planner
            ("random_page_cost", "4", "Lower for SSD (1.1-2.0)"),
            ("effective_io_concurrency", "200", "Higher for SSD"),
            # Parallel query
            ("max_parallel_workers_per_gather", "2", "Parallel query workers"),
            ("max_worker_processes", "8", "Background workers"),
            # Logging
            ("log_min_duration_statement", "-1", "Slow query logging (ms)"),
        ]

        self.stdout.write(self.style.WARNING("\n  Key Performance Settings:"))
        self.stdout.write("  " + "-" * 70)

        with connection.cursor() as cursor:
            for setting, default, description in settings_to_check:
                try:
                    cursor.execute(
                        "SELECT setting, unit FROM pg_settings WHERE name = %s",
                        [setting],
                    )
                    result = cursor.fetchone()
                    if result:
                        value, unit = result
                        unit_str = f" {unit}" if unit else ""
                        self.stdout.write(f"  {setting:40} = {value}{unit_str}")
                    else:
                        self.stdout.write(f"  {setting:40} = (not found)")
                except Exception as e:
                    self.stdout.write(f"  {setting:40} = ERROR: {e}")

        # Check for Docker-specific issues
        self.stdout.write(self.style.WARNING("\n  Docker/Container Detection:"))
        with connection.cursor() as cursor:
            # Check data directory
            cursor.execute("SHOW data_directory")
            data_dir = cursor.fetchone()[0]
            self.stdout.write(f"     Data directory: {data_dir}")

            # Check if running in container (common paths)
            if "/var/lib/postgresql/data" in data_dir:
                self.stdout.write(
                    self.style.WARNING(
                        "     [PKG] Appears to be running in a container"
                    )
                )

            # Check filesystem sync setting
            cursor.execute("SHOW fsync")
            fsync = cursor.fetchone()[0]
            self.stdout.write(f"     fsync: {fsync}")
            if fsync == "off":
                self.stdout.write(
                    self.style.ERROR(
                        "     [WARN]️  fsync is OFF - data durability at risk!"
                    )
                )

            # Check synchronous_commit
            cursor.execute("SHOW synchronous_commit")
            sync_commit = cursor.fetchone()[0]
            self.stdout.write(f"     synchronous_commit: {sync_commit}")

        # Memory comparison
        self.stdout.write(self.style.WARNING("\n  Memory Analysis:"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    pg_size_pretty(pg_database_size(current_database())) as db_size,
                    current_setting('shared_buffers') as shared_buffers,
                    current_setting('effective_cache_size') as cache_size
            """
            )
            result = cursor.fetchone()
            self.stdout.write(f"     Database size: {result[0]}")
            self.stdout.write(f"     shared_buffers: {result[1]}")
            self.stdout.write(f"     effective_cache_size: {result[2]}")

    # =========================================================================
    # QUERY BENCHMARKS
    # =========================================================================
    def run_query_benchmarks(self):
        """Run various query benchmarks to measure performance."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO("[LAUNCH] QUERY BENCHMARKS"))
        self.stdout.write("=" * 80)

        benchmarks = []

        # 1. Simple SELECT
        self.stdout.write(
            self.style.WARNING("\n  1. Simple SELECT (SELECT 1) - 100 iterations:")
        )
        times = self._run_query_benchmark("SELECT 1", iterations=100)
        benchmarks.append(("Simple SELECT", times))
        self._print_benchmark_stats(times)

        # 2. Table COUNT
        self.stdout.write(self.style.WARNING("\n  2. Table COUNT - 20 iterations:"))
        times = self._run_query_benchmark(
            "SELECT COUNT(*) FROM core_decision", iterations=20
        )
        benchmarks.append(("COUNT(*)", times))
        self._print_benchmark_stats(times)

        # 3. Simple SELECT with WHERE (indexed)
        self.stdout.write(
            self.style.WARNING(
                "\n  3. SELECT with indexed WHERE (LIMIT 1) - 50 iterations:"
            )
        )
        times = self._run_query_benchmark(
            "SELECT id, ada, subject FROM core_decision WHERE ada IS NOT NULL LIMIT 1",
            iterations=50,
        )
        benchmarks.append(("Indexed SELECT", times))
        self._print_benchmark_stats(times)

        # 4. SELECT with ORDER BY
        self.stdout.write(
            self.style.WARNING("\n  4. SELECT with ORDER BY LIMIT - 30 iterations:")
        )
        times = self._run_query_benchmark(
            "SELECT id, ada, issue_date FROM core_decision ORDER BY issue_date DESC LIMIT 10",
            iterations=30,
        )
        benchmarks.append(("ORDER BY LIMIT", times))
        self._print_benchmark_stats(times)

        # 5. JOIN query
        self.stdout.write(self.style.WARNING("\n  5. JOIN Query - 20 iterations:"))
        times = self._run_query_benchmark(
            """
            SELECT d.id, d.ada, o.label
            FROM core_decision d
            LEFT JOIN core_organization o ON d.organization_id = o.uid
            LIMIT 10
            """,
            iterations=20,
        )
        benchmarks.append(("JOIN Query", times))
        self._print_benchmark_stats(times)

        # 6. Aggregate query
        self.stdout.write(
            self.style.WARNING("\n  6. Aggregate Query (GROUP BY) - 10 iterations:")
        )
        times = self._run_query_benchmark(
            """
            SELECT organization_id, COUNT(*) as cnt
            FROM core_decision
            WHERE organization_id IS NOT NULL
            GROUP BY organization_id
            ORDER BY cnt DESC
            LIMIT 10
            """,
            iterations=10,
        )
        benchmarks.append(("GROUP BY", times))
        self._print_benchmark_stats(times)

        # 7. Text search (if applicable)
        self.stdout.write(self.style.WARNING("\n  7. Text LIKE Query - 10 iterations:"))
        times = self._run_query_benchmark(
            "SELECT id, ada, subject FROM core_decision WHERE subject LIKE '%ΑΠΟΦΑΣΗ%' LIMIT 5",
            iterations=10,
        )
        benchmarks.append(("Text LIKE", times))
        self._print_benchmark_stats(times)

        # Summary comparison
        self.stdout.write(self.style.WARNING("\n  [CHART] Benchmark Summary:"))
        self.stdout.write("  " + "-" * 60)
        for name, times in benchmarks:
            if times:
                avg = statistics.mean(times)
                self.stdout.write(f"  {name:25} Avg: {avg:8.2f}ms")

    def _run_query_benchmark(self, query, iterations=50):
        """Run a query multiple times and return timing data."""
        times = []
        for _ in range(iterations):
            try:
                start = time.perf_counter()
                with connection.cursor() as cursor:
                    cursor.execute(query)
                    cursor.fetchall()
                elapsed = (time.perf_counter() - start) * 1000
                times.append(elapsed)
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"     Query failed: {e}"))
                break
        return times

    def _print_benchmark_stats(self, times):
        """Print statistics for benchmark times."""
        if not times:
            self.stdout.write("     No data")
            return
        self.stdout.write(
            f"     Min: {min(times):.2f}ms | Max: {max(times):.2f}ms | Avg: {statistics.mean(times):.2f}ms"
        )
        if len(times) > 1:
            self.stdout.write(
                f"     Std Dev: {statistics.stdev(times):.2f}ms | P95: {sorted(times)[int(len(times)*0.95)]:.2f}ms"
            )

    # =========================================================================
    # I/O BENCHMARKS
    # =========================================================================
    def run_io_benchmarks(self):
        """Test database I/O performance."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO("[SAVE] I/O PERFORMANCE TESTS"))
        self.stdout.write("=" * 80)

        # 1. Check buffer cache hit ratio
        self.stdout.write(self.style.WARNING("\n  1. Buffer Cache Hit Ratio:"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sum(heap_blks_read) as heap_read,
                    sum(heap_blks_hit) as heap_hit,
                    CASE WHEN sum(heap_blks_hit) + sum(heap_blks_read) > 0
                         THEN sum(heap_blks_hit) * 100.0 / (sum(heap_blks_hit) + sum(heap_blks_read))
                         ELSE 0 END as ratio
                FROM pg_statio_user_tables
            """
            )
            result = cursor.fetchone()
            heap_read, heap_hit, ratio = result
            self.stdout.write(f"     Heap blocks read from disk: {heap_read:,}")
            self.stdout.write(f"     Heap blocks hit in cache: {heap_hit:,}")
            self.stdout.write(f"     Cache hit ratio: {ratio:.2f}%")

            if ratio and ratio < 99:
                self.stdout.write(
                    self.style.WARNING(
                        f"\n     [WARN]️  Cache hit ratio {ratio:.2f}% < 99% - consider increasing shared_buffers"
                    )
                )

        # 2. Index usage stats
        self.stdout.write(self.style.WARNING("\n  2. Index Cache Hit Ratio:"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    sum(idx_blks_read) as idx_read,
                    sum(idx_blks_hit) as idx_hit,
                    CASE WHEN sum(idx_blks_hit) + sum(idx_blks_read) > 0
                         THEN sum(idx_blks_hit) * 100.0 / (sum(idx_blks_hit) + sum(idx_blks_read))
                         ELSE 0 END as ratio
                FROM pg_statio_user_indexes
            """
            )
            result = cursor.fetchone()
            idx_read, idx_hit, ratio = result
            self.stdout.write(f"     Index blocks read from disk: {idx_read:,}")
            self.stdout.write(f"     Index blocks hit in cache: {idx_hit:,}")
            self.stdout.write(f"     Cache hit ratio: {ratio:.2f}%")

        # 3. Sequential vs Index scans
        self.stdout.write(self.style.WARNING("\n  3. Sequential vs Index Scan Usage:"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    relname,
                    seq_scan,
                    seq_tup_read,
                    idx_scan,
                    idx_tup_fetch
                FROM pg_stat_user_tables
                WHERE seq_scan + COALESCE(idx_scan, 0) > 0
                ORDER BY seq_scan DESC
                LIMIT 5
            """
            )
            results = cursor.fetchall()
            self.stdout.write(
                f"     {'Table':<30} {'Seq Scans':>12} {'Idx Scans':>12} {'Seq/Idx Ratio':>15}"
            )
            self.stdout.write("     " + "-" * 70)
            for row in results:
                table, seq_scan, seq_read, idx_scan, idx_fetch = row
                idx_scan = idx_scan or 0
                ratio = f"{seq_scan/idx_scan:.2f}" if idx_scan > 0 else "∞"
                self.stdout.write(
                    f"     {table:<30} {seq_scan:>12,} {idx_scan:>12,} {ratio:>15}"
                )

        # 4. Table bloat estimate (simple check)
        self.stdout.write(self.style.WARNING("\n  4. Table Size Analysis (Top 5):"))
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    relname as table,
                    pg_size_pretty(pg_total_relation_size(relid)) as total_size,
                    pg_size_pretty(pg_relation_size(relid)) as table_size,
                    pg_size_pretty(pg_indexes_size(relid)) as index_size,
                    n_live_tup as live_rows,
                    n_dead_tup as dead_rows
                FROM pg_stat_user_tables
                ORDER BY pg_total_relation_size(relid) DESC
                LIMIT 5
            """
            )
            results = cursor.fetchall()
            self.stdout.write(
                f"     {'Table':<25} {'Total':>10} {'Data':>10} {'Index':>10} {'Dead Rows':>12}"
            )
            self.stdout.write("     " + "-" * 70)
            for row in results:
                table, total, data, idx, live, dead = row
                dead_pct = f"({dead*100/live:.1f}%)" if live > 0 else ""
                self.stdout.write(
                    f"     {table:<25} {total:>10} {data:>10} {idx:>10} {dead:>8,} {dead_pct}"
                )

    # =========================================================================
    # PG_STAT_STATEMENTS ANALYSIS
    # =========================================================================
    def run_pg_stat_statements_analysis(self):
        """Analyze slow queries from pg_stat_statements if available."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(self.style.HTTP_INFO("[METRIC] PG_STAT_STATEMENTS ANALYSIS"))
        self.stdout.write("=" * 80)

        with connection.cursor() as cursor:
            # Check if extension is available
            cursor.execute(
                """
                SELECT EXISTS (
                    SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements'
                )
            """
            )
            exists = cursor.fetchone()[0]

            if not exists:
                self.stdout.write(
                    self.style.WARNING(
                        "\n  [WARN]️  pg_stat_statements extension not installed"
                    )
                )
                self.stdout.write(
                    "     To enable: CREATE EXTENSION pg_stat_statements;"
                )
                self.stdout.write(
                    "     Also add to postgresql.conf: shared_preload_libraries = 'pg_stat_statements'"
                )
                return

            # Top 10 slowest queries by total time
            self.stdout.write(self.style.WARNING("\n  Top 10 Queries by Total Time:"))
            try:
                cursor.execute(
                    """
                    SELECT
                        LEFT(query, 80) as query,
                        calls,
                        ROUND(total_exec_time::numeric, 2) as total_ms,
                        ROUND(mean_exec_time::numeric, 2) as avg_ms,
                        ROUND(max_exec_time::numeric, 2) as max_ms,
                        rows
                    FROM pg_stat_statements
                    ORDER BY total_exec_time DESC
                    LIMIT 10
                """
                )
                results = cursor.fetchall()

                if results:
                    self.stdout.write(
                        f"\n     {'Query (truncated)':<50} {'Calls':>8} {'Total ms':>12} {'Avg ms':>10}"
                    )
                    self.stdout.write("     " + "-" * 85)
                    for row in results:
                        query, calls, total, avg, max_t, rows = row
                        query_short = query.replace("\n", " ")[:50]
                        self.stdout.write(
                            f"     {query_short:<50} {calls:>8,} {total:>12,.2f} {avg:>10,.2f}"
                        )
                else:
                    self.stdout.write("     No query statistics available yet")
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"     Error querying pg_stat_statements: {e}")
                )

    # =========================================================================
    # DIAGNOSTIC SUMMARY
    # =========================================================================
    def print_diagnostic_summary(self):
        """Print a summary of potential issues found."""
        self.stdout.write("\n" + "=" * 80)
        self.stdout.write(
            self.style.HTTP_INFO("[COPY] DIAGNOSTIC SUMMARY & RECOMMENDATIONS")
        )
        self.stdout.write("=" * 80)

        issues = []

        db_config = connections["default"].settings_dict
        host = db_config.get("HOST", "localhost")

        # Check if using Docker networking
        if host not in ("localhost", "127.0.0.1", "::1"):
            issues.append(
                {
                    "severity": "INFO",
                    "issue": f'Database host is "{host}" (not localhost)',
                    "impact": "Docker bridge networking adds ~0.5-2ms latency per query",
                    "fix": "Use host network mode for containers, or accept the latency overhead",
                }
            )

        # Check CONN_MAX_AGE
        conn_max_age = db_config.get("CONN_MAX_AGE", 0)
        if conn_max_age == 0:
            issues.append(
                {
                    "severity": "WARNING",
                    "issue": "CONN_MAX_AGE is 0 (connections not reused)",
                    "impact": "Each request pays ~5-20ms connection establishment overhead",
                    "fix": "Set CONN_MAX_AGE=60 or higher in Django settings",
                }
            )

        # Print issues
        if issues:
            for idx, issue in enumerate(issues, 1):
                severity = issue["severity"]
                style = (
                    self.style.ERROR
                    if severity == "ERROR"
                    else (
                        self.style.WARNING
                        if severity == "WARNING"
                        else self.style.HTTP_INFO
                    )
                )
                self.stdout.write(style(f"\n  {idx}. [{severity}] {issue['issue']}"))
                self.stdout.write(f"     Impact: {issue['impact']}")
                self.stdout.write(f"     Fix: {issue['fix']}")
        else:
            self.stdout.write(self.style.SUCCESS("\n  [OK] No obvious issues detected"))

        self.stdout.write(
            self.style.WARNING("\n  Common Docker PostgreSQL Performance Issues:")
        )
        self.stdout.write("  " + "-" * 60)
        self.stdout.write("  1. Volume mounts on macOS (Docker Desktop) are slow")
        self.stdout.write("     - Use named volumes instead of bind mounts for data")
        self.stdout.write("     - Consider using ':delegated' or ':cached' flags")
        self.stdout.write("")
        self.stdout.write("  2. Docker networking adds latency")
        self.stdout.write("     - Use 'host' network mode if possible")
        self.stdout.write("     - Or accept ~1-2ms overhead per query")
        self.stdout.write("")
        self.stdout.write("  3. Resource limits")
        self.stdout.write("     - Check Docker Desktop memory/CPU allocation")
        self.stdout.write("     - PostgreSQL needs RAM for shared_buffers")
        self.stdout.write("")
        self.stdout.write("  4. Default PostgreSQL config is conservative")
        self.stdout.write("     - Tune shared_buffers, work_mem, effective_cache_size")
        self.stdout.write("     - Use PGTune for recommendations")

    # =========================================================================
    # CONNECTION POOL LOAD TESTS (Original functionality)
    # =========================================================================
    def get_active_connections(self):
        """Get count of active database connections."""
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT
                    state,
                    COUNT(*) as count
                FROM pg_stat_activity
                WHERE datname = current_database()
                GROUP BY state
                ORDER BY count DESC
            """
            )
            results = cursor.fetchall()
            return {row[0] or "unknown": row[1] for row in results}

    def simulate_request(self, stats):
        """Simulate a single request to the health endpoint."""
        try:
            start = time.time()

            # Create a mock request object
            request = HttpRequest()
            request.method = "GET"

            # Call the health check view
            response = health_check(request)

            duration = time.time() - start

            if response.status_code == 200:
                stats.record_success(duration)
            else:
                stats.record_failure(f"HTTP {response.status_code}")

        except Exception as e:
            stats.record_failure(type(e).__name__)

    def run_test(self, test_name, num_requests, concurrent):
        """Run a load test with specified parameters."""
        self.stdout.write("\n" + "-" * 80)
        self.stdout.write(self.style.HTTP_INFO(f"\n{test_name}"))
        self.stdout.write(
            f"  Requests: {num_requests} | Concurrent Workers: {concurrent}\n"
        )

        # Check initial connection count
        initial_conns = self.get_active_connections()
        self.stdout.write(f"  Initial connections: {sum(initial_conns.values())}")
        self.stdout.write(f"    {initial_conns}")

        # Run the load test
        stats = LoadTestStats()
        start_time = time.time()

        threads = []
        for i in range(num_requests):
            # Control concurrency
            while len([t for t in threads if t.is_alive()]) >= concurrent:
                time.sleep(0.01)

            thread = threading.Thread(target=self.simulate_request, args=(stats,))
            thread.start()
            threads.append(thread)

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        total_time = time.time() - start_time

        # Check peak connection count immediately
        peak_conns = self.get_active_connections()

        # Get final stats
        final_stats = stats.get_stats()

        # Display results
        self.stdout.write(self.style.SUCCESS("\n  Results:"))
        self.stdout.write(f"    Total Time: {total_time:.2f}s")
        self.stdout.write(f"    Requests/sec: {num_requests/total_time:.2f}")
        self.stdout.write(f"    Successful: {final_stats['successful']}/{num_requests}")
        self.stdout.write(f"    Failed: {final_stats['failed']}/{num_requests}")
        self.stdout.write(f"    Response Times:")
        self.stdout.write(
            f"      Avg: {final_stats['avg_duration']*1000:.2f}ms | Min: {final_stats['min']*1000:.2f}ms | Max: {final_stats['max']*1000:.2f}ms"
        )
        self.stdout.write(
            f"      P50: {final_stats['p50']*1000:.2f}ms | P95: {final_stats['p95']*1000:.2f}ms | P99: {final_stats['p99']*1000:.2f}ms"
        )

        if final_stats["errors"]:
            self.stdout.write(self.style.ERROR("\n    Errors:"))
            for error, count in final_stats["errors"].items():
                self.stdout.write(f"      {error}: {count}")

        self.stdout.write(
            self.style.WARNING(f"\n  Peak connections: {sum(peak_conns.values())}")
        )
        self.stdout.write(f"    {peak_conns}")

        # Wait and check if connections persist
        self.stdout.write("\n  Waiting 5 seconds to check connection persistence...")
        time.sleep(5)
        final_conns = self.get_active_connections()
        self.stdout.write(f"  Connections after 5s: {sum(final_conns.values())}")
        self.stdout.write(f"    {final_conns}")

        # Analysis
        peak_count = sum(peak_conns.values())
        final_count = sum(final_conns.values())
        initial_count = sum(initial_conns.values())

        if final_count > initial_count + 2:  # Allow for 2 extra connections
            self.stdout.write(
                self.style.ERROR(
                    f"\n  [WARN]️  WARNING: Connections increased from {initial_count} to {final_count}"
                )
            )
            self.stdout.write(
                self.style.ERROR(
                    f"     This suggests connection pooling is active (CONN_MAX_AGE > 0)"
                )
            )

        if peak_count > concurrent + 5:  # Allow some overhead
            self.stdout.write(
                self.style.WARNING(
                    f"\n  [WARN]️  NOTICE: Peak connections ({peak_count}) >> concurrent workers ({concurrent})"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"     This could indicate connection leaks or multiple processes"
                )
            )
