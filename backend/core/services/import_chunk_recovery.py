"""
Chunk-level recovery for import jobs.

Two independent failure modes are handled here:

1. **Surviving payloads** — a chunk task was lost but its Redis payload
   still exists.  The chunk is redispatched with at-least-once semantics.
2. **Lost payloads** — the payload is gone (consumed by a task that never
   reported, or expired).  The chunk is recorded as failed so the job can
   reach a terminal state instead of blocking the import queue forever.

The DB chunk counters are never trusted as the source of truth: per-chunk
outcomes recorded by :class:`RedisDecisionCache` are reconciled into them.
"""

from typing import Any, Dict, List, Optional

from core.models.import_jobs import ImportJob
from core.services.redis_decision_cache import RedisDecisionCache, parse_chunk_index
from loguru import logger

# A repaired job must not re-create the original connection storm.  Stagger
# redispatches and cap how many chunks one watchdog tick hands out per job;
# the next tick continues the remainder.
CHUNK_REDISPATCH_MAX_PER_JOB = 50
CHUNK_REDISPATCH_STAGGER_SECONDS = 0.5
CHUNK_REDISPATCH_MAX_DELAY_SECONDS = 60.0


class ImportChunkRecoveryService:
    """Inspect and repair a job whose chunk counters are not advancing."""

    def __init__(self, cache: Optional[RedisDecisionCache] = None):
        self.cache = cache or RedisDecisionCache()

    def inspect_job(self, job: ImportJob) -> Dict[str, Any]:
        """Return the recoverability picture without changing anything."""
        total = job.total_chunks
        missing = total - job.chunks_completed - job.chunks_failed
        if total <= 0 or missing <= 0:
            return {
                "job_id": job.id,
                "missing": max(missing, 0),
                "recoverable": [],
                "lost": [],
                "accounted": {},
            }

        states = self.cache.get_job_chunk_states(job.id)
        chunk_ids = self.cache.list_job_chunk_ids(job.id)
        key_indexes = {
            index
            for index in (parse_chunk_index(chunk_id) for chunk_id in chunk_ids)
            if index is not None and 0 <= index < total
        }

        reported = job.chunks_completed + job.chunks_failed

        # Jobs created before per-chunk state existed have an empty hash even
        # though most chunks are already counted.  Never infer that every
        # unrecorded index is lost: the counter gap is the only trustworthy
        # number of missing chunks.  Recorded-but-uncounted chunks (a worker
        # died between the Redis write and the DB update) reduce the gap
        # without needing action.
        recorded_unreported = max(0, len(states) - reported)

        recoverable = sorted(
            index
            for index in key_indexes
            if index not in states
        )[:missing]

        lost_candidates = [
            index
            for index in range(total)
            if index not in states and index not in key_indexes
        ]
        lost_count = max(
            0, missing - len(recoverable) - recorded_unreported
        )
        lost = lost_candidates[:lost_count]

        return {
            "job_id": job.id,
            "missing": missing,
            "reported": reported,
            "recorded_unreported": recorded_unreported,
            "recoverable": recoverable,
            "lost": lost,
            "accounted": states,
        }

    def recover_job(self, job: ImportJob, dispatch: bool = True) -> Dict[str, Any]:
        """Repair one job: redispatch survivors, account for lost chunks.

        Returns a summary suitable for logging and admin messages.
        """
        snapshot = self.inspect_job(job)
        if snapshot["missing"] <= 0:
            return {"status": "ok", "job_id": job.id, "missing": 0, "dispatched": []}

        recoverable: List[int] = snapshot["recoverable"]
        lost: List[int] = snapshot["lost"]

        # Account for payloads that can never be recovered.  Recording the
        # failure in the chunk-state hash (not incrementing per chunk) keeps
        # this idempotent when the watchdog runs again.
        newly_lost = 0
        for index in lost:
            if self.cache.mark_chunk_state(job.id, index, "failed"):
                newly_lost += 1

        # Nothing to redispatch, and at least one payload is gone: close the
        # job with an explicit reason before reconciling counters.  This keeps
        # the failure visible instead of silently becoming a normal completion.
        if newly_lost and not recoverable:
            reason = (
                f"Chunk watchdog: {len(lost)} chunk(s) have no recoverable "
                f"payload in Redis"
            )
            status = job.mark_chunks_abandoned(reason)
            states = self.cache.get_job_chunk_states(job.id)
            job.reconcile_chunk_counters(
                completed=sum(
                    1 for outcome in states.values() if outcome == "completed"
                ),
                failed=sum(1 for outcome in states.values() if outcome == "failed"),
            )
            job.refresh_from_db()
            logger.error(
                f"ImportChunkRecovery: Job #{job.id} abandoned as {status} — {reason}"
            )
            return {
                "status": "abandoned",
                "job_id": job.id,
                "terminal_status": status,
                "lost": lost,
                "newly_lost": newly_lost,
            }

        if newly_lost:
            # Make the loss visible in the counters immediately; the job still
            # cannot finalise while recoverable chunks are outstanding.
            states = self.cache.get_job_chunk_states(job.id)
            job.reconcile_chunk_counters(
                completed=sum(
                    1 for outcome in states.values() if outcome == "completed"
                ),
                failed=sum(1 for outcome in states.values() if outcome == "failed"),
            )
            job.refresh_from_db()

        dispatched_chunk_ids: List[str] = []

        if recoverable and dispatch:
            to_dispatch = recoverable[:CHUNK_REDISPATCH_MAX_PER_JOB]

            # Debounce the next watchdog run: a job that was just handed work
            # is no longer stalled.
            job.touch_progress()

            from core.tasks.tasks_decisions_import import store_decisions_from_redis

            for position, index in enumerate(to_dispatch):
                chunk_id = f"{job.id}_chunk_{index}"
                delay_seconds = min(
                    position * CHUNK_REDISPATCH_STAGGER_SECONDS,
                    CHUNK_REDISPATCH_MAX_DELAY_SECONDS,
                )
                store_decisions_from_redis.delay(
                    chunk_id=chunk_id,
                    job_id=job.id,
                    delay_seconds=delay_seconds,
                )
                dispatched_chunk_ids.append(chunk_id)

            logger.warning(
                f"IMPORT_ALERT ImportChunkRecovery: Job #{job.id} redispatched "
                f"{len(dispatched_chunk_ids)}/{len(recoverable)} surviving chunks "
                f"({len(lost)} lost, {job.chunks_completed + job.chunks_failed}"
                f"/{job.total_chunks} reported)"
            )
            return {
                "status": "redispatched",
                "job_id": job.id,
                "dispatched": dispatched_chunk_ids,
                "remaining": len(recoverable) - len(to_dispatch),
                "lost": lost,
                "newly_lost": newly_lost,
            }

        # Nothing left to dispatch.  Reconcile the counters from the recorded
        # outcomes; if the remaining chunks are still unaccounted for, the job
        # is wedged and must be closed so the queue advances.
        if recoverable and not dispatch:
            return {
                "status": "pending",
                "job_id": job.id,
                "recoverable": recoverable,
                "lost": lost,
                "newly_lost": newly_lost,
            }

        states = self.cache.get_job_chunk_states(job.id)
        completed = sum(1 for outcome in states.values() if outcome == "completed")
        failed = sum(1 for outcome in states.values() if outcome == "failed")
        job.reconcile_chunk_counters(completed=completed, failed=failed)
        job.refresh_from_db()

        if not job.is_complete:
            reason = (
                f"Chunk watchdog: {job.total_chunks - job.chunks_completed - job.chunks_failed} "
                f"chunk(s) have no recoverable payload in Redis"
            )
            status = job.mark_chunks_abandoned(reason)
            logger.error(
                f"ImportChunkRecovery: Job #{job.id} abandoned as {status} — {reason}"
            )
            return {
                "status": "abandoned",
                "job_id": job.id,
                "terminal_status": status,
                "lost": lost,
                "newly_lost": newly_lost,
            }

        logger.warning(
            f"ImportChunkRecovery: Job #{job.id} counters reconciled from "
            f"chunk state ({completed} completed, {failed} failed)"
        )
        return {
            "status": "reconciled",
            "job_id": job.id,
            "completed": completed,
            "failed": failed,
            "newly_lost": newly_lost,
        }
