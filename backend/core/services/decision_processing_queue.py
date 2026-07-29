"""
Decision AI Processing Queue — concurrency-controlled queue for user-triggered
decision extraction and AI summarization.

Pattern matches ``ImportJobQueue`` and ``AFMFetchQueueService``: Redis-backed
distributed queue with concurrency limiting and deduplication.

Two processing types are tracked separately so a decision can have text
extracted without being summarised, or summarised only when extraction is
already done.

Usage:
    queue = DecisionProcessingQueue()

    # API layer: enqueue + dispatch if capacity
    result = queue.enqueue(decision_id=42, process_type="extract")
    result = queue.enqueue(decision_id=42, process_type="summarize")

    # Celery consumer: process batch
    stats = queue.process_batch()

    # After a task completes:
    queue.on_completed(decision_id=42, process_type="extract")
"""

from typing import Any, Dict, List, Optional, Tuple

from api.redis_keys import (
    DECISION_AI_QUEUE_ACTIVE,
    DECISION_AI_QUEUE_COMPLETED,
    DECISION_AI_QUEUE_FAILED,
    DECISION_AI_QUEUE_LOCK,
    DECISION_AI_QUEUE_MAX_CONCURRENT,
    DECISION_AI_QUEUE_PENDING,
    DECISION_AI_QUEUE_STATS,
)
from django.utils import timezone
from django_redis import get_redis_connection
from loguru import logger


class DecisionProcessingQueue:
    """
    Concurrency-controlled queue for decision AI processing.

    Each decision can be in one of: pending, active, completed, failed.
    A global lock prevents multiple consumer tasks from racing.
    """

    PENDING_KEY = DECISION_AI_QUEUE_PENDING
    ACTIVE_KEY = DECISION_AI_QUEUE_ACTIVE
    COMPLETED_KEY = DECISION_AI_QUEUE_COMPLETED
    FAILED_KEY = DECISION_AI_QUEUE_FAILED
    LOCK_KEY = DECISION_AI_QUEUE_LOCK
    STATS_KEY = DECISION_AI_QUEUE_STATS

    MAX_CONCURRENT = DECISION_AI_QUEUE_MAX_CONCURRENT
    LOCK_TIMEOUT = 600  # 10 minutes

    def __init__(self):
        self.redis = get_redis_connection("default")

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------

    def enqueue(self, decision_id: int, force: bool = False) -> Dict[str, Any]:
        """
        Add a decision to the pending set.  Idempotent — returns existing
        status if the decision is already queued/active/completed.

        With ``force=True``, a completed or failed entry is reset so the
        decision can be re-processed (regeneration).

        Returns:
            ``{"decision_id": int, "status": "enqueued"|"already_pending"|"already_active"|"already_completed"}``
        """
        did = str(decision_id)

        if self.redis.sismember(self.ACTIVE_KEY, did):
            logger.debug(f"Decision {decision_id}: already active")
            return {"decision_id": decision_id, "status": "already_active"}
        if self.redis.sismember(self.PENDING_KEY, did):
            logger.debug(f"Decision {decision_id}: already pending")
            return {"decision_id": decision_id, "status": "already_pending"}
        if self.redis.sismember(self.COMPLETED_KEY, did):
            if not force:
                logger.debug(f"Decision {decision_id}: already completed, skipping")
                return {"decision_id": decision_id, "status": "already_completed"}
            # Regeneration: remove from completed so it can be re-queued
            self.redis.srem(self.COMPLETED_KEY, did)
            logger.info(f"Decision {decision_id}: removed from completed (force re-queue)")

        # Remove from failed (retry)
        self.redis.srem(self.FAILED_KEY, did)

        self.redis.sadd(self.PENDING_KEY, did)
        self._update_stats(last_enqueue_at=timezone.now().isoformat())

        pending = self.redis.scard(self.PENDING_KEY)
        logger.info(f"Decision {decision_id}: enqueued (pending={pending})")
        return {"decision_id": decision_id, "status": "enqueued"}

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def can_dispatch(self) -> bool:
        """Check if there is capacity to start a new job."""
        active = self.redis.scard(self.ACTIVE_KEY)
        return active < self.MAX_CONCURRENT

    def dispatch_next(self) -> Optional[int]:
        """
        Pop the next pending decision and move it to active.

        Returns the decision ID, or ``None`` if the queue is empty or at capacity.
        """
        if not self.can_dispatch():
            return None

        if not self.redis.exists(self.PENDING_KEY):
            return None

        did = self.redis.spop(self.PENDING_KEY)
        if not did:
            return None

        if isinstance(did, bytes):
            did = did.decode("utf-8")

        self.redis.sadd(self.ACTIVE_KEY, did)
        logger.info(f"Decision {did}: dispatched (active={self.redis.scard(self.ACTIVE_KEY)})")
        return int(did)

    def dispatch_batch(self, max_count: int = None) -> List[int]:
        """
        Dispatch up to *max_count* decisions (capped by capacity).

        Returns list of dispatched decision IDs.
        """
        available = self.MAX_CONCURRENT - self.redis.scard(self.ACTIVE_KEY)
        if available <= 0:
            return []

        count = min(available, max_count or available)
        dispatched = []
        for _ in range(count):
            did = self.dispatch_next()
            if did is None:
                break
            dispatched.append(did)

        if dispatched:
            logger.info(f"Dispatched {len(dispatched)}: {dispatched}")
        return dispatched

    # ------------------------------------------------------------------
    # Completion
    # ------------------------------------------------------------------

    def on_completed(self, decision_id: int):
        """Move a decision from active to completed."""
        did = str(decision_id)
        self.redis.srem(self.ACTIVE_KEY, did)
        self.redis.sadd(self.COMPLETED_KEY, did)
        self._update_stats(last_completed_at=timezone.now().isoformat())

    def on_failed(self, decision_id: int, error: str = ""):
        """Move a decision from active to failed."""
        did = str(decision_id)
        self.redis.srem(self.ACTIVE_KEY, did)
        self.redis.sadd(self.FAILED_KEY, did)
        if error:
            self.redis.hset(self.STATS_KEY, f"error:{did}", error[:300])

    # ------------------------------------------------------------------
    # Process batch (called by consumer Celery task)
    # ------------------------------------------------------------------

    def process_batch(self) -> Dict[str, Any]:
        """
        Consumer entry point: dispatch the next batch as async Celery tasks.

        Acquires a global lock so only one consumer dispatches at a time.
        The dispatched tasks themselves call ``on_completed``/``on_failed``
        when they finish (see ``process_decision_ai``).
        Returns stats dict for logging.
        """
        lock_ok = self.redis.set(self.LOCK_KEY, "1", nx=True, ex=self.LOCK_TIMEOUT)
        if not lock_ok:
            return {"status": "locked"}

        try:
            dispatched = self.dispatch_batch()
            if not dispatched:
                return {"status": "empty", "pending": self.redis.scard(self.PENDING_KEY)}

            from core.tasks.tasks_decision_ai import process_decision_ai

            for did in dispatched:
                process_decision_ai.delay(did)

            self._update_stats(
                last_batch_at=timezone.now().isoformat(),
                last_batch_size=len(dispatched),
            )

            logger.info(f"Decision AI queue: dispatched {len(dispatched)} async tasks: {dispatched}")
            return {"status": "dispatched", "dispatched": dispatched}
        finally:
            self.redis.delete(self.LOCK_KEY)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Current queue snapshot."""
        return {
            "pending": self.redis.scard(self.PENDING_KEY),
            "active": self.redis.scard(self.ACTIVE_KEY),
            "completed": self.redis.scard(self.COMPLETED_KEY),
            "failed": self.redis.scard(self.FAILED_KEY),
            "max_concurrent": self.MAX_CONCURRENT,
            "can_dispatch": self.can_dispatch(),
        }

    def get_decision_status(self, decision_id: int) -> str:
        """Return the queue state for a single decision."""
        did = str(decision_id)
        if self.redis.sismember(self.ACTIVE_KEY, did):
            return "active"
        if self.redis.sismember(self.PENDING_KEY, did):
            return "pending"
        if self.redis.sismember(self.COMPLETED_KEY, did):
            return "completed"
        if self.redis.sismember(self.FAILED_KEY, did):
            return "failed"
        return "unknown"

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_completed(self) -> int:
        """Clear the completed set (they're already persisted in the DB)."""
        count = self.redis.scard(self.COMPLETED_KEY)
        if count:
            self.redis.delete(self.COMPLETED_KEY)
            logger.info(f"Decision AI queue: cleared {count} completed entries")
        return count

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _update_stats(self, **kwargs):
        if kwargs:
            self.redis.hset(self.STATS_KEY, mapping=kwargs)
