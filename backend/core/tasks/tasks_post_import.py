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
  compute_entity_rankings  →  warm_analytics_cache  →  invalidate_browse_cache
  →  trigger_check_all_subscriptions  →  verify_high_value_amounts
  (DB snapshots)               (Redis cache)            (Notifications)         (AI amount audit)

Views warmed (all DashboardGrid sections):
  explore_orgs               → OrganizationsSection
  da_top_pairs               → TopRelationshipPairs (featured)
  top_payments               → TopPaymentsSection
  top_direct_assignments     → TopDirectAssignmentsSection
"""

from datetime import date, timedelta
import calendar

from celery import chain, shared_task
from core.services.feature_flag_service import feature_flags
from loguru import logger


# ---------------------------------------------------------------------------
# Calendar-aware window helpers
# ---------------------------------------------------------------------------

def _subtract_calendar_months(d: date, n: int) -> date:
    """
    Subtract *n* calendar months from *d*, clamping the day if the target
    month is shorter (e.g. 31 Mar → 28 Feb).

    Matches JavaScript's ``d.setMonth(d.getMonth() - n)`` behaviour.
    """
    month = d.month - n
    year = d.year
    while month <= 0:
        month += 12
        year -= 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(d.day, last_day))


def _calendar_windows(ref: date) -> list[tuple[str, date, date]]:
    """
    Return the 4 standard time windows using **calendar arithmetic**
    (matching the frontend's ``DateRangeContext.calculateDateRange``).

    Frontend reference (``DateRangeContext.js``)::
        yesterday: ref → ref                               # the reference date itself
        week:     start.setDate(end.getDate() - 7)         # pure days
        month:    start.setMonth(end.getMonth() - 1)        # calendar month
        year:     start.setFullYear(end.getFullYear() - 1)  # calendar year
    """
    return [
        ("daily",   ref,   ref),
        ("weekly",  ref - timedelta(days=7),   ref),
        ("monthly", _subtract_calendar_months(ref, 1),  ref),
        ("yearly",  date(ref.year - 1, ref.month,
                         min(ref.day, calendar.monthrange(ref.year - 1, ref.month)[1])),
                     ref),
    ]


def _build_warmup_sentinel_keys(
    view_name: str,
    start_str: str,
    end_str: str,
    kwargs: dict,
) -> list[str]:
    """
    Build the first-page cache key(s) for a view so L3 can set warmup
    status before calling the warm function.  This lets L2 (defer_on_miss)
    detect that L3 is already working and avoid dispatching a duplicate.

    Returns a list because some views (da_top_entities, da_top_orgs) warm
    two sort variants in one call.
    """
    from core.services.response_cache_service import response_cache

    page_size = str(kwargs.get("page_size", 20))

    if view_name == "explore_orgs":
        return [response_cache.build_key(
            "explore_orgs",
            start_date=start_str, end_date=end_str,
            limit=page_size, offset="0",
        )]

    if view_name == "da_top_pairs":
        return [response_cache.build_key(
            "da_top_pairs",
            start_date=start_str, end_date=end_str,
            limit=page_size, offset="0",
        )]

    if view_name == "top_payments":
        return [response_cache.build_key(
            "top_payments",
            start_date=start_str, end_date=end_str,
            limit=page_size, offset="0",
        )]

    if view_name == "top_direct_assignments":
        return [response_cache.build_key(
            "top_direct_assignments",
            start_date=start_str, end_date=end_str,
            limit=page_size, offset="0",
        )]

    if view_name == "top_by_amount":
        return [response_cache.build_key(
            "top_by_amount",
            start_date=start_str, end_date=end_str,
            limit=page_size, offset="0",
        )]

    # Fallback for unknown views
    return []


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
        # Invalidate browse caches so fresh entity data appears after import
        invalidate_browse_cache.si(),
        # Notifications: Check all active subscriptions against yesterday's data
        trigger_check_all_subscriptions.si(reference_date_str=reference_date_str),
        # Amount Verification: AI-based validation of high-value decisions
        verify_high_value_amounts.si(reference_date_str=reference_date_str),
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

    windows = _calendar_windows(ref)

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
      - explore_orgs              (explore/organizations/)          page_size=6, max_limit=200
      - da_top_pairs              (direct-assignments/top-pairs/)   page_size=6, max_limit=50
      - top_payments              (decisions/top-payments/)         page_size=5, max_limit=100
      - top_direct_assignments    (decisions/top-direct-assignments/) page_size=5, max_limit=100
      - top_by_amount             (decisions/top-by-amount/)        page_size=5, max_limit=100

    Views NOT warmed (frontend no longer calls these directly):
      - explore_decisions      frontend uses unified?view=decisions (not cached)
      - da_top_entities        frontend uses /entities/{afm}/top-organizations/
      - da_top_orgs            same as above
      - explore_decision_types frontend uses unified?view=decision_types
      - explore_statistics     frontend uses unified?view=statistics

    Args:
        reference_date_str: ISO-format date string. Defaults to today.
    """
    if not feature_flags.is_enabled("ANALYTICS_WARMUP_ENABLED"):
        logger.debug("ANALYTICS_WARMUP_ENABLED is disabled, skipping cache warmup")
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from core.services.analytics_precalc_service import (
        warm_da_top_pairs_window,
        warm_explore_orgs_window,
        warm_top_by_amount_window,
        warm_top_direct_assignments_window,
        warm_top_payments_window,
    )

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )

    windows = _calendar_windows(ref)

    logger.info(f"Warming analytics cache for {len(windows)} windows (ref={ref})")

    from core.services.response_cache_service import response_cache

    warmed = 0
    errors = []

    for label, start, end in windows:
        start_str = start.isoformat()
        end_str = end.isoformat()

        # ── page_size values MUST match what the frontend actually sends, ─
        #    because the cache key includes limit/page_size.  A mismatch
        #    means the warmed key never matches the request → defer_on_miss
        #    → 202 polling loop on the first request after every import.
        #
        #    Frontend reference:
        #      explore_orgs  → OrganizationsSection  PAGE_SIZE=6
        #      da_top_pairs  → HomePage             limit={6}
        #      unified       → DecisionsSection      PAGE_SIZE=5 (view=decisions,
        #                       statistics, decision_types, date_range)
        #
        #    Removed (frontend no longer calls these directly):
        #      explore_decisions  → frontend uses unified?view=decisions (not cached)
        #      da_top_entities    → frontend uses /entities/{afm}/top-organizations/
        #      da_top_orgs        → same as above
        #      explore_decision_types → frontend uses unified?view=decision_types
        #      explore_statistics    → frontend uses unified?view=statistics
        for view_name, warm_fn, kwargs in [
            ("explore_orgs", warm_explore_orgs_window, {"max_limit": 200, "page_size": 6}),
            ("da_top_pairs", warm_da_top_pairs_window, {"max_limit": 50, "page_size": 6}),
            ("top_payments", warm_top_payments_window, {"max_limit": 100, "page_size": 5}),
            ("top_direct_assignments", warm_top_direct_assignments_window, {"max_limit": 100, "page_size": 5}),
            ("top_by_amount", warm_top_by_amount_window, {"max_limit": 100, "page_size": 5}),
        ]:
            # ── Build sentinel warmup keys so L2 (defer_on_miss) can
            #     detect that L3 is already working on this view ──────
            sentinel_keys = _build_warmup_sentinel_keys(
                view_name, start_str, end_str, kwargs
            )
            for key in sentinel_keys:
                response_cache.set_warmup_status(key, "in_progress")

            try:
                warm_fn(
                    start_date_str=start_str,
                    end_date_str=end_str,
                    end_date=end,
                    **kwargs,
                )
                for key in sentinel_keys:
                    response_cache.set_warmup_status(key, "ready")
                warmed += 1
            except Exception as exc:
                for key in sentinel_keys:
                    response_cache.clear_warmup_status(key)
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


# ── On-demand single-window warmup (defer_on_miss) ──────────────────────


@shared_task
def warm_single_window(
    view_name: str,
    params: dict,
    cache_key: str,
):
    """
    On-demand warmup for a single (view, date-range) pair.

    Dispatched by cached_view on defer_on_miss cache miss when no custom
    defer_warmup_task is provided.

    Args:
        view_name: The cache_prefix from @cached_view (e.g. "explore_orgs")
        params: Dict of query params from the original request
        cache_key: The exact Redis cache key the frontend is polling for

    The task:
    1. Looks up the warm function from WARMUP_REGISTRY
    2. Calls it with the date range from params
    3. On success, marks warmup_status as "ready"
    4. On failure, clears the "in_progress" status so the next request retries
    """
    from core.services.analytics_precalc_service import WARMUP_REGISTRY
    from core.services.response_cache_service import response_cache

    warm_fn = WARMUP_REGISTRY.get(view_name)
    if not warm_fn:
        logger.warning(
            f"[warm_single_window] No warmup registered for view={view_name}"
        )
        return {"status": "unknown_view", "view_name": view_name}

    # Extract date params
    start_date_str = params.get("start_date", "")
    end_date_str = params.get("end_date", "")

    if not start_date_str or not end_date_str:
        logger.warning(
            f"[warm_single_window] Missing date params for view={view_name}, "
            f"params={params}"
        )
        response_cache.clear_warmup_status(cache_key)
        return {"status": "missing_date_params", "view_name": view_name}

    try:
        from datetime import date as date_type

        end_date = date_type.fromisoformat(end_date_str)

        # Call the warm function
        warm_fn(
            start_date_str=start_date_str,
            end_date_str=end_date_str,
            end_date=end_date,
        )

        # Mark warmup as ready
        response_cache.set_warmup_status(cache_key, "ready")
        logger.info(
            f"[warm_single_window] Successfully warmed view={view_name} "
            f"[{start_date_str} → {end_date_str}]"
        )
        return {
            "status": "warmed",
            "view_name": view_name,
            "start_date": start_date_str,
            "end_date": end_date_str,
        }

    except Exception as exc:
        logger.error(
            f"[warm_single_window] Failed to warm view={view_name} "
            f"[{start_date_str} → {end_date_str}]: {exc}"
        )
        # Clear the in_progress status so the next user request can retry
        response_cache.clear_warmup_status(cache_key)
        return {
            "status": "failed",
            "view_name": view_name,
            "error": str(exc),
        }


# ── Browse cache invalidation ──────────────────────────────────────────


@shared_task
def invalidate_browse_cache():
    """
    Invalidate all browse API response caches after daily import.

    Browse views show the current state of entities.  Since entities may be
    added/updated during import, we flush cached pages so the next user
    request picks up fresh data.

    Uses a simple invalidation rather than warmup because:
      - Browse queries are cheap (functional indexes)
      - The cache key space is large (type × letter × offset × limit)
      - Warming every combination is wasteful
    """
    from core.services.response_cache_service import response_cache

    count = response_cache.invalidate_prefix("browse")
    logger.info(f"[invalidate_browse_cache] Invalidated {count} browse cache keys")
    return {"status": "completed", "keys_invalidated": count}


# ── Notifications — Bulk check all active subscriptions ──────────────────

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


# ── Amount Verification — AI-based validation of high-value decisions ─────

@shared_task
def verify_high_value_amounts(reference_date_str: str | None = None):
    """
    Verify AND correct monetary amounts for decisions exceeding the
    high-value threshold by reading the actual document text.

    Two-phase pipeline:
      1. Verification (AmountVerificationService): runs regex/AI detection
         and persists TextProcessRun + TextProcessResolution records for
         audit trail.
      2. Correction (AmountCorrectionService): runs the cents-based detector
         and — when the text has a clear different amount with a ×100/÷100
         decimal-shift — stores the corrected value on each affected
         ``DecisionAmountField.verified_amount`` so all downstream consumers
         (via ``COALESCE(verified_amount, amount)``) use the corrected value.

    Catches data-entry errors where decimal separators are misplaced
    (e.g. €30,000.00 recorded as €3,000,000 in Diavgeia).

    This task is idempotent — it skips decisions that have already been
    verified/corrected.  It runs as a standalone @shared_task so it can
    also be triggered manually via the Django admin or management command.

    Args:
        reference_date_str: ISO-format date string of the import day.  Only
            decisions *imported* on that day (``Decision.created_at`` within
            [ref 00:00, ref+1 00:00)) are processed — so a daily post-import
            run never fans out over the entire historical backlog.  Pass a
            past date to backfill a specific import day.  If omitted,
            defaults to today.

    Returns:
        Dict with batch summary from both phases.
    """
    if not feature_flags.is_enabled("POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"):
        logger.debug(
            "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED is disabled, skipping"
        )
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from datetime import datetime, timedelta

    from django.utils import timezone as dj_timezone

    from core.services.amount_verification_service import AmountVerificationService
    from core.services.amount_correction_service import AmountCorrectionService

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )

    # Scope to decisions IMPORTED on the reference day — not issue_date, so
    # old decisions (e.g. 2021) that were only imported today are included,
    # while the historical backlog is never re-scanned.
    imported_since = dj_timezone.make_aware(
        datetime.combine(ref, datetime.min.time())
    )
    imported_until = imported_since + timedelta(days=1)

    logger.info(
        f"Starting amount verification + correction batch "
        f"(decisions imported on {ref})"
    )

    # ── Phase 1: Verification (audit trail + discrepancy detection) ───
    verify_service = AmountVerificationService()
    verify_result = verify_service.verify_high_value_decisions(
        imported_since=imported_since,
        imported_until=imported_until,
        limit=500,
    )

    logger.info(
        f"Amount verification complete: {verify_result['verified']} verified, "
        f"{verify_result['discrepancies']} discrepancies found"
    )

    # ── Phase 2: Correction (cents-based, updates Decision model) ────
    correction_service = AmountCorrectionService()
    correct_result = correction_service.correct_high_value_decisions(
        imported_since=imported_since,
        imported_until=imported_until,
        limit=500,
    )

    logger.info(
        f"Amount correction complete: {correct_result['corrected']} corrected, "
        f"{correct_result['consistent']} consistent, "
        f"{correct_result['no_text']} no text, "
        f"{correct_result['errors']} errors"
    )

    return {
        "status": "completed",
        "reference_date": str(ref),
        "verification": verify_result,
        "correction": correct_result,
    }
