import os
from datetime import date, datetime, timedelta

import requests
from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.importers.decisions import DecisionImporter
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.decision_analysis_service import DecisionAnalysisService
from core.services.decision_ingestion_service import DecisionIngestionService
from django.core.management.base import BaseCommand
from django.utils import timezone
from loguru import logger


class Command(BaseCommand):
    help = "Sync decisions for a specific day with reconciliation"

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=lambda s: datetime.strptime(s, "%Y-%m-%d").date(),
            help="Date to sync (YYYY-MM-DD). Defaults to yesterday.",
        )
        parser.add_argument(
            "--incremental",
            action="store_true",
            help="Use incremental sync based on last timestamp",
        )
        parser.add_argument(
            "--reconcile",
            action="store_true",
            help="Compare results with official API counts",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force sync even if already completed for this date",
        )
        parser.add_argument(
            "--distributed",
            action="store_true",
            default=True,
            help="Use Celery for distributed processing (DEFAULT, recommended)",
        )
        parser.add_argument(
            "--no-distributed",
            dest="distributed",
            action="store_false",
            help="[DEPRECATED] Use old single-process mode (not recommended)",
        )
        parser.add_argument(
            "--file-log",
            action="store_true",
            help="Enable logging to file (default: logs only go to stdout)",
        )

    def handle(self, *args, **options):
        # Setup file logging for this import run
        target_date = options.get("date") or (date.today() - timedelta(days=1))
        force = options.get("force", False)
        file_log = options.get("file_log", False)
        log_file = None

        if file_log:
            log_dir = "/code/logs"
            os.makedirs(log_dir, exist_ok=True)

            log_file = f"{log_dir}/import_decisions_{target_date.strftime('%Y%m%d')}_{datetime.now().strftime('%H%M%S')}.log"

            # Configure loguru to write to file
            logger.add(
                log_file,
                rotation="100 MB",
                retention="30 days",
                level="INFO",
                format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level} | {name}:{function}:{line} - {message}",
                compression="gz",
            )

        log_msg = f"Starting import for {target_date} (force={force}, distributed={options['distributed']})"
        if log_file:
            log_msg += f" - Logs will be saved to: {log_file}"
        logger.info(log_msg)

        # Show deprecation warning for non-distributed mode
        if not options["distributed"]:
            warning_msg = (
                "[WARN]️  WARNING: Non-distributed mode is DEPRECATED and will be removed in a future version.\n"
                "   The distributed mode (default) is the recommended single source of truth.\n"
                "   It uses Redis-based pipeline with proper tracking and parallel processing."
            )
            logger.warning(warning_msg)
            self.stdout.write(self.style.WARNING(warning_msg))

        self.stdout.write(
            f"Starting sync for {target_date} (force={force}, distributed={options['distributed']})"
        )
        if log_file:
            self.stdout.write(f"Logs are being saved to: {log_file}")

        # Create ImportJob immediately for all modes (distributed and non-distributed)
        # This gives instant visibility regardless of execution mode
        import_job = ImportJob.objects.create(
            start_date=target_date,
            end_date=target_date,
            status=(
                ImportJobStatus.PENDING
                if options["distributed"]
                else ImportJobStatus.RUNNING
            ),
            created_by=None,  # Management command has no user
            search_params={"force": force, "distributed": options["distributed"]},
        )
        logger.info(f"Created ImportJob #{import_job.id} for {target_date}")
        self.stdout.write(f"[CHART] ImportJob #{import_job.id} created for tracking")

        # Create service components with ImportJob linkage
        fetcher = DiavgeiaFetcher()
        decision_importer = DecisionImporter(import_job=import_job)
        service = DecisionIngestionService(
            diavgeia_fetcher=fetcher,
            decision_importer=decision_importer,
        )

        try:
            if options["incremental"]:
                # Use incremental sync
                logger.info("Starting incremental sync")
                result = service.fetch_decisions_since_timestamp(save_to_db=True)
                logger.info(
                    f"Incremental sync completed. Processed {result['processed_count']} decisions."
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Incremental sync completed. Processed {result['processed_count']} decisions."
                    )
                )
            else:
                # Check if we should use the new distributed approach
                if options["distributed"]:
                    # Use ImportJobQueue to respect concurrency limits and queue management
                    from core.services.import_job_queue import ImportJobQueue

                    logger.info(
                        f"Starting distributed sync for {target_date} (force={force})"
                    )

                    # Delete the ImportJob we pre-created since ImportJobQueue will create it
                    import_job.delete()

                    # Use ImportJobQueue to create and dispatch the job properly
                    queue = ImportJobQueue()
                    search_params = {"force": force}

                    import_job = queue.enqueue_job(
                        target_date=target_date,
                        search_params=search_params,
                        created_by=None,  # Management command has no user
                        auto_dispatch=True,  # Auto-dispatch if capacity available
                    )

                    logger.info(
                        f"Queued ImportJob #{import_job.id} for {target_date} "
                        f"(status: {import_job.status})"
                    )

                    status_msg = (
                        f"ImportJob #{import_job.id} queued for {target_date}\n"
                        f"Status: {import_job.status}"
                    )

                    if import_job.status == ImportJobStatus.PENDING:
                        status_msg += (
                            "\n Job queued - will start when capacity available"
                        )
                    elif import_job.celery_task_id:
                        status_msg += (
                            f"\n Job dispatched - Task ID: {import_job.celery_task_id}"
                        )

                    self.stdout.write(self.style.SUCCESS(status_msg))

                    self.stdout.write(f"\nThe system will:")
                    self.stdout.write(
                        f"  1. Fetch all decisions for {target_date} (via Diavgeia API)"
                    )
                    self.stdout.write(
                        f"  2. Store in Redis and split into parallel storage tasks"
                    )
                    self.stdout.write(
                        f"  3. Each storage task runs through full pipeline (orgs, entities, opensearch, etc.)"
                    )
                    self.stdout.write(
                        f"\nMonitor progress: Decision Management → Import Jobs Monitor"
                    )
                    self.stdout.write(
                        f"[INFO] Tip: ImportJob #{import_job.id} status: PENDING → FETCHING → SPLITTING → PROCESSING → COMPLETED"
                    )

                    # Return early since we can't get result without backend
                    result = {
                        "status": "queued",
                        "processed_count": "pending",
                        "task_id": import_job.celery_task_id,
                        "job_id": import_job.id,
                        "job_status": import_job.status,
                    }
                else:
                    # Use traditional single-process approach with batching
                    logger.info(f"Starting single-process sync for {target_date}")
                    result = service.fetch_daily_decisions(
                        target_date=target_date,
                        save_to_db=True,
                        want_it_distributed=False,  # Force local processing
                    )
                    logger.info(
                        f"Single-process sync completed for {target_date}. Processed {result['processed_count']} decisions."
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Single-process sync completed for {target_date}. Processed {result['processed_count']} decisions."
                        )
                    )

            # Update ImportJob with results (only for non-distributed mode)
            # In distributed mode, the tasks will update the job automatically
            if import_job and not options["distributed"]:
                import_job.status = ImportJobStatus.COMPLETED
                import_job.completed_at = timezone.now()
                import_job.total_decisions = (
                    result.get("processed_count", 0)
                    if isinstance(result.get("processed_count"), int)
                    else 0
                )
                import_job.save()
                logger.info(f"ImportJob #{import_job.id} marked as COMPLETED")

                # Reconciliation (only for non-distributed)
                if options["reconcile"]:
                    logger.info("Starting reconciliation")
                    self._reconcile_counts(target_date, result["processed_count"])

                if log_file:
                    logger.info(
                        f"Import process completed successfully. Check logs at: {log_file}"
                    )
                    self.stdout.write(
                        f"Import completed. Full logs available at: {log_file}"
                    )
                else:
                    logger.info(f"Import process completed successfully.")
                    self.stdout.write(f"Import completed.")
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] ImportJob #{import_job.id}: View in admin for batch health status"
                    )
                )
            elif options["distributed"]:
                logger.info(
                    f"Distributed import dispatched successfully. "
                    f"Monitor progress in 'Decision Management → [IMPORT] Import Jobs Monitor'"
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[OK] Distributed import running in background. "
                        f"Check 'Import Jobs Monitor' for progress."
                    )
                )

        except Exception as e:
            logger.error(f"Import process failed: {str(e)}", exc_info=True)

            # Mark ImportJob as failed
            try:
                import_job.status = ImportJobStatus.FAILED
                import_job.error_details = str(e)
                import_job.save()
                logger.error(f"ImportJob #{import_job.id} marked as FAILED")
            except:
                pass

            self.stdout.write(self.style.ERROR(f"Sync failed: {str(e)}"))
            if log_file:
                self.stdout.write(f"Check detailed error logs at: {log_file}")
            raise

    def _reconcile_counts(self, target_date: date, our_count: int):
        """Compare our counts with official API and show detailed analysis"""
        try:
            # Get official counts
            response = requests.get(
                "https://diavgeia.gov.gr/static/api/search/countPerDayLastMonth",
                timeout=30,
            )
            response.raise_for_status()

            official_data = response.json()

            # Find count for our target date
            target_timestamp = target_date.strftime("%Y-%m-%dT00:00:00Z")
            official_count = None

            for item in official_data.get("facetsResults", []):
                if item["label"] == target_timestamp:
                    official_count = item["counter"]
                    break

            if official_count is not None:
                difference = our_count - official_count
                percentage_diff = (
                    (difference / official_count * 100) if official_count > 0 else 0
                )

                self.stdout.write(f"Reconciliation for {target_date}:")
                self.stdout.write(f"  Official count: {official_count}")
                self.stdout.write(f"  Our count: {our_count}")
                self.stdout.write(
                    f"  Difference: {difference} ({percentage_diff:.2f}%)"
                )

                if abs(percentage_diff) > 5:  # More than 5% difference
                    self.stdout.write(
                        self.style.WARNING(
                            f"Large discrepancy detected! Consider investigating."
                        )
                    )

                    # Show detailed analysis for large discrepancies
                    self._show_detailed_analysis(target_date)
                else:
                    self.stdout.write(
                        self.style.SUCCESS("Counts are reasonably aligned.")
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(f"No official count found for {target_date}")
                )

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Reconciliation failed: {str(e)}"))

    def _show_detailed_analysis(self, target_date: date):
        """Show detailed analysis when discrepancies are found"""
        try:
            analysis_service = DecisionAnalysisService()
            analysis = analysis_service.get_daily_decision_analysis(target_date)

            if not analysis["has_data"]:
                self.stdout.write("  No decisions found in local database")
                return

            self.stdout.write("\n  Detailed Analysis:")
            self.stdout.write(f"    Total decisions: {analysis['total_count']}")

            # Show top 3 organizations
            if analysis["top_organizations"]:
                self.stdout.write("    Top organizations:")
                for i, org in enumerate(analysis["top_organizations"][:3], 1):
                    self.stdout.write(
                        f"      {i}. {org['organization__label']}: {org['count']} decisions"
                    )

            # Show top 3 types
            if analysis["top_types"]:
                self.stdout.write("    Top decision types:")
                for i, act_type in enumerate(analysis["top_types"][:3], 1):
                    self.stdout.write(
                        f"      {i}. {act_type['type__label']}: {act_type['count']} decisions"
                    )

            # Show quality indicators
            quality = analysis["quality_indicators"]
            self.stdout.write(
                f"    Data completeness: {quality['completeness_score']}%"
            )

            if quality["missing_subject_count"] > 0:
                self.stdout.write(
                    f"    Missing subjects: {quality['missing_subject_count']}"
                )
            if quality["missing_organization_count"] > 0:
                self.stdout.write(
                    f"    Missing organizations: {quality['missing_organization_count']}"
                )

        except Exception as e:
            self.stdout.write(f"    Failed to get detailed analysis: {str(e)}")
