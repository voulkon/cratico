from core.models.decisions import Decision
from django.core.management.base import BaseCommand
from experiments.strategies import StrategyRegistry
from experiments.strategies.base import StrategyRunner


class Command(BaseCommand):
    help = "Run decomposition strategy experiments and compare results"

    def add_arguments(self, parser):
        parser.add_argument("--strategy", type=str, help="Strategy name")
        parser.add_argument(
            "--decision-type", type=str, help="Filter by decision type UID"
        )
        parser.add_argument("--sample-size", type=int, help="Limit sample size")
        parser.add_argument(
            "--list-strategies", action="store_true", help="List available strategies"
        )
        parser.add_argument(
            "--compare-all", action="store_true", help="Run all strategies and compare"
        )

    def handle(self, *args, **options):
        # List available strategies
        if options["list_strategies"]:
            strategies = StrategyRegistry.list_names()
            self.stdout.write(self.style.SUCCESS("Available strategies:"))
            for name in strategies:
                self.stdout.write(f"  - {name}")
            return

        # Get available strategies
        strategies_map = StrategyRegistry.get_all()

        if not strategies_map:
            self.stdout.write(self.style.ERROR("No strategies found!"))
            return

        # Build queryset
        queryset = Decision.objects.all()

        if options["decision_type"]:
            queryset = queryset.filter(decision_type__uid=options["decision_type"])

        if options["sample_size"]:
            queryset = queryset[: options["sample_size"]]

        total = queryset.count()
        self.stdout.write(f"Dataset: {total} decisions")

        if options["compare_all"]:
            # Run all strategies
            self.stdout.write(self.style.WARNING("\nRunning all strategies..."))
            runs = []
            for name, strategy_class in strategies_map.items():
                strategy = strategy_class()
                runner = StrategyRunner(strategy, version="1.0")
                self.stdout.write(f"\nRunning: {name}")
                run = runner.run_on_queryset(queryset, notes=f"Comparison run")
                runs.append(run)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK] {run.successful_count}/{run.total_decisions} "
                        f"({run.success_rate:.1f}%) in {run.duration_seconds:.1f}s"
                    )
                )

            # Show comparison
            self.stdout.write(self.style.WARNING("\n=== COMPARISON ==="))
            runs = sorted(runs, key=lambda r: r.success_rate or 0, reverse=True)
            for run in runs:
                self.stdout.write(
                    f"{run.strategy_name:20} | "
                    f"Success: {run.success_rate:5.1f}% | "
                    f"Time: {run.duration_seconds:6.1f}s | "
                    f"ID: {run.id}"
                )

        else:
            # Run single strategy
            strategy_name = options.get("strategy")
            if not strategy_name:
                strategy_name = list(strategies_map.keys())[0]
                self.stdout.write(f"No strategy specified, using: {strategy_name}")

            if strategy_name not in strategies_map:
                self.stdout.write(
                    self.style.ERROR(f"Unknown strategy: {strategy_name}")
                )
                self.stdout.write(f"Available: {', '.join(strategies_map.keys())}")
                return

            strategy = strategies_map[strategy_name]()
            runner = StrategyRunner(strategy, version="1.0")

            self.stdout.write(f"Running strategy: {strategy.name}")
            run = runner.run_on_queryset(queryset)

            self.stdout.write(
                self.style.SUCCESS(
                    f"\nCompleted in {run.duration_seconds:.1f}s\n"
                    f"Success: {run.successful_count}/{run.total_decisions} ({run.success_rate:.1f}%)\n"
                    f"Failed:  {run.failed_count}\n"
                    f"Run ID: {run.id}"
                )
            )

            # Show some failures for debugging
            if run.failed_count > 0:
                failures = run.results.filter(success=False)[:5]
                self.stdout.write("\nSample failures:")
                for result in failures:
                    self.stdout.write(
                        f"  {result.decision.ada}: {result.error_message[:100]}"
                    )
