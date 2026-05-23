import json

from core.models.decisions import Decision
from core.services.extractor_comparison import ExtractorComparison
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Compare different text extractors on the same documents"

    def add_arguments(self, parser):
        parser.add_argument(
            "--ada", type=str, help="Compare extractors on a specific decision by ADA"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=5,
            help="Number of documents to compare (when not using --ada)",
        )
        parser.add_argument(
            "--include-async",
            action="store_true",
            help="Include async extractors like Docling (requires worker)",
        )
        parser.add_argument(
            "--output-file",
            type=str,
            help="Save detailed results to JSON file",
        )

    def handle(self, *args, **options):
        comparison_service = ExtractorComparison()
        ada = options.get("ada")
        limit = options["limit"]
        include_async = options.get("include_async", False)
        output_file = options.get("output_file")

        if include_async:
            self.stdout.write(
                self.style.WARNING(
                    "[WARN]️  Async mode enabled - this will trigger worker tasks"
                )
            )

        if ada:
            # Compare single document
            try:
                decision = Decision.objects.get(ada=ada)
                self.stdout.write(f"Comparing extractors for {decision.ada}")

                results = comparison_service.compare_extractors(
                    decision, include_async=include_async
                )
                self._display_results(results)

                if output_file:
                    self._save_results([results], output_file)

            except Decision.DoesNotExist:
                self.stdout.write(
                    self.style.ERROR(f"Decision with ADA {ada} not found")
                )
        else:
            # Compare multiple documents
            decisions = Decision.objects.filter(document_url__isnull=False).exclude(
                document_url=""
            )[:limit]

            self.stdout.write(f"Comparing extractors on {len(decisions)} documents")

            all_results = []
            for decision in decisions:
                self.stdout.write(f"\n--- Comparing {decision.ada} ---")
                results = comparison_service.compare_extractors(
                    decision, include_async=include_async
                )
                self._display_results(results)
                all_results.append(results)

            if output_file:
                self._save_results(all_results, output_file)

            # Summary statistics
            self._display_summary(all_results)

    def _display_results(self, results):
        """Display results for a single document"""
        if "error" in results:
            self.stdout.write(self.style.ERROR(f"Error: {results['error']}"))
            return

        for extractor_name, data in results["extractions"].items():
            extraction_type = data.get("extraction_type", "unknown")
            type_indicator = "[RETRY]" if extraction_type == "async" else "[CRIT]"

            if data["success"]:
                self.stdout.write(
                    f"  {type_indicator} {extractor_name}: {data['text_length']} chars, "
                    f"{data['page_count']} pages, {data['processing_time_ms']}ms"
                )
            else:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {type_indicator} {extractor_name}: FAILED - {data['error']}"
                    )
                )

        # Show comparison metrics
        comparison = results.get("comparison", {})
        if "fastest_extractor" in comparison:
            self.stdout.write(f"  Fastest: {comparison['fastest_extractor']}")

        if "sync_extractors" in comparison:
            self.stdout.write(
                f"  Sync extractors: {', '.join(comparison['sync_extractors'])}"
            )
        if "async_extractors" in comparison:
            self.stdout.write(
                f"  Async extractors: {', '.join(comparison['async_extractors'])}"
            )

    def _save_results(self, all_results, output_file):
        """Save results to JSON file"""
        with open(output_file, "w") as f:
            # Convert ExtractionResult objects to dicts for JSON serialization
            serializable_results = []
            for result in all_results:
                serializable_result = {}
                for key, value in result.items():
                    if key == "extractions":
                        serializable_result[key] = {}
                        for extractor_name, extractor_data in value.items():
                            serializable_result[key][extractor_name] = {}
                            for k, v in extractor_data.items():
                                if k == "result" and hasattr(v, "model_dump"):
                                    serializable_result[key][extractor_name][
                                        k
                                    ] = v.model_dump()
                                else:
                                    serializable_result[key][extractor_name][k] = v
                    else:
                        serializable_result[key] = value
                serializable_results.append(serializable_result)

            json.dump(serializable_results, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(f"Results saved to {output_file}"))

    def _display_summary(self, all_results):
        """Display summary statistics across all comparisons"""
        self.stdout.write(f"\n=== SUMMARY ===")

        successful_comparisons = [r for r in all_results if "error" not in r]
        self.stdout.write(
            f"Successful comparisons: {len(successful_comparisons)}/{len(all_results)}"
        )

        if not successful_comparisons:
            return

        # Aggregate performance stats
        extractor_stats = {}
        for result in successful_comparisons:
            for extractor_name, data in result["extractions"].items():
                if data["success"]:
                    if extractor_name not in extractor_stats:
                        extractor_stats[extractor_name] = {
                            "times": [],
                            "text_lengths": [],
                            "successes": 0,
                        }
                    extractor_stats[extractor_name]["times"].append(
                        data["processing_time_ms"]
                    )
                    extractor_stats[extractor_name]["text_lengths"].append(
                        data["text_length"]
                    )
                    extractor_stats[extractor_name]["successes"] += 1

        for extractor_name, stats in extractor_stats.items():
            avg_time = sum(stats["times"]) / len(stats["times"])
            avg_length = sum(stats["text_lengths"]) / len(stats["text_lengths"])
            self.stdout.write(
                f"{extractor_name}: {stats['successes']} successes, "
                f"avg {avg_time:.0f}ms, avg {avg_length:.0f} chars"
            )
