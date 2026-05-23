import json
import os
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand
from experiments.strategies import StrategyRegistry
from experiments.testing import SampleTester


class Command(BaseCommand):
    help = "Test strategies on exported samples (filesystem) before DB testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--samples-dir",
            type=str,
            default="decision_samples",
            help="Directory with samples",
        )
        parser.add_argument("--strategy", type=str, help="Strategy to test")
        parser.add_argument(
            "--decision-type",
            type=str,
            help='Filter to specific decision type folder (e.g., "Β.2.1_ΕΓΚΡΙΣΗ ΔΑΠΑΝΗΣ")',
        )
        parser.add_argument(
            "--compare-all", action="store_true", help="Compare all strategies"
        )
        parser.add_argument(
            "--show-failures", action="store_true", help="Show failed cases"
        )
        parser.add_argument(
            "--list-strategies", action="store_true", help="List available strategies"
        )
        parser.add_argument(
            "--export-results",
            action="store_true",
            help="Export extraction results to JSON files for review",
        )
        parser.add_argument(
            "--export-dir",
            type=str,
            default="extraction_results",
            help="Directory for exported results",
        )

    def handle(self, *args, **options):
        samples_dir = options["samples_dir"]

        # List available strategies
        if options["list_strategies"]:
            strategies = StrategyRegistry.list_names()
            self.stdout.write(self.style.SUCCESS("Available strategies:"))
            for name in strategies:
                self.stdout.write(f"  - {name}")
            return

        if not os.path.exists(samples_dir):
            self.stdout.write(self.style.ERROR(f"Directory not found: {samples_dir}"))
            self.stdout.write("Run 'python manage.py export_samples' first")
            return

        # Get all available strategies
        strategies_map = StrategyRegistry.get_all()

        if not strategies_map:
            self.stdout.write(self.style.ERROR("No strategies found!"))
            return

        tester = SampleTester(
            samples_dir, decision_type_filter=options.get("decision_type")
        )

        # Show what we're testing
        if options.get("decision_type"):
            self.stdout.write(f"Filtering to decision type: {options['decision_type']}")

        if options["compare_all"]:
            # Test all strategies
            strategies = [cls() for cls in strategies_map.values()]
            results = tester.compare_strategies(strategies)

            self.stdout.write(
                self.style.WARNING("\n=== STRATEGY COMPARISON (Filesystem Test) ===\n")
            )
            for result in results:
                self.stdout.write(
                    f"{result['strategy']:25} | "
                    f"Success: {result['success_rate']:5.1f}% | "
                    f"{result['successful']}/{result['total']} passed"
                )

        else:
            # Test single strategy
            strategy_name = options.get("strategy")
            if not strategy_name:
                # Default to first available
                strategy_name = list(strategies_map.keys())[0]
                self.stdout.write(f"No strategy specified, using: {strategy_name}")

            if strategy_name not in strategies_map:
                self.stdout.write(
                    self.style.ERROR(f"Unknown strategy: {strategy_name}")
                )
                self.stdout.write(f"Available: {', '.join(strategies_map.keys())}")
                return

            strategy = strategies_map[strategy_name]()
            result = tester.test_strategy(strategy)

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n{strategy.name} Test Results:\n"
                    f"Success: {result['successful']}/{result['total']} ({result['success_rate']:.1f}%)\n"
                    f"Failed:  {result['failed']}"
                )
            )

            # Export results if requested
            if options["export_results"]:
                export_dir = options["export_dir"]
                self._export_results(result, strategy.name, export_dir, samples_dir)
                self.stdout.write(
                    self.style.SUCCESS(f"\n[OK] Results exported to {export_dir}/")
                )

            # Show failures if requested
            if options["show_failures"] and result["failed"] > 0:
                failures = tester.get_failures(strategy, limit=10)
                self.stdout.write("\n" + self.style.WARNING("Sample Failures:"))
                for f in failures:
                    self.stdout.write(f"  {f.ada}: {f.error}")

        self.stdout.write(
            self.style.SUCCESS(
                "\n[OK] Filesystem testing complete. Ready for DB testing with 'run_experiment'"
            )
        )

    def _export_results(
        self, test_result: dict, strategy_name: str, export_dir: str, samples_dir: str
    ):
        """Export extraction results to JSON files for manual review."""
        # Create export directory structure
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(export_dir) / f"{strategy_name}_{timestamp}"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Summary file
        summary = {
            "strategy": strategy_name,
            "timestamp": timestamp,
            "total": test_result["total"],
            "successful": test_result["successful"],
            "failed": test_result["failed"],
            "success_rate": test_result["success_rate"],
            "results": [],
        }

        # Process each result
        for sample_result in test_result["results"]:
            ada = sample_result.ada

            # Load original decision data from samples
            original_data = self._load_original_data(ada, samples_dir)

            result_entry = {
                "ada": ada,
                "success": sample_result.success,
                "extracted": sample_result.data if sample_result.success else None,
                "error": sample_result.error,
                "original_metadata": {
                    "subject": original_data.get("subject"),
                    "amount": original_data.get("amounts", {}).get("calculated_total"),
                    "organization": original_data.get("organization", {}).get("label"),
                    "decision_type": original_data.get("decision_type", {}).get(
                        "label"
                    ),
                },
            }

            summary["results"].append(result_entry)

            # Export individual detailed file for successful extractions
            if sample_result.success:
                detail_file = output_dir / f"{ada}.json"
                with open(detail_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "ada": ada,
                            "extraction": {
                                "success": True,
                                "data": sample_result.data,
                            },
                            "original": original_data,
                            "comparison": {
                                "has_purpose": bool(sample_result.data.get("purpose")),
                                "has_beneficiary": bool(
                                    sample_result.data.get("beneficiary_name")
                                ),
                                "extracted_amount": sample_result.data.get(
                                    "total_amount"
                                ),
                                "api_amount": original_data.get("amounts", {}).get(
                                    "calculated_total"
                                ),
                                "amounts_match": self._amounts_match(
                                    sample_result.data.get("total_amount"),
                                    original_data.get("amounts", {}).get(
                                        "calculated_total"
                                    ),
                                ),
                            },
                        },
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

        # Write summary file
        summary_file = output_dir / "summary.json"
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        # Create a human-readable report
        report_file = output_dir / "report.txt"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(f"{'='*80}\n")
            f.write(f"EXTRACTION RESULTS REPORT\n")
            f.write(f"Strategy: {strategy_name}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"{'='*80}\n\n")

            f.write(f"Overall Results:\n")
            f.write(f"  Total: {test_result['total']}\n")
            f.write(
                f"  Successful: {test_result['successful']} ({test_result['success_rate']:.1f}%)\n"
            )
            f.write(f"  Failed: {test_result['failed']}\n\n")

            f.write(f"{'='*80}\n")
            f.write(f"SUCCESSFUL EXTRACTIONS\n")
            f.write(f"{'='*80}\n\n")

            for result in summary["results"]:
                if result["success"]:
                    f.write(f"ADA: {result['ada']}\n")
                    f.write(
                        f"Original Subject: {result['original_metadata']['subject']}\n"
                    )

                    extracted = result["extracted"]
                    if extracted:
                        f.write(
                            f"Extracted Purpose: {extracted.get('purpose', 'N/A')}\n"
                        )
                        f.write(
                            f"Extracted Beneficiary: {extracted.get('beneficiary_name', 'N/A')}\n"
                        )
                        f.write(
                            f"Extracted Amount: {extracted.get('total_amount', 'N/A')}\n"
                        )
                        f.write(
                            f"API Amount: {result['original_metadata']['amount']}\n"
                        )
                        f.write(
                            f"Confidence: {extracted.get('confidence_score', 'N/A')}\n"
                        )
                    f.write(f"\n{'-'*80}\n\n")

            if test_result["failed"] > 0:
                f.write(f"\n{'='*80}\n")
                f.write(f"FAILED EXTRACTIONS\n")
                f.write(f"{'='*80}\n\n")

                for result in summary["results"]:
                    if not result["success"]:
                        f.write(f"ADA: {result['ada']}\n")
                        f.write(f"Error: {result['error']}\n")
                        f.write(f"Subject: {result['original_metadata']['subject']}\n")
                        f.write(f"\n{'-'*80}\n\n")

    def _load_original_data(self, ada: str, samples_dir: str) -> dict:
        """Load original decision data from samples directory."""
        # Search for the JSON file in all subdirectories
        for root, dirs, files in os.walk(samples_dir):
            if f"{ada}.json" in files:
                json_path = os.path.join(root, f"{ada}.json")
                with open(json_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        return {}

    def _amounts_match(
        self, extracted: float, api: float, tolerance: float = 0.01
    ) -> bool:
        """Check if extracted amount matches API amount within tolerance."""
        if extracted is None or api is None:
            return False
        return abs(float(extracted) - float(api)) < tolerance
