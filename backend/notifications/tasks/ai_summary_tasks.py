"""
Celery task for AI summarization of notification batches.

Triggered after a batch is created (if the subscription has AI summary enabled)
or manually via the API ``summarize`` action.
"""

from django.utils import timezone
from loguru import logger

from celery import shared_task

from core.tasks.tasks_decision_ai import _extract_pipeline_output
from notifications.models import NotificationBatch


@shared_task(bind=True, max_retries=2)
def summarize_notification_batch(self, batch_id):
    """
    Run the AI summarization pipeline on a notification batch.

    Reads the subscription's configured pipeline (or the default), builds a
    ``PipelineContext`` from the batch's decisions, and stores the result on
    ``NotificationBatch.ai_summary``.
    """
    try:
        batch = NotificationBatch.objects.select_related(
            "subscription__user",
            "subscription__ai_summary_pipeline",
        ).get(id=batch_id)
    except NotificationBatch.DoesNotExist:
        logger.error(f"summarize_notification_batch: batch {batch_id} not found")
        return {"batch_id": batch_id, "error": "not_found"}

    subscription = batch.subscription

    # Check if AI summary is enabled
    if not subscription.ai_summary_enabled:
        batch.ai_summary_status = "SKIPPED"
        batch.save(update_fields=["ai_summary_status"])
        logger.info(f"Batch {batch_id}: AI summary disabled, skipping")
        return {"batch_id": batch_id, "status": "skipped"}

    # Mark as running
    batch.ai_summary_status = "RUNNING"
    batch.save(update_fields=["ai_summary_status"])

    try:
        from core.models.pipeline import PipelineDefinition
        from core.services.pipeline_engine import PipelineContext, PipelineEngine

        # Resolve pipeline definition
        pipeline_def = subscription.ai_summary_pipeline
        if pipeline_def is None:
            pipeline_def = _get_or_create_default_pipeline()

        # Gather decisions from the batch
        batch_decisions = batch.batch_decisions.select_related(
            "decision__text_extraction"
        ).all()
        decisions = [bd.decision for bd in batch_decisions]

        if not decisions:
            batch.ai_summary_status = "SKIPPED"
            batch.ai_summary_error = "No decisions in batch to summarize"
            batch.save(update_fields=["ai_summary_status", "ai_summary_error"])
            return {"batch_id": batch_id, "status": "skipped", "reason": "no_decisions"}

        # Build context and run pipeline
        context = PipelineContext(
            decisions=decisions,
            batch=batch,
            user=subscription.user,
        )
        engine = PipelineEngine()
        run = engine.run(
            pipeline_def,
            context,
            trigger="notification_batch_summary",
            trigger_ref=f"batch:{batch_id}",
        )

        final_output = _extract_pipeline_output(context, run)

        batch.ai_summary = final_output
        batch.ai_summary_status = run.status
        batch.ai_summary_run = run
        batch.ai_summary_completed_at = run.completed_at
        if run.status == "FAILED":
            batch.ai_summary_error = run.error_message
        batch.save()

        logger.info(
            f"Batch {batch_id}: AI summary {run.status} "
            f"(cost: ${run.total_cost_usd}, tokens: {run.total_input_tokens}+{run.total_output_tokens})"
        )
        return {
            "batch_id": batch_id,
            "status": run.status,
            "pipeline_run_id": run.id,
            "cost_usd": str(run.total_cost_usd),
        }

    except Exception as exc:
        logger.error(
            f"summarize_notification_batch failed for batch {batch_id}: {exc}",
            exc_info=True,
        )
        batch.ai_summary_status = "FAILED"
        batch.ai_summary_error = str(exc)
        batch.save(update_fields=["ai_summary_status", "ai_summary_error"])

        # Retry with backoff
        raise self.retry(exc=exc, countdown=60)


def _get_or_create_default_pipeline():
    """
    Get or create the default notification batch summary pipeline.

    This is a map-reduce pipeline:
    1. EXTRACT — read cached DocumentExtraction.raw_text
    2. AI_CALL (map) — summarize each decision
    3. AGGREGATE — summarize-of-summaries
    """
    from core.models.pipeline import PipelineDefinition

    pipeline, created = PipelineDefinition.objects.get_or_create(
        name="notification_batch_summary_v1",
        defaults={
            "version": 1,
            "description": "Default map-reduce pipeline for notification batch summarization",
            "is_active": True,
            "trigger_type": "notification_batch_summary",
        },
    )

    if created:
        from core.models.pipeline import PipelineStep

        PipelineStep.objects.create(
            pipeline=pipeline,
            order=1,
            step_type="EXTRACT",
            name="Extract document text",
            config={
                "extractor": "PYMUPDF",
                "re_extract": False,
                "max_chars": 50000,
            },
        )
        PipelineStep.objects.create(
            pipeline=pipeline,
            order=2,
            step_type="AI_CALL",
            name="Summarize each decision",
            config={
                "provider": "OPENROUTER",
                "map_over_items": True,
                "system_prompt": "You are a legal analyst. Summarize the key points of this government decision concisely.",
                "prompt_template": "Summarize this decision:\n{{ text }}",
                "temperature": 0.3,
                # max_tokens intentionally omitted: only persist a step config
                # value when overriding the code-level default
                # (ai_call.DEFAULT_MAX_TOKENS).  Tuning the default is a
                # code change, not a data migration.
            },
        )
        PipelineStep.objects.create(
            pipeline=pipeline,
            order=3,
            step_type="AGGREGATE",
            name="Merge summaries",
            config={
                "strategy": "summarize_each_then_merge",
                "provider": "OPENROUTER",
                "system_prompt": "You are a legal analyst. Synthesize the provided decision summaries into a single coherent overview.",
                "merge_prompt_template": "Synthesize a single summary of these decision summaries:\n{{ text }}",
                "temperature": 0.3,
                # max_tokens intentionally omitted — see AI_CALL step above.
            },
        )
        logger.info("Created default notification_batch_summary_v1 pipeline")

    return pipeline
