"""
Celery tasks for automated health checking.

These tasks run in the background to keep health check data fresh
so the admin interface always has up-to-date information.
"""

from datetime import timedelta

from celery import shared_task
from core.models.decision_health import DecisionHealthCheck, HealthStatus
from core.models.decisions import Decision
from core.models.import_jobs import ImportJob
from core.services.decision_health_service import DecisionHealthService
from django.utils import timezone
from loguru import logger


@shared_task
def check_recent_decisions_health():
    """
    Automatically check health of recent decisions.
    This task should be run periodically (e.g., every hour) to keep data fresh.
    """
    health_service = DecisionHealthService()

    # Check decisions from the last 24 hours
    yesterday = timezone.now() - timedelta(hours=24)
    recent_decisions = Decision.objects.filter(issue_date__gte=yesterday).order_by(
        "-issue_date"
    )[
        :50
    ]  # Limit to avoid overload

    if not recent_decisions:
        logger.info("No recent decisions to check")
        return {"status": "completed", "checked_count": 0}

    logger.info(
        f"Starting automated health check for {len(recent_decisions)} recent decisions"
    )

    results = health_service.bulk_check_decisions(list(recent_decisions))

    logger.info(
        f"Automated health check completed: {results['summary']['total_checked']} checked, "
        f"{results['summary']['errors']} errors, {results['summary']['warnings']} warnings"
    )

    return {
        "status": "completed",
        "checked_count": results["summary"]["total_checked"],
        "errors": results["summary"]["errors"],
        "warnings": results["summary"]["warnings"],
    }


@shared_task
def refresh_problematic_decisions():
    """
    Re-check decisions that currently have health issues.
    This helps track if issues are being resolved.
    """
    health_service = DecisionHealthService()

    # Get decisions with errors or warnings that haven't been checked recently
    one_hour_ago = timezone.now() - timedelta(hours=1)
    problematic_checks = DecisionHealthCheck.objects.filter(
        overall_status__in=[HealthStatus.ERROR, HealthStatus.WARNING],
        last_checked_at__lt=one_hour_ago,
    ).select_related("decision")[
        :30
    ]  # Limit to avoid overload

    if not problematic_checks:
        logger.info("No problematic decisions need refresh")
        return {"status": "completed", "refreshed_count": 0}

    logger.info(f"Refreshing {len(problematic_checks)} problematic decisions")

    refreshed_count = 0
    for health_check in problematic_checks:
        try:
            health_service.check_decision_health(
                health_check.decision, force_refresh=True
            )
            refreshed_count += 1
        except Exception as e:
            logger.error(f"Failed to refresh {health_check.decision.ada}: {e}")

    logger.info(f"Refreshed {refreshed_count} problematic decisions")

    return {"status": "completed", "refreshed_count": refreshed_count}


@shared_task
def cleanup_old_health_checks():
    """
    Clean up old health check records to prevent database bloat.
    Keeps the most recent check for each decision and removes older ones.
    """

    from django.db.models import Max

    # Group health checks by decision and find the latest for each
    latest_checks = DecisionHealthCheck.objects.values("decision_id").annotate(
        latest_check=Max("last_checked_at")
    )

    # Build a map of decision_id -> latest_check_date
    latest_map = {item["decision_id"]: item["latest_check"] for item in latest_checks}

    # Find and delete older checks
    deleted_count = 0
    for decision_id, latest_date in latest_map.items():
        older_checks = DecisionHealthCheck.objects.filter(
            decision_id=decision_id, last_checked_at__lt=latest_date
        )

        count = older_checks.count()
        if count > 0:
            older_checks.delete()
            deleted_count += count

    logger.info(f"Cleaned up {deleted_count} old health check records")

    return {"status": "completed", "deleted_count": deleted_count}


@shared_task
def auto_fix_simple_issues(decision_adas=None):
    """
    Automatically attempt to fix simple, safe issues.
    Only performs actions that are known to be safe and reversible.

    Args:
        decision_adas: Optional list of specific decision ADAs to fix.
                      If None, will find problematic decisions automatically.
    """
    from core.models.document_analysis import DocumentExtraction, ProcessingStatus

    DecisionHealthService()
    fixes_attempted = 0

    if decision_adas:
        # Fix specific decisions
        opensearch_issues = DecisionHealthCheck.objects.filter(
            opensearch_status=HealthStatus.ERROR, decision__ada__in=decision_adas
        ).select_related("decision")
    else:
        # Find decisions with OpenSearch indexing issues where document extraction is complete
        opensearch_issues = DecisionHealthCheck.objects.filter(
            opensearch_status=HealthStatus.ERROR
        ).select_related("decision")[
            :20
        ]  # Limit to avoid overwhelming the system

    for health_check in opensearch_issues:
        decision = health_check.decision

        try:
            # Check if document extraction is complete
            extraction = decision.text_extraction
            if (
                extraction.extraction_status == ProcessingStatus.COMPLETED
                and extraction.raw_text
            ):
                # Re-trigger OpenSearch indexing
                from core.signals import index_document_in_opensearch

                index_document_in_opensearch(
                    sender=type(extraction), instance=extraction, created=False
                )

                fixes_attempted += 1
                logger.info(f"Auto-fixed OpenSearch indexing for {decision.ada}")

        except DocumentExtraction.DoesNotExist:
            continue
        except Exception as e:
            logger.error(f"Auto-fix failed for {decision.ada}: {e}")

    return {"status": "completed", "fixes_attempted": fixes_attempted}


@shared_task
def check_single_decision_health(ada: str):
    """
    Check health of a single decision by ADA.
    Used for immediate updates when decisions are modified.
    """
    health_service = DecisionHealthService()

    try:
        decision = Decision.objects.get(ada=ada)

        health_check = health_service.check_decision_health(
            decision, force_refresh=True
        )

        logger.info(f"Updated health check for {ada}: {health_check.overall_status}")

        return {
            "status": "completed",
            "ada": ada,
            "overall_status": health_check.overall_status,
            "has_errors": health_check.has_errors,
            "has_warnings": health_check.has_warnings,
        }

    except Decision.DoesNotExist:
        logger.error(f"Decision {ada} not found for health check")
        return {"status": "error", "message": f"Decision {ada} not found"}

    except Exception as e:
        logger.error(f"Failed to check health for {ada}: {e}")
        return {"status": "error", "message": str(e)}


@shared_task
def backfill_health_checks_for_import_job(
    import_job_id: int, max_workers: int = 5, force_reprocess: bool = False
):
    """
    Create/refresh DecisionHealthCheck records for decisions in an ImportJob that are missing them.

    This is intended to be triggered from admin actions so that large batches don't require log spelunking.

    Args:
        import_job_id: ImportJob primary key
        max_workers: Thread concurrency for orchestrator runs
        force_reprocess: If True, forces reprocessing steps even if already healthy

    Returns:
        Summary dict
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator

    try:
        job = ImportJob.objects.get(id=import_job_id)
    except ImportJob.DoesNotExist:
        return {"status": "error", "message": f"ImportJob {import_job_id} not found"}

    missing_qs = Decision.objects.filter(
        import_job_id=import_job_id, health_check__isnull=True
    )
    total = missing_qs.count()

    if total == 0:
        return {
            "status": "completed",
            "import_job_id": import_job_id,
            "missing": 0,
            "successful": 0,
            "failed": 0,
            "message": "No missing health checks",
        }

    logger.info(
        f"🩺 Backfilling health checks for ImportJob #{import_job_id}: {total} missing"
    )
    orchestrator = DecisionPipelineOrchestrator()

    # Pull ADAs only to keep memory predictable.
    adas = list(missing_qs.values_list("ada", flat=True))

    results = {"successful": 0, "failed": 0, "errors": []}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_ada = {
            executor.submit(
                orchestrator.run_pipeline, ada, force_reprocess=force_reprocess
            ): ada
            for ada in adas
        }

        for idx, future in enumerate(as_completed(future_to_ada), start=1):
            ada = future_to_ada[future]
            try:
                health_check = future.result()
                if (
                    health_check is None
                    or health_check.overall_status == HealthStatus.ERROR
                ):
                    results["failed"] += 1
                    results["errors"].append({"ada": ada})
                else:
                    results["successful"] += 1
            except Exception as e:
                results["failed"] += 1
                results["errors"].append({"ada": ada, "error": str(e)})

            if idx % 100 == 0:
                logger.info(
                    f"🩺 Backfill progress for ImportJob #{import_job_id}: {idx}/{total} "
                    f"({results['successful']} [OK], {results['failed']} [ERROR])"
                )

    logger.info(
        f"[OK] Backfill completed for ImportJob #{import_job_id}: "
        f"{results['successful']} succeeded, {results['failed']} failed"
    )

    return {
        "status": "completed",
        "import_job_id": import_job_id,
        "missing": total,
        "successful": results["successful"],
        "failed": results["failed"],
        "errors": results["errors"][:50],
        "errors_note": (
            "Showing first 50 errors" if len(results["errors"]) > 50 else None
        ),
    }


@shared_task
def retry_failed_decisions_for_import_job(
    import_job_id: int, component: str = None, max_workers: int = 5
):
    """
    Retry all ERROR-status DecisionHealthCheck records for an ImportJob.

    Uses the orchestrator's retry logic to re-run specific failed components
    or the entire pipeline.

    Args:
        import_job_id: ImportJob primary key
        component: Optional specific component to retry (e.g., 'document', 'opensearch')
        max_workers: Thread concurrency for retries

    Returns:
        Summary dict with retry results
    """
    from core.services.pipeline_orchestrator import DecisionPipelineOrchestrator

    try:
        job = ImportJob.objects.get(id=import_job_id)
    except ImportJob.DoesNotExist:
        return {"status": "error", "message": f"ImportJob {import_job_id} not found"}

    orchestrator = DecisionPipelineOrchestrator()

    logger.info(
        f"[RETRY] Starting retry for ImportJob #{import_job_id}, component: {component or 'all'}"
    )

    results = orchestrator.retry_batch_failures(
        import_job_id=import_job_id, component=component, max_workers=max_workers
    )

    logger.info(
        f"[OK] Retry completed for ImportJob #{import_job_id}: "
        f"{results.get('retried', 0)} fixed, {results.get('still_failed', 0)} still failed"
    )

    return {
        "status": "completed",
        "import_job_id": import_job_id,
        "component": component or "all",
        **results,
    }
