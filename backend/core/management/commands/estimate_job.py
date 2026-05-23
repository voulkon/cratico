"""
Management command to estimate costs for AI jobs.

Usage:
    # Estimate daily_summary for today
    python manage.py estimate_job daily_summary --provider AWS_BEDROCK --model anthropic.claude-3-haiku-20240307-v1:0

    # Estimate with date range
    python manage.py estimate_job daily_summary --start-date 2025-01-01 --end-date 2025-01-31

    # Estimate high_value_analysis with custom threshold
    python manage.py estimate_job high_value_analysis --min-amount 50000 --limit 100

    # Show per-item breakdown
    python manage.py estimate_job daily_summary --verbose
"""

from datetime import datetime
from decimal import Decimal

from core.jobs.base import load_job_class
from core.models.ai_pricing import AIJobDefinition
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Estimate AI job costs before running"

    def add_arguments(self, parser):
        parser.add_argument("job_name", type=str, help="Job name to estimate")

        parser.add_argument(
            "--provider", type=str, help="AI provider (defaults to job default)"
        )
        parser.add_argument(
            "--model", type=str, help="Model name (defaults to job default)"
        )

        # Common filters
        parser.add_argument("--start-date", type=str, help="Start date (YYYY-MM-DD)")
        parser.add_argument("--end-date", type=str, help="End date (YYYY-MM-DD)")
        parser.add_argument(
            "--limit", type=int, help="Limit number of items to estimate"
        )

        # Job-specific kwargs
        parser.add_argument(
            "--target-date", type=str, help="Target date for daily_summary (YYYY-MM-DD)"
        )
        parser.add_argument(
            "--min-amount", type=float, help="Minimum amount for high_value_analysis"
        )
        parser.add_argument(
            "--decision-types", type=str, help="Comma-separated decision type UIDs"
        )
        parser.add_argument(
            "--organization-ids", type=str, help="Comma-separated organization UIDs"
        )

        # Output options
        parser.add_argument(
            "--verbose", action="store_true", help="Show per-item breakdown"
        )

    def handle(self, *args, **options):
        job_name = options["job_name"]
        verbose = options.get("verbose", False)

        # Load job definition
        try:
            job_def = AIJobDefinition.objects.get(job_name=job_name, is_active=True)
        except AIJobDefinition.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(f'Job "{job_name}" not found or not active')
            )
            return

        # Get provider and model
        provider = options.get("provider") or job_def.default_provider
        model = options.get("model") or job_def.default_model

        if not provider or not model:
            self.stdout.write(self.style.ERROR("Provider and model must be specified"))
            return

        # Build kwargs for job
        job_kwargs = {}

        # Parse dates
        if options.get("start_date"):
            job_kwargs["start_date"] = datetime.strptime(
                options["start_date"], "%Y-%m-%d"
            ).date()
        if options.get("end_date"):
            job_kwargs["end_date"] = datetime.strptime(
                options["end_date"], "%Y-%m-%d"
            ).date()
        if options.get("target_date"):
            job_kwargs["target_date"] = datetime.strptime(
                options["target_date"], "%Y-%m-%d"
            ).date()

        # Other filters
        if options.get("min_amount"):
            job_kwargs["min_amount"] = options["min_amount"]
        if options.get("decision_types"):
            job_kwargs["decision_types"] = [
                t.strip() for t in options["decision_types"].split(",")
            ]
        if options.get("organization_ids"):
            job_kwargs["organization_ids"] = [
                o.strip() for o in options["organization_ids"].split(",")
            ]

        # Load and instantiate job
        self.stdout.write(f'\n{"="*80}')
        self.stdout.write(self.style.SUCCESS(f"Estimating: {job_def.display_name}"))
        self.stdout.write(f'{"="*80}\n')

        self.stdout.write(f"Provider: {provider}")
        self.stdout.write(f"Model: {model}")
        self.stdout.write(f"Analysis Type: {job_def.analysis_type}")

        if job_kwargs:
            self.stdout.write(f"\nFilters:")
            for key, value in job_kwargs.items():
                self.stdout.write(f"  {key}: {value}")

        try:
            job_class = load_job_class(job_def)
            job = job_class(job_def)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"\nFailed to load job: {e}"))
            return

        # Get items to process
        self.stdout.write(f'\n{"-"*80}')
        self.stdout.write("Fetching items...\n")

        try:
            items = job.get_items_to_process(**job_kwargs)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Failed to fetch items: {e}"))
            import traceback

            traceback.print_exc()
            return

        if not items:
            self.stdout.write(self.style.WARNING("No items found to process"))
            return

        # Apply limit if specified
        limit = options.get("limit")
        if limit and len(items) > limit:
            self.stdout.write(
                self.style.WARNING(
                    f"Limiting to {limit} items (out of {len(items)} total)"
                )
            )
            items = items[:limit]

        self.stdout.write(self.style.SUCCESS(f"Found {len(items)} items to process\n"))

        # Run estimation
        self.stdout.write(f'{"-"*80}')
        self.stdout.write("Estimating costs...\n")

        total_input_tokens = 0
        total_output_tokens = 0
        total_cost = Decimal("0")
        item_details = []

        for i, item in enumerate(items, 1):
            # Check if should process
            if not job.should_process_item(item):
                if verbose:
                    self.stdout.write(f'{i}. {item["item_identifier"]} - SKIPPED')
                continue

            # Estimate this item
            try:
                result = job.process_item(
                    item=item,
                    provider=provider,
                    model=model,
                    dry_run=True,  # Just estimate
                )

                input_tokens = result.get("input_tokens", 0)
                output_tokens = result.get("output_tokens", 0)
                cost = result.get("estimated_cost_usd", Decimal("0"))

                total_input_tokens += input_tokens
                total_output_tokens += output_tokens
                total_cost += cost

                item_details.append(
                    {
                        "identifier": item["item_identifier"],
                        "input_tokens": input_tokens,
                        "output_tokens": output_tokens,
                        "cost": cost,
                    }
                )

                if verbose:
                    self.stdout.write(
                        f'{i}. {item["item_identifier"]}: '
                        f"{input_tokens:,} in + {output_tokens:,} out = ${float(cost):.4f}"
                    )

            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f'{i}. {item["item_identifier"]}: ERROR - {e}')
                )

        # Summary
        self.stdout.write(f'\n{"="*80}')
        self.stdout.write(self.style.SUCCESS("ESTIMATION SUMMARY"))
        self.stdout.write(f'{"="*80}\n')

        self.stdout.write(f"Items to process: {len(item_details)}")
        self.stdout.write(f"Total input tokens: {total_input_tokens:,}")
        self.stdout.write(f"Total output tokens: {total_output_tokens:,}")
        self.stdout.write(f"Total tokens: {total_input_tokens + total_output_tokens:,}")
        self.stdout.write(
            self.style.SUCCESS(f"\nEstimated cost: ${float(total_cost):.4f}")
        )

        # Show top 5 most expensive items
        if item_details and not verbose:
            self.stdout.write(f'\n{"-"*80}')
            self.stdout.write("Top 5 most expensive items:\n")

            sorted_items = sorted(item_details, key=lambda x: x["cost"], reverse=True)[
                :5
            ]
            for i, item in enumerate(sorted_items, 1):
                self.stdout.write(
                    f'{i}. {item["identifier"]}: '
                    f'{item["input_tokens"]:,} in + {item["output_tokens"]:,} out = ${float(item["cost"]):.4f}'
                )

        self.stdout.write(f'\n{"="*80}\n')
