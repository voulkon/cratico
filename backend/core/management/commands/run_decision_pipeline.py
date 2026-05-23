from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Runs the comprehensive decision processing pipeline for specified decisions."
    )

    def add_arguments(self, parser):
        parser.add_argument("adas", nargs="*", type=str, help="List of ADAs to process")
        parser.add_argument(
            "--file", type=str, help="Path to file containing ADAs (one per line)"
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Limit the number of decisions to process",
        )
        parser.add_argument(
            "--failed-only",
            action="store_true",
            help="Process only decisions with known errors in health check",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-processing of steps even if successful",
        )
        parser.add_argument(
            "--import-job-id",
            type=int,
            default=None,
            help="Process all decisions linked to this ImportJob id",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=10,
            help="Parallel workers for --import-job-id processing",
        )
        parser.add_argument(
            "--stop-on-error",
            action="store_true",
            help="Stop batch processing on first error",
        )

    def handle(self, *args, **options):
        orchestrator = DecisionPipelineOrchestrator()
        adas = options["adas"]

        if options.get("import_job_id"):
            report = orchestrator.run_batch_pipeline(
                import_job_id=options["import_job_id"],
                max_workers=options["workers"],
                stop_on_error=options["stop_on_error"],
                force_reprocess=options["force"],
            )
            self.stdout.write(self.style.SUCCESS("Batch pipeline completed."))
            self.stdout.write(str(report))
            return

        if options["file"]:
            with open(options["file"], "r") as f:
                adas.extend([line.strip() for line in f if line.strip()])

        if options["failed_only"]:
            failed_checks = DecisionHealthCheck.objects.filter(
                overall_status=HealthStatus.ERROR
            )
            if options["limit"]:
                failed_checks = failed_checks[: options["limit"]]

            failed_adas = [check.decision.ada for check in failed_checks]
            self.stdout.write(f"Found {len(failed_adas)} failed decisions to retry.")
            adas.extend(failed_adas)

        # Remove duplicates
        adas = list(set(adas))

        if not adas:
            self.stdout.write(
                self.style.WARNING(
                    "No ADAs provided. Use args, --file, or --failed-only."
                )
            )
            return

        self.stdout.write(f"Starting pipeline for {len(adas)} decisions...")

        success_count = 0
        failure_count = 0

        for i, ada in enumerate(adas):
            self.stdout.write(f"[{i+1}/{len(adas)}] Processing {ada}...")
            try:
                health_check = orchestrator.run_pipeline(
                    ada, force_reprocess=options["force"]
                )
                if health_check and health_check.overall_status == HealthStatus.HEALTHY:
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f"  [OK] {ada} processed successfully")
                    )
                else:
                    failure_count += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"  [ERROR] {ada} failed (Status: {health_check.overall_status if health_check else 'None'})"
                        )
                    )
            except Exception as e:
                failure_count += 1
                self.stdout.write(
                    self.style.ERROR(f"  [CRASH] Exception processing {ada}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"\nPipeline finished. Success: {success_count}, Failed: {failure_count}"
            )
        )
