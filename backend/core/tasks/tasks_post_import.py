"""
Post-Import Task Orchestrator

Single entry point for all work that should run after a GLOBAL daily import
completes.  Each piece of work is a separate @shared_task with its own feature
flag, and the orchestrator chains them in the right order.

To add new post-import work:
  1. Create your @shared_task (in its own module if large, or here if small)
  2. Add it to the chain in post_daily_import_orchestrator()
  3. Add a feature flag key to KNOWN_FLAGS in feature_flag_service.py

Execution order (via Celery chord — sequential, fail-fast):
  verify_high_value_amounts
      └─ chord: [verify_correct_decision_batch × N]  →  finalize_amount_verification
      └─ chord body continues: compute_entity_rankings  →  invalidate_browse_cache
         →  warm_analytics_cache  →  trigger_check_all_subscriptions
  (amount correction)                (DB snapshots)             (Redis cache)             (Notifications)

Amount verification runs FIRST: it is the only step that mutates monetary values
(``verified_amount`` + the invalid-amount marker), and the steps that read
amounts through the facet layer (entity rankings, analytics cache warming) must
therefore run after it — otherwise they publish pre-correction figures.

WHY FAN-OUT (2026-09-12 incident): the previous implementation ran up to 500
sequential document downloads inside ONE task.  A single 6h task (a) grows
worker memory unchecked — Celery's ``max_tasks_per_child`` /
``max_memory_per_child`` only take effect BETWEEN tasks — and (b) holds one
persistent DB connection for hours, which eventually dies with
"server closed the connection unexpectedly" (CONN_MAX_AGE staleness), losing
the whole batch.  One child task per decision bounds memory per child, makes
the memory limits effective, isolates failures to a single decision, and gives
per-decision progress in the logs.  The chord body guarantees the rest of the
post-import chain still runs only after ALL children complete.

Views warmed (all DashboardGrid sections):
  explore_orgs               → OrganizationsSection
  da_top_pairs               → TopRelationshipPairs (featured)
  top_payments               → TopPaymentsSection
  top_direct_assignments     → TopDirectAssignmentsSection
"""

from datetime import date, timedelta
import calendar
import functools
import time

from celery import chain, chord, shared_task
from core.services.feature_flag_service import feature_flags
from loguru import logger


# ---------------------------------------------------------------------------
# Task-run logging decorator
# ---------------------------------------------------------------------------
#
# Celery's own task-lifecycle signals are DISABLED in this project (see the
# commented-out ``task_prerun`` / ``task_postrun`` / ``task_failure`` handlers
# in ``diavgeia_project/celery.py``), and ``CELERY_TASK_EVENT_LOG_LEVEL``
# defaults to WARNING — so the "Task … received/succeeded" lines are hidden and
# a task that logs nothing of its own appears to vanish.  This decorator gives
# every post-import task a guaranteed start / finish line with its duration and
# a one-line summary of what it did.
#
# Apply it UNDER ``@shared_task`` so the wrapper is the task body:
#
#     @shared_task
#     @log_task_run
#     def my_task(...): ...
#
# ``functools.wraps`` preserves ``__name__``/signature, so the Celery task name
# is unchanged.

# Result-dict keys surfaced in the finish line (counts an operator cares about).
_SUMMARY_KEYS = (
    "reference_date",
    "windows_processed",
    "keys_warmed",
    "keys_invalidated",
    "task_id",
    "verified",
    "discrepancies",
    "corrected",
    "consistent",
    "no_text",
    "errors",
)


def _summarize_result(result) -> str:
    """Render a task's return value as a short, log-safe one-liner."""
    if not isinstance(result, dict):
        return f"result={result!r}"

    parts: list[str] = []
    if result.get("status") is not None:
        parts.append(f"status={result['status']}")
    for key in _SUMMARY_KEYS:
        value = result.get(key)
        if value is not None:
            parts.append(f"{key}={value}")
    # Nested phase summaries (verify_high_value_amounts returns three dicts).
    for phase in ("verification", "correction", "discovery"):
        sub = result.get(phase)
        if isinstance(sub, dict):
            for key, value in sub.items():
                if key == "results":
                    continue  # per-decision payload — never log it
                if isinstance(value, (str, int, float, bool)):
                    parts.append(f"{phase}.{key}={value}")
    return ", ".join(parts) or "no result"


def log_task_run(func=None, *, swallow_errors: bool = False):
    """
    Log ``started`` / ``finished`` (+ duration and result summary) around a task.

    Args:
        swallow_errors: When True, an exception is logged (at ERROR, with
            traceback) and converted into ``{"status": "error", "error": …}``
            so a Celery **chain keeps going** instead of fail-stopping on this
            task.  The failure is still visible: the ERROR log, the returned
            result, and the ``finished … status=error`` line.  Default False
            re-raises, preserving normal Celery failure/retry semantics.

    Usable bare (``@log_task_run``) or with arguments
    (``@log_task_run(swallow_errors=True)``).
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            started = time.perf_counter()
            logger.info(f"[task] {fn.__name__} started")
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                logger.exception(
                    f"[task] {fn.__name__} FAILED after "
                    f"{time.perf_counter() - started:.1f}s"
                )
                if swallow_errors:
                    logger.error(
                        f"[task] {fn.__name__} — failure swallowed so the "
                        f"post-import chain continues"
                    )
                    return {"status": "error", "error": str(exc)}
                raise
            logger.info(
                f"[task] {fn.__name__} finished in "
                f"{time.perf_counter() - started:.1f}s — "
                f"{_summarize_result(result)}"
            )
            return result

        return wrapper

    if func is not None:  # used bare: @log_task_run
        return decorator(func)
    return decorator  # used with args: @log_task_run(...)


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
@log_task_run
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
    #
    # A Celery ``chain`` is SEQUENTIAL (each task starts only after the
    # previous one succeeds), not concurrent.  Order matters for correctness:
    task_chain = chain(
        # Amount Verification: the ONLY step that mutates monetary values
        # (verified_amount + invalid-amount marker).  It must run before any
        # step that reads amounts through the facet layer — otherwise
        # rankings and warmed caches encode pre-correction figures.
        verify_high_value_amounts.si(reference_date_str=reference_date_str),
        # Track 2: Compute entity rankings (DB snapshots) from corrected amounts
        compute_entity_rankings.si(reference_date_str=reference_date_str),
        # Invalidate browse caches so fresh entity data appears after import
        # (runs before warming; it touches the disjoint "browse" prefix)
        invalidate_browse_cache.si(),
        # Track 1: Warm the response cache for heavy views with fresh amounts
        warm_analytics_cache.si(reference_date_str=reference_date_str),
        # Notifications: Check all active subscriptions against the new data
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
@log_task_run(swallow_errors=True)
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
@log_task_run(swallow_errors=True)
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
@log_task_run
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
@log_task_run(swallow_errors=True)
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
    letters_count = response_cache.invalidate_browse_available_letters()
    logger.info(
        f"[invalidate_browse_cache] Invalidated {count} browse cache keys "
        f"and {letters_count} available_letters keys"
    )
    return {"status": "completed", "keys_invalidated": count + letters_count}

# ── Notifications — Bulk check all active subscriptions ──────────────────

@shared_task
@log_task_run(swallow_errors=True)
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
#
# FAN-OUT ARCHITECTURE (see module docstring for the why):
#   verify_high_value_amounts        — parent: resolve candidates, dispatch chord
#   verify_correct_decision_batch    — child: one BATCH of decisions through
#                                      verify+correct
#   finalize_amount_verification     — chord body: aggregate, invalidate caches,
#                                      run discovery, CONTINUE the post-import
#                                      chain (rankings → invalidate → warm →
#                                      notifications) via a nested chain.

# Per-decision work is dispatched in batches of this size so the parent's
# candidate query result is chunked into manageable child tasks.
# Tunable via VERIFY_AMOUNT_BATCH_SIZE (default 50).  Each child does at most
# ``batch_size`` document reads, so per-child memory stays bounded and
# Celery's max_memory_per_child remains effective.
import os

VERIFY_BATCH_SIZE = int(os.environ.get("VERIFY_AMOUNT_BATCH_SIZE", 30))

# Hard cap on candidates per run (cost control; matches the previous
# monolithic limit=500).
VERIFY_CANDIDATE_LIMIT = 500


@shared_task
@log_task_run(swallow_errors=True)
def verify_high_value_amounts(reference_date_str: str | None = None):
    """
    Verify AND correct monetary amounts for decisions exceeding the
    high-value threshold by reading the actual document text.

    This is the PARENT task: it resolves the candidate pool (fast, indexed
    query) and fans out one child task per batch of decisions via a Celery
    chord.  The chord body (``finalize_amount_verification``) runs the
    discovery sweep, invalidates amount-dependent caches, and dispatches the
    REST of the post-import chain — so rankings/warm/notifications still run
    only after every child has finished.

    Per-decision work (in ``verify_correct_decision_batch``):
      1. Verification (AmountVerificationService.verify_decision): regex/AI
         detection, persists TextProcessRun + TextProcessResolution.
      2. Correction (AmountCorrectionService.correct_decision): cents-based
         ×100/÷100 detector, writes ``DecisionAmountField.verified_amount``
         and the invalid-amount marker for non-monetary values.

    Catches data-entry errors where decimal separators are misplaced
    (e.g. €30,000.00 recorded as €3,000,000 in Diavgeia).

    Idempotent — children skip decisions that already have a COMPLETED
    verification resolution.

    Args:
        reference_date_str: ISO-format date string of the import day.  Only
            decisions *imported* on that day (``Decision.created_at`` within
            [ref 00:00, ref+1 00:00)) are processed — so a daily post-import
            run never fans out over the entire historical backlog.  Pass a
            past date to backfill a specific import day.  If omitted,
            defaults to today.

    Returns:
        Dict with dispatch summary (candidate count, batch count).
    """
    if not feature_flags.is_enabled("POST_IMPORT_AMOUNT_VERIFICATION_ENABLED"):
        logger.debug(
            "POST_IMPORT_AMOUNT_VERIFICATION_ENABLED is disabled, skipping"
        )
        return {"status": "skipped", "reason": "feature_flag_disabled"}

    from datetime import datetime, timedelta

    from django.utils import timezone as dj_timezone

    from core.services.amount_verification_service import AmountVerificationService

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

    # Resolve the candidate pool ONCE (the heavy aggregate query — now
    # index-backed on created_at).  The service's batch method materialises
    # the limited candidate set; we reuse its query shape via the same
    # service so the candidate selection stays in ONE place.
    verify_service = AmountVerificationService()
    decisions = verify_service.get_high_value_candidates(
        imported_since=imported_since,
        imported_until=imported_until,
        limit=VERIFY_CANDIDATE_LIMIT,
    )

    total = len(decisions)
    logger.info(
        f"Amount verification: {total} decisions above threshold "
        f"(imported on {ref})"
    )

    if not decisions:
        # Nothing to do — run the finalize path inline (no chord needed) so
        # the rest of the post-import chain still executes.
        finalize_amount_verification.run(
            [], reference_date_str=reference_date_str
        )
        return {
            "status": "completed",
            "reference_date": str(ref),
            "total_candidates": 0,
            "batches_dispatched": 0,
        }

    # Fan out: one child per batch, chord body = finalize + chain continuation.
    decision_ids = [d.id for d in decisions]
    batches = [
        decision_ids[i : i + VERIFY_BATCH_SIZE]
        for i in range(0, len(decision_ids), VERIFY_BATCH_SIZE)
    ]

    header = [
        verify_correct_decision_batch.si(batch)
        for batch in batches
    ]
    # NOTE: the body MUST be a mutable signature (.s) — a chord passes the
    # header results as the body's first positional argument, and .si would
    # silently discard them (batch_summaries would arrive empty).
    task_chord = chord(header)(
        finalize_amount_verification.s(reference_date_str=reference_date_str)
    )

    logger.info(
        f"Amount verification fan-out: {len(batches)} batch(es) of up to "
        f"{VERIFY_BATCH_SIZE} decisions dispatched (chord id {task_chord.id})"
    )

    return {
        "status": "dispatched",
        "reference_date": str(ref),
        "total_candidates": total,
        "batches_dispatched": len(batches),
        "batch_size": VERIFY_BATCH_SIZE,
    }


@shared_task(
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def verify_correct_decision_batch(self, decision_ids: list[int]) -> dict:
    """
    Child task: verify AND correct ONE BATCH of decisions (up to
    ``VERIFY_BATCH_SIZE``, passed as an explicit ID list by the parent).

    Runs the per-decision verify (audit trail) + correct (mutates
    verified_amount / invalid marker) paths.  Bounded work per task: at most
    ``VERIFY_BATCH_SIZE`` document reads, so Celery's per-child memory limits
    are effective and one poisoned decision cannot lose the batch
    (per-decision errors are counted, never raised).

    DB hygiene: closes stale persistent connections up front — a child lives
    minutes, not hours, but CONN_MAX_AGE connections can still be stale if
    the worker was idle.
    """
    from django.db import close_old_connections

    from core.models.decisions import Decision
    from core.services.amount_correction_service import AmountCorrectionService
    from core.services.amount_verification_service import AmountVerificationService

    close_old_connections()

    verify_service = AmountVerificationService()
    correction_service = AmountCorrectionService()

    summary = {
        "verified": 0,
        "discrepancies": 0,
        "corrected": 0,
        "consistent": 0,
        "no_text": 0,
        "skipped": 0,
        "errors": 0,
    }

    for decision_id in decision_ids:
        try:
            decision = Decision.objects.get(id=decision_id)

            # Phase 1: verification (audit trail + discrepancy detection).
            # Skips decisions that already have a COMPLETED resolution.
            verify_result = verify_service.verify_decision(decision)
            if verify_result["status"] == "completed":
                summary["verified"] += 1
                if verify_result.get("has_discrepancy"):
                    summary["discrepancies"] += 1

            # Phase 2: correction (cents-based, mutates verified_amount).
            correct_result = correction_service.correct_decision(
                decision, dry_run=False, read_if_missing=True
            )
            status = correct_result["status"]
            if status in ("corrected", "would_correct"):
                summary["corrected"] += 1
            elif status == "consistent":
                summary["consistent"] += 1
            elif status == "no_text_amounts_found":
                summary["no_text"] += 1
            else:
                summary["skipped"] += 1
        except Exception as exc:
            logger.error(
                f"verify_correct_decision_batch: decision {decision_id} "
                f"failed: {exc}",
                exc_info=True,
            )
            summary["errors"] += 1

    logger.info(
        f"verify_correct_decision_batch done: {summary} "
        f"({len(decision_ids)} decisions)"
    )
    return summary


@shared_task
@log_task_run(swallow_errors=True)
def finalize_amount_verification(
    batch_summaries: list[dict],
    reference_date_str: str | None = None,
):
    """
    Chord body: aggregate child results, invalidate caches, run discovery,
    and CONTINUE the post-import chain.

    Receives the list of per-batch summary dicts from the chord header.
    Dispatches the remaining post-import tasks (rankings → invalidate →
    warm → notifications) as a nested chain so the ordering guarantee
    (amounts corrected BEFORE anything reads them) is preserved.
    """
    from datetime import datetime, timedelta

    from django.utils import timezone as dj_timezone

    ref = (
        date.fromisoformat(reference_date_str)
        if reference_date_str
        else date.today()
    )
    imported_since = dj_timezone.make_aware(
        datetime.combine(ref, datetime.min.time())
    )
    imported_until = imported_since + timedelta(days=1)

    # ── Aggregate child summaries ─────────────────────────────────────
    totals = {
        "verified": 0,
        "discrepancies": 0,
        "corrected": 0,
        "consistent": 0,
        "no_text": 0,
        "skipped": 0,
        "errors": 0,
    }
    for s in batch_summaries or []:
        if not isinstance(s, dict):
            continue
        for key in totals:
            totals[key] += s.get(key, 0) or 0

    logger.info(
        f"Amount verification + correction complete: {totals} "
        f"({len(batch_summaries or [])} batch(es))"
    )

    # ── Amounts changed → drop the analytics caches that encode them ──
    # The warm step later in this chain repopulates only the exact
    # (view, window, limit) keys it knows, so any OTHER cached range would
    # keep serving pre-correction figures.  These prefixes cover the views
    # that read amounts via the facet layer (explore_orgs / da_top_pairs are
    # NOT matched by the "top_" prefix).
    if totals["corrected"] or totals["discrepancies"]:
        from core.services.response_cache_service import response_cache

        invalidated = sum(
            response_cache.invalidate_prefix(prefix)
            for prefix in ("top_", "da_top_pairs", "explore_orgs")
        )
        logger.info(
            f"Amount correction changed values — invalidated {invalidated} "
            f"amount-dependent analytics cache key(s)"
        )

    # ── Discovery (non-monetary values recorded as amounts) ───────────
    # DB-only, read-only sweep — see _discover_non_monetary_values.
    discovery_result = _discover_non_monetary_values(
        imported_since=imported_since,
        imported_until=imported_until,
    )

    # ── Continue the post-import chain ────────────────────────────────
    # The chord replaced the first link of the old chain, so the remaining
    # tasks are dispatched here, in the same order as before.
    continuation = chain(
        compute_entity_rankings.si(reference_date_str=reference_date_str),
        invalidate_browse_cache.si(),
        warm_analytics_cache.si(reference_date_str=reference_date_str),
        trigger_check_all_subscriptions.si(reference_date_str=reference_date_str),
    )
    continuation_result = continuation.apply_async()
    logger.info(
        f"Post-import continuation dispatched (chain task id: "
        f"{continuation_result.id}) for reference date {ref}"
    )

    return {
        "status": "completed",
        "reference_date": str(ref),
        "totals": totals,
        "discovery": discovery_result,
        "continuation_task_id": str(continuation_result.id),
    }


def _discover_non_monetary_values(
    imported_since=None,
    imported_until=None,
) -> dict:
    """
    Log (and count) decisions imported in the window whose recorded amount is
    actually a non-monetary value (AFM/KAE).

    Read-only: it never mutates ``verified_amount`` — the guard already
    refuses to write such values there.  The purpose is observability so
    operators know a case needs the real amount looked up manually.
    """
    from core.models.decisions import Decision
    from core.services.non_monetary_value_guard import (
        KIND_AFM,
        KIND_KAE,
        collect_non_monetary_values,
    )

    decisions = (
        Decision.objects.filter(
            amount_fields__isnull=False,
        )
        .prefetch_related("entity_relationships__entity", "amount_fields")
        .distinct()
    )
    if imported_since is not None:
        decisions = decisions.filter(created_at__gte=imported_since)
    if imported_until is not None:
        decisions = decisions.filter(created_at__lt=imported_until)

    afm_count = 0
    kae_count = 0
    flagged: list[dict] = []

    for decision in decisions.iterator(chunk_size=500):
        anomalies = collect_non_monetary_values(decision)
        if not anomalies:
            continue
        for anomaly in anomalies:
            if anomaly.kind == KIND_AFM:
                afm_count += 1
            elif anomaly.kind == KIND_KAE:
                kae_count += 1
            flagged.append(
                {
                    "ada": decision.ada,
                    "kind": anomaly.kind,
                    "source_field": anomaly.source_field,
                    "amount": str(anomaly.amount),
                    "matched_value": anomaly.matched_value,
                }
            )
            logger.warning(
                f"Non-monetary-value-as-amount: decision {decision.id} "
                f"({decision.ada}) {anomaly.source_field}="
                f"{anomaly.amount} equals {anomaly.kind} {anomaly.matched_value}"
            )

    result = {
        "afm_anomalies": afm_count,
        "kae_anomalies": kae_count,
        "total_anomalies": afm_count + kae_count,
        "sample": flagged[:50],
    }
    logger.info(f"Non-monetary-value discovery: {result}")
    return result
