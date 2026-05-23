"""
Celery tasks for AI jobs.

This module automatically registers Celery tasks for all active AIJobDefinitions.
"""

from celery import shared_task
from core.jobs.base import load_job_class
from core.models.ai_pricing import AIJobDefinition
from loguru import logger


@shared_task(name="ai_jobs.register_all")
def register_all_job_tasks():
    """
    Register Celery tasks for all active job definitions.
    Run this on worker startup or when jobs are added/updated.
    """
    active_jobs = AIJobDefinition.objects.filter(is_active=True)

    registered = []
    for job_def in active_jobs:
        try:
            job_class = load_job_class(job_def)
            job_class.create_celery_task(job_def)
            registered.append(job_def.job_name)
            logger.info(f"[OK] Registered Celery task: ai_job.{job_def.job_name}")
        except Exception as e:
            logger.error(f"[FAIL] Failed to register {job_def.job_name}: {e}")

    logger.info(f"Registered {len(registered)} AI job tasks")
    return registered


@shared_task(name="ai_jobs.execute_by_name")
def execute_job_by_name(
    job_name: str, provider: str, model: str, dry_run: bool = False, **kwargs
):
    """
    Execute a job by its name.

    Args:
        job_name: Name of the job to execute
        provider: AI provider to use
        model: Model name
        dry_run: If True, only estimate costs
        **kwargs: Additional arguments for the job

    Returns:
        Dict with execution results

    Example:
        from core.jobs.tasks import execute_job_by_name

        result = execute_job_by_name.delay(
            job_name="daily_summary",
            provider="AWS_BEDROCK",
            model="anthropic.claude-3-haiku-20240307-v1:0",
            target_date=date(2025, 1, 1),
            dry_run=False
        )
    """
    try:
        job_def = AIJobDefinition.objects.get(job_name=job_name, is_active=True)
        job_class = load_job_class(job_def)

        job = job_class(job_def)
        execution = job.execute(
            provider=provider, model=model, dry_run=dry_run, **kwargs
        )

        return {
            "success": True,
            "execution_id": execution.execution_id,
            "status": execution.status,
            "items_processed": execution.items_processed,
            "total_cost_usd": float(
                execution.actual_cost_usd or execution.estimated_cost_usd or 0
            ),
            "dry_run": dry_run,
        }

    except AIJobDefinition.DoesNotExist:
        logger.error(f"Job {job_name} not found or not active")
        return {"success": False, "error": f"Job {job_name} not found"}
    except Exception as e:
        logger.error(f"Job {job_name} execution failed: {e}")
        return {"success": False, "error": str(e)}


@shared_task(name="ai_jobs.validate_all")
def validate_all_jobs():
    """
    Validate all job implementations.
    Useful for checking if jobs are correctly implemented after code changes.

    Returns:
        Dict with validation results
    """
    results = {}
    active_jobs = AIJobDefinition.objects.filter(is_active=True)

    for job_def in active_jobs:
        try:
            job_class = load_job_class(job_def)
            job = job_class(job_def)
            job.validate_implementation()
            results[job_def.job_name] = {"valid": True, "error": None}
            logger.info(f"[OK] {job_def.job_name} validation passed")
        except Exception as e:
            results[job_def.job_name] = {"valid": False, "error": str(e)}
            logger.error(f"[FAIL] {job_def.job_name} validation failed: {e}")

    return results
