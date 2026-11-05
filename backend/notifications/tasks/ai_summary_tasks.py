"""
Celery task for AI summarization of notification batches.

Triggered after a batch is created (if the subscription has AI summary enabled)
or manually via the API ``summarize`` action.
"""

from loguru import logger

from celery import shared_task
from celery.exceptions import MaxRetriesExceededError, Retry

from core.ai_services.summary_prompts import (
    BATCH_MAP_SYSTEM_PROMPT,
    BATCH_MERGE_SYSTEM_PROMPT,
    BATCH_ONE_LINER_PROMPT_KIND,
    CACHE_ONE_LINERS_FLAG,
)
from core.tasks.tasks_decision_ai import _extract_pipeline_output
from notifications.models import (
    AISummarySkipReason,
    NotificationBatch,
    NotificationPreference,
)


def mark_summary_skipped(batch, reason, error=None):
    """Persist a SKIPPED status with its machine-readable reason."""
    batch.ai_summary_status = "SKIPPED"
    batch.ai_summary_skip_reason = reason
    batch.ai_summary_error = error
    batch.save(
        update_fields=[
            "ai_summary_status",
            "ai_summary_skip_reason",
            "ai_summary_error",
        ]
    )


@shared_task(bind=True, max_retries=2)
def summarize_notification_batch(self, batch_id, manual_override=False):
    """
    Run the AI summarization pipeline on a notification batch.

    Reads the subscription's configured pipeline (or the default), builds a
    ``PipelineContext`` from the batch's decisions, and stores the result on
    ``NotificationBatch.ai_summary``.  For map-mode pipelines the
    per-decision one-liners are also stored on ``ai_summary_items``.

    Chord-safe: when retries are exhausted the task marks the batch FAILED
    and *returns* an error dict instead of re-raising — a failing summary
    task must never break the email chord that waits on it.
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

    if manual_override:
        batch.ai_summary_manual_override = True
        batch.save(update_fields=["ai_summary_manual_override"])

    # Check if AI summary is enabled
    if not subscription.ai_summary_enabled:
        mark_summary_skipped(
            batch,
            AISummarySkipReason.SUBSCRIPTION_DISABLED,
            "AI summary disabled for this subscription",
        )
        logger.info(f"Batch {batch_id}: AI summary disabled, skipping")
        return {"batch_id": batch_id, "status": "skipped"}

    # The task is the authoritative gate for the user-level toggle too, so a
    # direct task call cannot bypass it.  An explicit manual override is the
    # documented exception.
    preference = NotificationPreference.get_for_user_id(subscription.user_id)
    if not preference.ai_summary_enabled and not manual_override:
        mark_summary_skipped(
            batch,
            AISummarySkipReason.USER_DISABLED,
            "AI summaries are disabled in notification preferences",
        )
        logger.info(f"Batch {batch_id}: user-level AI summaries disabled, skipping")
        return {"batch_id": batch_id, "status": "skipped"}

    # Mark as running and clear any previous skip/error detail.
    batch.ai_summary_status = "RUNNING"
    batch.ai_summary_skip_reason = None
    batch.ai_summary_error = None
    batch.save(
        update_fields=[
            "ai_summary_status",
            "ai_summary_skip_reason",
            "ai_summary_error",
        ]
    )

    try:
        from core.services.pipeline_engine import PipelineContext, PipelineEngine

        # Resolve pipeline definition
        pipeline_def = subscription.ai_summary_pipeline
        if pipeline_def is None:
            pipeline_def = _get_or_create_default_pipeline()

        map_mode = pipeline_def.steps.filter(
            step_type="AI_CALL", is_active=True, config__map_over_items=True
        ).exists()

        # Gather decisions from the batch
        batch_decisions = batch.batch_decisions.select_related(
            "decision__text_extraction"
        ).all()
        decisions = [bd.decision for bd in batch_decisions]

        if not decisions:
            mark_summary_skipped(
                batch,
                AISummarySkipReason.NO_DECISIONS,
                "No decisions in batch to summarize",
            )
            return {"batch_id": batch_id, "status": "skipped", "reason": "no_decisions"}

        # Cache inventory: decisions already covered by a shareable one-liner
        # cost nothing, so the budget only applies to the remainder.
        from core.services.decision_projections import (
            build_shareable_one_liners_by_decision,
        )
        from notifications.services.ai_budget import (
            subscription_new_decision_allowance,
            user_has_ai_budget,
        )

        cached = build_shareable_one_liners_by_decision(
            [decision.id for decision in decisions]
        )
        uncached = [d for d in decisions if d.id not in cached]

        # Compute the allowance before persisting this batch's counts: the
        # allowance sums *previous* batches for the day, and this batch must
        # not consume its own budget.
        allowance = subscription_new_decision_allowance(
            subscription, exclude_batch_id=batch.id
        )
        if manual_override:
            allowance = len(uncached)
        elif not user_has_ai_budget(subscription.user_id):
            allowance = 0

        max_new = min(len(uncached), allowance)
        skip_aggregate = (
            not manual_override and allowance == 0
        )

        batch.ai_summary_cached_count = len(cached)
        # Only allowed provider calls count against the daily budget; items
        # skipped because the budget was already spent are not charged.
        batch.ai_summary_new_count = max_new
        batch.save(
            update_fields=["ai_summary_cached_count", "ai_summary_new_count"]
        )

        # Build context and run pipeline
        context = PipelineContext(
            decisions=decisions,
            batch=batch,
            user=subscription.user,
        )

        if isinstance(context.metadata, dict):
            context.metadata["max_new_one_liners"] = max_new
            context.metadata["shared_one_liners"] = True
            context.metadata["skip_aggregate"] = skip_aggregate

        # Adopt one-liner rows minted by the previous (failed) try so internal
        # Celery retries overwrite the same rows in place instead of minting
        # new attempts (retry noise must not inflate the attempts history).
        if batch.ai_summary_run_id:
            from core.models.decision_one_liner import (
                DecisionOneLiner,
                OneLinerStatus,
            )

            context.metadata["adopt_one_liner_rows"] = {
                str(row.decision_id): row.id
                for row in DecisionOneLiner.objects.filter(
                    pipeline_run_id=batch.ai_summary_run_id,
                    status__in=(
                        OneLinerStatus.PENDING,
                        OneLinerStatus.RUNNING,
                    ),
                )
            }

        engine = PipelineEngine()
        run = engine.run(
            pipeline_def,
            context,
            trigger="notification_batch_summary",
            trigger_ref=f"batch:{batch_id}",
        )

        final_output = _extract_pipeline_output(context, run)

        # Per-decision one-liners from the map step (map-mode pipelines only)
        # feed the email bullets; merged ai_summary feeds AISummaryCard.
        if run.status == "COMPLETED":
            ai_summary_items = _collect_summary_items(
                decisions, context, pipeline_def
            )
        else:
            # A failed run may leave raw extract texts in per_item_outputs —
            # never surface those as one-liners.
            ai_summary_items = None

        # Cache-aware budget bookkeeping only applies to a real context (the
        # task configures metadata on it).  Tests and non-notification callers
        # that patch PipelineContext keep the plain run status.
        budget_active = isinstance(context.metadata, dict) and (
            "max_new_one_liners" in context.metadata
        )
        skip_aggregate_active = (
            isinstance(context.metadata, dict)
            and context.metadata.get("skip_aggregate") is True
        )

        status = run.status
        skip_reason = None
        error = None
        if skip_aggregate_active:
            # Cached bullets without a paid merge paragraph.
            final_output = None

        if budget_active and map_mode and run.status == "COMPLETED":
            item_count = len(ai_summary_items or [])
            if item_count == 0:
                status = "SKIPPED"
                skip_reason = AISummarySkipReason.BUDGET_EXHAUSTED
                error = (
                    "AI budget exhausted and no shared one-liners were available"
                )
                ai_summary_items = None
            elif item_count < len(decisions) or skip_aggregate_active:
                status = "PARTIAL"
                skip_reason = AISummarySkipReason.BUDGET_EXHAUSTED
                error = "AI budget exhausted before every decision was summarized"

        batch.ai_summary = final_output
        batch.ai_summary_items = ai_summary_items
        batch.ai_summary_status = status
        batch.ai_summary_skip_reason = skip_reason
        batch.ai_summary_run = run
        batch.ai_summary_completed_at = run.completed_at
        if run.status == "FAILED":
            batch.ai_summary_error = run.error_message
        elif error is not None:
            batch.ai_summary_error = error
        else:
            batch.ai_summary_error = None
        batch.save(
            update_fields=[
                "ai_summary",
                "ai_summary_items",
                "ai_summary_status",
                "ai_summary_skip_reason",
                "ai_summary_run",
                "ai_summary_completed_at",
                "ai_summary_error",
            ]
        )

        logger.info(
            f"Batch {batch_id}: AI summary {status} "
            f"(cost: ${run.total_cost_usd}, tokens: {run.total_input_tokens}+{run.total_output_tokens}, "
            f"items: {len(ai_summary_items) if ai_summary_items else 0})"
        )
        return {
            "batch_id": batch_id,
            "status": status,
            "skip_reason": skip_reason,
            "pipeline_run_id": run.id,
            "cost_usd": str(run.total_cost_usd),
            # Cache observability: {hits, misses} when the pipeline's
            # AI_CALL step runs with ``cache_one_liners`` (absent otherwise).
            "one_liner_cache": context.metadata.get("one_liner_cache"),
        }

    except Exception as exc:
        logger.error(
            f"summarize_notification_batch failed for batch {batch_id}: {exc}",
            exc_info=True,
        )
        batch.ai_summary_status = "FAILED"
        batch.ai_summary_error = str(exc)
        batch.save(update_fields=["ai_summary_status", "ai_summary_error"])

        # Retry with backoff — but never re-raise past the retries: this task
        # runs inside an email chord, so a hard failure would abort the chord
        # and the user would get no email at all.
        try:
            raise self.retry(exc=exc, countdown=60)
        except Retry:
            # Celery signalled a retry — propagate so the worker re-runs us.
            raise
        except MaxRetriesExceededError:
            logger.error(
                f"Batch {batch_id}: AI summary retries exhausted, "
                f"giving up (email will be sent without AI bullets)"
            )
            return {
                "batch_id": batch_id,
                "status": "FAILED",
                "error": str(exc),
                "retries_exhausted": True,
            }


def _collect_summary_items(decisions, context, pipeline_def):
    """
    Build per-decision one-liner items from a *map-mode* pipeline run.

    After a successful map step, ``context.per_item_outputs`` is keyed by
    ``str(decision.pk)``.  For single-mode pipelines the same dict still
    holds raw extracted texts, so items are only built when the pipeline
    actually has an active AI_CALL step in map mode.  Decisions without an
    entry (e.g. skipped by the map step) are simply left out.
    """
    is_map_mode = pipeline_def.steps.filter(
        step_type="AI_CALL", is_active=True, config__map_over_items=True
    ).exists()
    if not is_map_mode:
        return None

    per_item = context.per_item_outputs
    if not isinstance(per_item, dict) or not per_item:
        return None

    items = []
    for decision in decisions:
        one_liner = per_item.get(str(decision.pk))
        if not one_liner:
            continue
        items.append(
            {
                "decision_id": decision.pk,
                "ada": decision.ada,
                "subject": decision.subject,
                "one_liner": one_liner,
            }
        )
    return items or None


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
                # Shared per-decision one-liner cache (DecisionOneLiner):
                # identical (decision × extraction × generation-circumstances)
                # pairs reuse the stored one-liner at zero cost.
                CACHE_ONE_LINERS_FLAG: True,
                "prompt_kind": BATCH_ONE_LINER_PROMPT_KIND,
                "system_prompt": BATCH_MAP_SYSTEM_PROMPT,
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
                "system_prompt": BATCH_MERGE_SYSTEM_PROMPT,
                "merge_prompt_template": "Synthesize a single summary of these decision summaries:\n{{ text }}",
                "temperature": 0.3,
                # max_tokens intentionally omitted — see AI_CALL step above.
            },
        )
        logger.info("Created default notification_batch_summary_v1 pipeline")

    return pipeline
