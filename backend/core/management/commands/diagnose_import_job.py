"""
Management command to diagnose stuck import jobs and provide actionable recommendations

Usage:
    # Diagnose job 849
    python manage.py diagnose_import_job 849

    # Include Celery task status checks
    python manage.py diagnose_import_job 849 --check-celery

    # Export full diagnostic report as JSON
    python manage.py diagnose_import_job 849 --export diagnosis-849.json
"""

import json

from core.models.import_jobs import ImportFailure, ImportJob, ImportJobStatus
from diavgeia_project.settings.constants import IMPORT_CHUNKS_REDIS_DB_NAME
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_redis import get_redis_connection


class Command(BaseCommand):
    help = "Diagnose stuck import jobs and provide recommendations"

    def add_arguments(self, parser):
        parser.add_argument("job_id", type=int, help="ImportJob ID to diagnose")
        parser.add_argument(
            "--check-celery",
            action="store_true",
            help="Check Celery task status (requires celery inspect)",
        )
        parser.add_argument(
            "--export", type=str, help="Export full diagnostic report to JSON file"
        )

    def handle(self, *args, **options):
        job_id = options["job_id"]
        check_celery = options["check_celery"]
        export_file = options.get("export")

        # Get the import job
        try:
            job = ImportJob.objects.get(id=job_id)
        except ImportJob.DoesNotExist:
            raise CommandError(f"ImportJob {job_id} does not exist")

        # Build diagnostic report
        report = self.build_diagnostic_report(job, check_celery)

        # Display report
        self.display_report(report)

        # Export if requested
        if export_file:
            with open(export_file, "w") as f:
                json.dump(report, f, indent=2, default=str)
            self.stdout.write(self.style.SUCCESS(f"\n[OK] Exported to {export_file}"))

    def build_diagnostic_report(self, job, check_celery=False):
        """Build comprehensive diagnostic report"""
        age = timezone.now() - job.created_at

        report = {
            "job_info": {
                "id": job.id,
                "status": job.status,
                "start_date": job.start_date.isoformat(),
                "created_at": job.created_at.isoformat(),
                "age_hours": age.total_seconds() / 3600,
                "age_human": f"{age.seconds//3600}h {(age.seconds%3600)//60}m",
                "celery_task_id": job.celery_task_id,
            },
            "pipeline_progress": {
                "total_decisions": job.total_decisions,
                "restored_from_redis": job.decisions_restored_from_redis,
                "restored_percentage": (
                    (job.decisions_restored_from_redis / job.total_decisions * 100)
                    if job.total_decisions > 0
                    else 0
                ),
                "assigned_to_pipeline": job.decisions_assigned_to_pipeline,
                "pipeline_percentage": (
                    (job.decisions_assigned_to_pipeline / job.total_decisions * 100)
                    if job.total_decisions > 0
                    else 0
                ),
                "new_decisions": job.new_decisions,
                "updated_decisions": job.updated_decisions,
                "error_count": job.error_count,
            },
            "chunk_progress": {
                "total_chunks": job.total_chunks,
                "chunks_completed": job.chunks_completed,
                "chunks_failed": job.chunks_failed,
                "chunks_missing": job.total_chunks
                - job.chunks_completed
                - job.chunks_failed,
                "completion_percentage": (
                    (job.chunks_completed / job.total_chunks * 100)
                    if job.total_chunks > 0
                    else 0
                ),
                "task_ids_dispatched": len(job.chunk_task_ids),
                "tasks_reported": job.chunks_completed + job.chunks_failed,
                "tasks_unreported": len(job.chunk_task_ids)
                - (job.chunks_completed + job.chunks_failed),
            },
        }

        # Check Redis for remaining chunks
        redis_client = get_redis_connection(IMPORT_CHUNKS_REDIS_DB_NAME)
        date_str = job.start_date.isoformat()
        pattern = f"decision_chunk:{date_str}_*"

        redis_chunks = []
        for key in redis_client.scan_iter(match=pattern):
            key_str = key.decode("utf-8") if isinstance(key, bytes) else key
            redis_chunks.append(key_str)

        report["redis_status"] = {
            "chunks_remaining": len(redis_chunks),
            "sample_chunk_ids": redis_chunks[:10],
        }

        # Check for failures
        failures = ImportFailure.objects.filter(import_job=job).order_by("-created_at")[
            :20
        ]
        report["recent_failures"] = [
            {
                "task_id": f.task_id,
                "error_message": f.error_message[:200],
                "created_at": f.created_at.isoformat(),
                "retry_count": f.retry_count,
            }
            for f in failures
        ]

        # Analyze issues
        report["issues"] = self.analyze_issues(job, report)

        # Generate recommendations
        report["recommendations"] = self.generate_recommendations(job, report)

        # Check Celery if requested
        if check_celery and job.celery_task_id:
            try:
                from celery import current_app

                inspect = current_app.control.inspect()

                # Check active tasks
                active = inspect.active()
                if active:
                    for worker, tasks in active.items():
                        for task in tasks:
                            if task["id"] == job.celery_task_id:
                                report["celery_status"] = {
                                    "status": "active",
                                    "worker": worker,
                                    "task": task,
                                }

                # Check reserved tasks
                if "celery_status" not in report:
                    reserved = inspect.reserved()
                    if reserved:
                        for worker, tasks in reserved.items():
                            for task in tasks:
                                if task["id"] == job.celery_task_id:
                                    report["celery_status"] = {
                                        "status": "reserved",
                                        "worker": worker,
                                        "task": task,
                                    }

                if "celery_status" not in report:
                    report["celery_status"] = {
                        "status": "not_found",
                        "message": "Task not in active or reserved queues",
                    }

            except Exception as e:
                report["celery_status"] = {"error": str(e)}

        return report

    def analyze_issues(self, job, report):
        """Analyze what's wrong with the job"""
        issues = []

        chunk_info = report["chunk_progress"]
        pipeline_info = report["pipeline_progress"]
        redis_info = report["redis_status"]
        age_hours = report["job_info"]["age_hours"]

        # Issue 1: Job stuck in active status for too long
        if job.status in [
            ImportJobStatus.PROCESSING,
            ImportJobStatus.FETCHING,
            ImportJobStatus.SPLITTING,
        ]:
            if age_hours > 2:
                issues.append(
                    {
                        "severity": "CRITICAL",
                        "type": "stuck_status",
                        "message": f"Job has been in {job.status} status for {age_hours:.1f} hours",
                    }
                )

        # Issue 2: Missing chunks
        if chunk_info["chunks_missing"] > 0:
            issues.append(
                {
                    "severity": "HIGH",
                    "type": "missing_chunks",
                    "message": f'{chunk_info["chunks_missing"]} chunks have not reported completion',
                }
            )

        # Issue 3: Chunks still in Redis
        if redis_info["chunks_remaining"] > 0:
            issues.append(
                {
                    "severity": "MEDIUM",
                    "type": "redis_chunks_remaining",
                    "message": f'{redis_info["chunks_remaining"]} chunks still in Redis (should be processed)',
                }
            )

        # Issue 4: Pipeline stall
        restore_rate = pipeline_info["restored_percentage"]
        pipeline_rate = pipeline_info["pipeline_percentage"]

        if restore_rate < 95 and chunk_info["completion_percentage"] > 90:
            issues.append(
                {
                    "severity": "HIGH",
                    "type": "pipeline_restore_stall",
                    "message": f'Only {restore_rate:.1f}% restored but {chunk_info["completion_percentage"]:.1f}% chunks complete',
                }
            )

        if pipeline_rate < restore_rate - 5:
            issues.append(
                {
                    "severity": "MEDIUM",
                    "type": "pipeline_assignment_lag",
                    "message": f"Pipeline assignment lagging: {pipeline_rate:.1f}% vs {restore_rate:.1f}% restored",
                }
            )

        # Issue 5: High error rate
        if pipeline_info["error_count"] > 0:
            error_rate = (
                pipeline_info["error_count"] / pipeline_info["total_decisions"] * 100
            )
            if error_rate > 5:
                issues.append(
                    {
                        "severity": "HIGH",
                        "type": "high_error_rate",
                        "message": f'{error_rate:.1f}% error rate ({pipeline_info["error_count"]} errors)',
                    }
                )

        # Issue 6: Failed chunks
        if chunk_info["chunks_failed"] > 0:
            fail_rate = chunk_info["chunks_failed"] / chunk_info["total_chunks"] * 100
            issues.append(
                {
                    "severity": "MEDIUM" if fail_rate < 10 else "HIGH",
                    "type": "failed_chunks",
                    "message": f'{chunk_info["chunks_failed"]} chunks failed ({fail_rate:.1f}%)',
                }
            )

        return issues

    def generate_recommendations(self, job, report):
        """Generate actionable recommendations"""
        recommendations = []

        chunk_info = report["chunk_progress"]
        redis_info = report["redis_status"]

        # Recommendation 1: Retry missing chunks
        if chunk_info["chunks_missing"] > 0 and redis_info["chunks_remaining"] > 0:
            recommendations.append(
                {
                    "action": "retry_missing_chunks",
                    "command": f"python manage.py retry_import_chunks {job.id} --all-missing",
                    "description": f'Retry all {redis_info["chunks_remaining"]} chunks found in Redis',
                }
            )

        # Recommendation 2: Check Celery worker
        if chunk_info["chunks_missing"] > 0:
            recommendations.append(
                {
                    "action": "check_celery_worker",
                    "command": "docker-compose logs -f backend --tail=100",
                    "description": "Check Celery worker logs for errors or task failures",
                }
            )

        # Recommendation 3: Mark job as failed if hopeless
        if report["job_info"]["age_hours"] > 24:
            recommendations.append(
                {
                    "action": "mark_as_failed",
                    "description": "Job is >24h old. Consider marking as failed and starting fresh",
                    "django_admin": f"/api/admin/core/importjob/{job.id}/change/",
                }
            )

        # Recommendation 4: Check for duplicate jobs
        recommendations.append(
            {
                "action": "check_duplicates",
                "command": 'Visit /api/admin/core/importjob/monitor/ and click "Clear Duplicates"',
                "description": "Check if there are duplicate jobs blocking the queue",
            }
        )

        # Recommendation 5: View detailed diagnostics
        recommendations.append(
            {
                "action": "view_diagnostics",
                "url": f"/api/admin/core/importjob/{job.id}/change/",
                "description": "View full diagnostics in Django admin",
            }
        )

        return recommendations

    def display_report(self, report):
        """Display diagnostic report in terminal"""

        # Header
        self.stdout.write(self.style.SUCCESS("\n" + "=" * 80))
        self.stdout.write(self.style.SUCCESS(f"  IMPORT JOB DIAGNOSTIC REPORT"))
        self.stdout.write(self.style.SUCCESS("=" * 80 + "\n"))

        # Job Info
        job_info = report["job_info"]
        self.stdout.write(self.style.HTTP_INFO("[COPY] JOB INFORMATION"))
        self.stdout.write(f'  ID: {job_info["id"]}')
        self.stdout.write(f'  Status: {job_info["status"]}')
        self.stdout.write(f'  Date: {job_info["start_date"]}')
        self.stdout.write(f'  Created: {job_info["created_at"]}')
        self.stdout.write(
            f'  Age: {job_info["age_human"]} ({job_info["age_hours"]:.1f}h)'
        )

        # Pipeline Progress
        pipeline = report["pipeline_progress"]
        self.stdout.write(self.style.HTTP_INFO("\n[CHART] PIPELINE PROGRESS"))
        self.stdout.write(f'  Total Decisions: {pipeline["total_decisions"]}')
        self.stdout.write(
            f'  Restored from Redis: {pipeline["restored_from_redis"]} ({pipeline["restored_percentage"]:.1f}%)'
        )
        self.stdout.write(
            f'  Assigned to Pipeline: {pipeline["assigned_to_pipeline"]} ({pipeline["pipeline_percentage"]:.1f}%)'
        )
        self.stdout.write(
            f'  New: {pipeline["new_decisions"]} | Updated: {pipeline["updated_decisions"]} | Errors: {pipeline["error_count"]}'
        )

        # Chunk Progress
        chunks = report["chunk_progress"]
        self.stdout.write(self.style.HTTP_INFO("\n[PKG] CHUNK PROGRESS"))
        self.stdout.write(f'  Total Chunks: {chunks["total_chunks"]}')
        self.stdout.write(
            f'  Completed: {chunks["chunks_completed"]} ({chunks["completion_percentage"]:.1f}%)'
        )
        self.stdout.write(f'  Failed: {chunks["chunks_failed"]}')

        if chunks["chunks_missing"] > 0:
            self.stdout.write(
                self.style.WARNING(f'  [WARN]️  Missing: {chunks["chunks_missing"]}')
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"  [OK] Missing: 0"))

        self.stdout.write(f'  Task IDs Dispatched: {chunks["task_ids_dispatched"]}')
        self.stdout.write(f'  Tasks Reported: {chunks["tasks_reported"]}')

        if chunks["tasks_unreported"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'  [WARN]️  Tasks Unreported: {chunks["tasks_unreported"]}'
                )
            )

        # Redis Status
        redis = report["redis_status"]
        self.stdout.write(self.style.HTTP_INFO("\n[SAVE] REDIS STATUS"))
        if redis["chunks_remaining"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f'  [WARN]️  Chunks Remaining: {redis["chunks_remaining"]}'
                )
            )
            if redis["sample_chunk_ids"]:
                self.stdout.write("  Sample chunk IDs:")
                for chunk_id in redis["sample_chunk_ids"][:5]:
                    self.stdout.write(f"    - {chunk_id}")
        else:
            self.stdout.write(
                self.style.SUCCESS(f"  [OK] Chunks Remaining: 0 (all processed)")
            )

        # Issues
        issues = report["issues"]
        if issues:
            self.stdout.write(self.style.ERROR("\n[ALERT] ISSUES DETECTED"))
            for issue in issues:
                severity_color = {
                    "CRITICAL": self.style.ERROR,
                    "HIGH": self.style.WARNING,
                    "MEDIUM": self.style.HTTP_INFO,
                }[issue["severity"]]
                self.stdout.write(
                    severity_color(f'  [{issue["severity"]}] {issue["type"]}')
                )
                self.stdout.write(f'    {issue["message"]}')
        else:
            self.stdout.write(self.style.SUCCESS("\n[OK] No issues detected"))

        # Recommendations
        recommendations = report["recommendations"]
        if recommendations:
            self.stdout.write(self.style.SUCCESS("\n[INFO] RECOMMENDATIONS"))
            for i, rec in enumerate(recommendations, 1):
                self.stdout.write(f'\n  {i}. {rec["action"].replace("_", " ").title()}')
                self.stdout.write(f'     {rec["description"]}')
                if "command" in rec:
                    self.stdout.write(self.style.SQL_FIELD(f'     $ {rec["command"]}'))
                if "url" in rec:
                    self.stdout.write(self.style.HTTP_INFO(f'     [LINK] {rec["url"]}'))

        # Celery Status
        if "celery_status" in report:
            self.stdout.write(self.style.HTTP_INFO("\n[RETRY] CELERY STATUS"))
            celery = report["celery_status"]
            if celery.get("status") == "active":
                self.stdout.write(
                    self.style.SUCCESS(
                        f'  [OK] Task is ACTIVE on worker: {celery["worker"]}'
                    )
                )
            elif celery.get("status") == "reserved":
                self.stdout.write(
                    self.style.WARNING(
                        f'  ⏳ Task is RESERVED on worker: {celery["worker"]}'
                    )
                )
            elif celery.get("status") == "not_found":
                self.stdout.write(
                    self.style.ERROR(
                        f"  [FAIL] Task not found in active/reserved queues"
                    )
                )
                self.stdout.write("    Task may have completed or failed")
            elif "error" in celery:
                self.stdout.write(
                    self.style.ERROR(
                        f'  [FAIL] Error checking Celery: {celery["error"]}'
                    )
                )

        # Footer
        self.stdout.write("\n" + "=" * 80 + "\n")
