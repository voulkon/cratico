"""
Test strategies on exported samples (filesystem) before running on DB.
This allows rapid iteration without touching the database.
"""

import json
import os
from typing import Any, Dict, List

from experiments.strategies.base import DecompositionStrategy


class SampleTestResult:
    def __init__(self, ada: str, success: bool, data: Dict = None, error: str = None):
        self.ada = ada
        self.success = success
        self.data = data or {}
        self.error = error


class SampleTester:
    """Test strategies on exported samples directory"""

    def __init__(self, samples_dir: str, decision_type_filter: str = None):
        self.samples_dir = samples_dir
        self.decision_type_filter = decision_type_filter

    def test_strategy(self, strategy: DecompositionStrategy) -> Dict[str, Any]:
        """
        Test a strategy on all exported samples.
        Returns summary and detailed results.
        """
        results = []

        # Walk through the samples directory
        for type_folder in os.listdir(self.samples_dir):
            type_path = os.path.join(self.samples_dir, type_folder)
            if not os.path.isdir(type_path):
                continue

            # Filter by decision type if specified
            if (
                self.decision_type_filter
                and self.decision_type_filter not in type_folder
            ):
                continue

            # Find all .json files (decision data)
            for filename in os.listdir(type_path):
                if not filename.endswith(".json"):
                    continue

                ada = filename.replace(".json", "")
                json_path = os.path.join(type_path, filename)

                # Read combined JSON data
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    # Get text from JSON (new format) or fall back to .txt file (old format)
                    text = data.get("text", "")
                    if not text:
                        # Try to read from separate .txt file (backward compatibility)
                        txt_path = os.path.join(type_path, f"{ada}.txt")
                        if os.path.exists(txt_path):
                            with open(txt_path, "r", encoding="utf-8") as f:
                                text = f.read()

                    # Create a mock decision object with accurate metadata
                    mock_decision = type(
                        "Decision",
                        (),
                        {
                            "ada": data.get("ada", ada),
                            "subject": data.get("subject", ""),
                            "amount": data.get("amounts", {}).get("calculated_total"),
                            "decision_type": data.get("decision_type", {}),
                            "organization": data.get("organization", {}),
                        },
                    )()

                    # Test strategy
                    result = strategy.decompose(mock_decision, text)
                    results.append(
                        SampleTestResult(
                            ada=ada,
                            success=result.success,
                            data=result.data,
                            error=result.error,
                        )
                    )
                except Exception as e:
                    results.append(
                        SampleTestResult(
                            ada=ada,
                            success=False,
                            error=f"Failed to process file: {str(e)}",
                        )
                    )

        # Calculate summary
        total = len(results)
        successful = sum(1 for r in results if r.success)
        failed = total - successful
        success_rate = (successful / total * 100) if total > 0 else 0

        return {
            "strategy": strategy.name,
            "total": total,
            "successful": successful,
            "failed": failed,
            "success_rate": success_rate,
            "results": results,
        }

    def compare_strategies(
        self, strategies: List[DecompositionStrategy]
    ) -> List[Dict[str, Any]]:
        """Run multiple strategies and compare results"""
        comparisons = []

        for strategy in strategies:
            print(f"Testing {strategy.name}...")
            result = self.test_strategy(strategy)
            comparisons.append(result)

        # Sort by success rate
        comparisons.sort(key=lambda x: x["success_rate"], reverse=True)
        return comparisons

    def get_failures(
        self, strategy: DecompositionStrategy, limit: int = 10
    ) -> List[SampleTestResult]:
        """Get failed cases for analysis"""
        result = self.test_strategy(strategy)
        failures = [r for r in result["results"] if not r.success]
        return failures[:limit]
