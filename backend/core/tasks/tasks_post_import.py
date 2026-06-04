"""
Post-Import Task Orchestrator

Single entry point for all work that should run after a GLOBAL daily import
completes.  Each piece of work is a separate @shared_task with its own feature
flag, and the orchestrator chains them in the right order.

To add new post-import work:
  1. Create your @shared_task (in its own module if large, or here if small)
  2. Add it to the chain in post_daily_import_orchestrator()
  3. Add a feature flag key to KNOWN_FLAGS in feature_flag_service.py

Execution order (via Celery chain):
  compute_entity_rankings  →  warm_analytics_cache  →  check_all_subscriptions
  (Track 2: DB snapshots)     (Track 1: Redis cache)     (Notifications)
"""

from datetime import date, timedelta

from celery import chain, shared_task
from core.services.feature_flag_service import feature_flags
from loguru import logger


# ---------------------------------------------------------------------------
# Orchestrator — the single place to wire post-import work
# ---------------------------------------------------------------------------


@shared_task
def post_daily_import_orchestrator(job_id: int, reference_date_str: str):
    """
    Orchestrate all post-daily-import tasks in order.

    Called from ImportJobQueue.on_job_completed() ONLY when the completed
    job is a global daily import (no org/unit/signer filter).

    Tasks are chained so each runs only after the previous succeeds.
    If a task fails, the chain stops (fail-fast).  Each task is idempotent
    so re-running the orchestrator is safe.

    Args:
        job_id: The completed ImportJob's ID (for logging).
        reference_date_str: ISO-format date string for the "as-of" date.
    """
    if not feature_flags.is_enabled("POST_IMPORT_ORCHESTRATOR_ENABLED"):
        logger.info("POST_IMPORT_ORCHESTRATOR_ENABLED is disabled, skipping")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    logger.info(
        f"Post-import orchestrator starting for job #{job_id} "
        f"(reference date: {reference_date_str})"
    )

    reference_date = date.fromisoformat(reference_date_str)

    # Build the task chain — add new tasks here ↓
    task_chain = chain(
        # Track 2: Compute entity rankings (DB snapshots) — must run first
        # so cache warming can use fresh stats
        compute_entity_rankings.si(reference_date_str=reference_date_str),
        # Track 1: Warm the response cache for heavy views
        warm_analytics_cache.si(reference_date_str=reference_date_str),
        # Notifications: Check all active subscriptions against yesterday's data
        trigger_check_all_subscriptions.si(reference_date_str=reference_date_str),
    )

    result = task_chain.apply_async()
    logger.info(
        f"Post-import chain dispatched (chain task id: {result.id}) "
        f"for job #{job_id}"
    )

    return {
        "status": "dispatched",
        "job_id": job_id,
        "chain_task_id": str(result.id),
        "reference_date": reference_date_str,
    }


# ---------------------------------------------------------------------------
# Track 2 — Persistent Entity Rankings (DB snapshots)
# ---------------------------------------------------------------------------

@shared_task
def compute_entity_rankings(reference_date_str: str | None = None):
    """
    Pre-compute per-entity statistics for the 4 standard time windows.

    See: backend/notes/02.precalculate/02. Global Stats

    Computes total_amount, decision_count, unique_org_count, avg_amount,
    median_amount, mode_amount, rank_by_amount, rank_by_frequency for each
    AFMEntity across daily/weekly/monthly/yearly windows.

    Stores results in AnalyticsSnapshotRun + EntityAnalyticsSnapshot models.

    Args:
        reference_date_str: ISO-format date string. Defaults to today.
    """
    if not feature_flags.is_enabled("ANALYTICS_PRECALC_ENABLED"):
        logger.debug("ANALYTICS_PRECALC_ENABLED is disabled, skipping entity rankings")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )

    windows = [
        ("daily", ref - timedelta(days=1), ref - timedelta(days=1)),
        ("weekly", ref - timedelta(days=7), ref),
        ("monthly", ref - timedelta(days=30), ref),
        ("yearly", ref - timedelta(days=365), ref),
    ]

    logger.info(f"Computing entity rankings for {len(windows)} windows (ref={ref})")

    # TODO: Implement _compute_and_store per window
    # for label, start, end in windows:
    #     _compute_and_store(label, ref, start, end)

    return {
        "status": "stub",
        "reference_date": str(ref),
        "windows_processed": len(windows),
    }


# ---------------------------------------------------------------------------
# Track 1 — Redis Cache Warming (view-level, ephemeral)
# ---------------------------------------------------------------------------

@shared_task
def warm_analytics_cache(reference_date_str: str | None = None):
    """
    Pre-populate ResponseCacheService keys for the 4 standard time windows.

    See: backend/notes/02.precalculate/01. Cache heavy views

    Ensures the first real user request to heavy analytics views is always a
    cache hit.  Uses the SAME key format as the cached_view decorator so the
    cache keys match exactly.

    Views warmed:
      - explore_orgs  (explore/organizations/)
      - da_top_pairs  (direct-assignments/top-pairs/)

    Args:
        reference_date_str: ISO-format date string. Defaults to today.
    """
    if not feature_flags.is_enabled("ANALYTICS_WARMUP_ENABLED"):
        logger.debug("ANALYTICS_WARMUP_ENABLED is disabled, skipping cache warmup")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from core.services.analytics_precalc_service import (
        warm_da_top_pairs_window,
        warm_explore_orgs_window,
    )

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )

    windows = [
        ("daily", ref - timedelta(days=1), ref - timedelta(days=1)),
        ("weekly", ref - timedelta(days=7), ref),
        ("monthly", ref - timedelta(days=30), ref),
        ("yearly", ref - timedelta(days=365), ref),
    ]

    logger.info(f"Warming analytics cache for {len(windows)} windows (ref={ref})")

    warmed = 0
    errors = []

    for label, start, end in windows:
        start_str = start.isoformat()
        end_str = end.isoformat()

        for view_name, warm_fn, kwargs in [
            ("explore_orgs", warm_explore_orgs_window, {"limit": 6}),
            ("da_top_pairs", warm_da_top_pairs_window, {"limit": 20, "offset": 0}),
        ]:
            try:
                warm_fn(
                    start_date_str=start_str,
                    end_date_str=end_str,
                    end_date=end,
                    **kwargs,
                )
                warmed += 1
            except Exception as exc:
                logger.warning(
                    f"[warm_analytics_cache] Failed to warm {view_name} "
                    f"for window {label} ({start_str} → {end_str}): {exc}"
                )
                errors.append(
                    {"window": label, "view": view_name, "error": str(exc)}
                )

    logger.info(
        f"Analytics cache warming complete: {warmed} keys warmed, "
        f"{len(errors)} errors (ref={ref})"
    )

    return {
        "status": "completed",
        "reference_date": str(ref),
        "windows_warmed": len(windows),
        "keys_warmed": warmed,
        "errors": errors,
    }


# ---------------------------------------------------------------------------
# Notifications — Bulk check all active subscriptions
# ---------------------------------------------------------------------------

@shared_task
def trigger_check_all_subscriptions(reference_date_str: str | None = None):
    """
    Trigger a check of all active notification subscriptions against
    yesterday's new decisions.

    Delegates to notifications.tasks.check_all_active_subscriptions which
    fans out to individual check_single_subscription tasks so each
    subscription is checked independently (and can be retried individually).

    Args:
        reference_date_str: ISO-format date string. Defaults to today.
    """
    if not feature_flags.is_enabled("POST_IMPORT_NOTIFICATIONS_ENABLED"):
        logger.debug(
            "POST_IMPORT_NOTIFICATIONS_ENABLED is disabled, "
            "skipping notification checks"
        )
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from notifications.tasks.notification_tasks import check_all_active_subscriptions

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )

    logger.info(f"Triggering bulk notification check for reference date {ref}")

    result = check_all_active_subscriptions.delay()

    return {
        "status": "dispatched",
        "reference_date": str(ref),
        "task_id": str(result.id),
    }
