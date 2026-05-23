"""
Complete a partially-completed import job by re-fetching missing decisions

This command identifies decisions that were fetched but never processed,
and re-dispatches them through the pipeline.

Usage:
    # Complete job 849 by finding missing decisions
    python manage.py complete_partial_import 849

    # Force re-fetch from API if decisions are not in DB
    python manage.py complete_partial_import 849 --refetch-from-api
"""

from core.fetchers.diavgeia_fetcher import DiavgeiaFetcher
from core.models.import_jobs import ImportJob, ImportJobStatus
from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator
from core.tasks.tasks_documents import run_decision_pipeline_task
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Complete a partially-completed import job"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int, help="ImportJob ID to complete")
        parser.add_argument(
            "--refetch-from-api",
            action="store_true",
            help="Re-fetch missing decisions from Diavgeia API",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without doing it",
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        refetch = options["refetch_from_api"]
        dry_run = options["dry_run"]

        # Get the import job
        try:
            job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            raise CommandError(f"ImportJob {job_id} does not exist")

        self.stdout.write(
            self.style.SUCCESS(f"\n=== Analyzing Import Job #{job.id} ===")
        )
        self.stdout.write(f"Status: {job.status}")
        self.stdout.write(f"Date: {job.start_date}")

        # Calculate what's missing
        total = job.total_decisions
        restored = job.decisions_restored_from_redis
        assigned = job.decisions_assigned_to_pipeline
        missing = total - restored

        self.stdout.write(f"\n=== Pipeline Progress ===")
        self.stdout.write(f"Total fetched from API: {total}")
        self.stdout.write(
            f"Restored from Redis: {restored} ({100*restored/total:.1f}%)"
        )
        self.stdout.write(
            f"Assigned to pipeline: {assigned} ({100*assigned/total:.1f}%)"
        )
        self.stdout.write(
            self.style.WARNING(
                f"\n[WARN]️  Missing: {missing} decisions ({100*missing/total:.1f}%)"
            )
        )

        if missing == 0:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n[OK] All decisions restored! Job may just need status update."
                )
            )
            if not dry_run:
                job.status = ImportJobStatus.COMPLETED
                job.completed_at = timezone.now()
                job.save()
                self.stdout.write(self.style.SUCCESS(f"[OK] Updated job to COMPLETED"))
            return

        # Check if decisions exist in database
        self.stdout.write(f"\n=== Checking Database ===")

        from datetime import timedelta

        from diavgeia_api.models.decisions import Decision

        # Get all decisions for this date
        decisions_in_db = Decision.objects.filter(
            issue_date__gte=job.start_date,
            issue_date__lt=job.start_date + timedelta(days=1),
        )

        if job.organization_id:
            decisions_in_db = decisions_in_db.filter(
                organization_id=job.organization_id
            )
        if job.unit_id:
            decisions_in_db.filter(unit_id=job.unit_id)
        if job.signer_id:
            decisions_in_db = decisions_in_db.filter(signer_id=job.signer_id)

        db_count = decisions_in_db.count()
        self.stdout.write(f"Decisions in database: {db_count}")

        # Get decisions linked to this job
        job_decisions = Decision.objects.filter(import_job=job)
        job_count = job_decisions.count()
        self.stdout.write(f"Decisions linked to job: {job_count}")

        # Strategy 1: Find decisions in DB but not linked to this job
        unlinked = db_count - job_count
        if unlinked > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\n[WARN]️  Found {unlinked} decisions in DB not linked to this job"
                )
            )
            self.stdout.write("These may have been imported but not tracked properly.")

        # Strategy 2: Re-fetch from API
        if refetch:
            self.stdout.write(f"\n=== Re-fetching from API ===")

            fetcher = DiavgeiaFetcher()
            search_params = {
                "from_issue_date": job.start_date.isoformat(),
                "to_issue_date": (job.start_date + timedelta(days=1)).isoformat(),
                "page": 0,
                "size": 500,
            }

            if job.search_params:
                search_params.update(job.search_params)

            self.stdout.write(f"Fetching decisions for {job.start_date}...")

            if dry_run:
                self.stdout.write(
                    self.style.WARNING("DRY RUN - Would fetch from API with params:")
                )
                import json

                self.stdout.write(json.dumps(search_params, indent=2))
                return

            # Fetch all pages
            all_decisions = []
            page = 0
            total_pages = 1

            while page < total_pages:
                search_params["page"] = page
                result = fetcher.fetch_decisions(search_params)

                if not result or "decisions" not in result:
                    break

                decisions = result["decisions"]
                all_decisions.extend(decisions)

                total_pages = result.get("info", {}).get("pages", 1)
                page += 1

                self.stdout.write(
                    f"  Fetched page {page}/{total_pages}: {len(decisions)} decisions"
                )

            self.stdout.write(
                self.style.SUCCESS(
                    f"\n[OK] Fetched {len(all_decisions)} decisions total"
                )
            )

            # Now import them
            from core.importers.decisions import DecisionImporter
            from core.utils.discovery_tracking import (
                DiscoverySource,
                add_discovery_source_to_decision,
            )

            importer = DecisionImporter()
            DecisionPipelineOrchestrator()

            imported = 0
            updated = 0
            dispatched = 0

            for i, decision_dto in enumerate(all_decisions, 1):
                try:
                    # Import decision
                    decision_db, created = importer.import_decision(
                        decision_dto=decision_dto, import_job=job
                    )

                    if created:
                        imported += 1
                    else:
                        updated += 1

                    # Add discovery tracking
                    add_discovery_source_to_decision(
                        decision=decision_db,
                        source=DiscoverySource.MANUAL_COMPLETION,
                        metadata={"original_job_id": job.id, "completion_run": True},
                    )

                    # Dispatch to pipeline
                    result = run_decision_pipeline_task.delay(
                        decision_id=decision_db.id,
                        stages_to_run=list(range(1, 8)),  # All stages
                        skip_opensearch=False,
                    )

                    dispatched += 1

                    if i % 100 == 0:
                        self.stdout.write(f"  Processed {i}/{len(all_decisions)}...")

                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"  [FAIL] Error on decision {i}: {str(e)}")
                    )

            self.stdout.write(f"\n=== Summary ===")
            self.stdout.write(self.style.SUCCESS(f"[OK] New decisions: {imported}"))
            self.stdout.write(self.style.SUCCESS(f"[OK] Updated decisions: {updated}"))
            self.stdout.write(
                self.style.SUCCESS(f"[OK] Pipeline tasks dispatched: {dispatched}")
            )

            # Update job
            job.new_decisions += imported
            job.updated_decisions += updated
            job.decisions_assigned_to_pipeline += dispatched
            job.save()

            self.stdout.write(f"\n[OK] Updated ImportJob #{job.id}")

        else:
            self.stdout.write(f"\n=== Recommendations ===")
            self.stdout.write(
                "1. Use --refetch-from-api to re-fetch missing decisions from Diavgeia"
            )
            self.stdout.write(
                "2. Or accept partial completion and mark job as PARTIALLY_COMPLETED"
            )
            self.stdout.write("3. Missing decisions will be caught on next full import")
