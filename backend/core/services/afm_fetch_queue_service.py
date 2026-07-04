"""
AFM Fetch Queue Service

Manages a Redis-based priority queue for fetching company data from GEMI.
Uses sorted sets to maintain priority order based on entity importance scores.

Architecture:
- Pending queue: Redis sorted set (score = entity importance)
- Active set: Currently being processed
- Fetched set: Successfully completed
- Failed set: Failed fetches
- Ignored set: Below threshold or excluded

This prevents API quota exhaustion by focusing on high-value entities.
"""

import time
from typing import Any, Dict, Optional

from api.redis_keys import (
    AFM_FETCH_QUEUE_ACTIVE,
    AFM_FETCH_QUEUE_FAILED,
    AFM_FETCH_QUEUE_FETCHED,
    AFM_FETCH_QUEUE_IGNORED,
    AFM_FETCH_QUEUE_LOCK,
    AFM_FETCH_QUEUE_PENDING,
    AFM_FETCH_QUEUE_STATS,
)
from core.models.afm_scoring import AFMEntityScore
from core.models.entities import AFMEntity
from core.services.gemi_service import GemiService
from django.utils import timezone
from django_redis import get_redis_connection
from gemi.exceptions import GemiAPIError, GemiNotFoundError
from loguru import logger


class AFMFetchQueueService:
    """
    Service for managing AFM entity fetch queue.

    Usage:
        queue = AFMFetchQueueService()

        # Populate queue from scored entities
        queue.populate_queue_from_scores(limit=1000)

        # Process batch
        stats = queue.process_batch(batch_size=50)

        # Check status
        status = queue.get_queue_status()
    """

    # Redis keys
    PENDING_KEY = AFM_FETCH_QUEUE_PENDING
    ACTIVE_KEY = AFM_FETCH_QUEUE_ACTIVE
    FETCHED_KEY = AFM_FETCH_QUEUE_FETCHED
    FAILED_KEY = AFM_FETCH_QUEUE_FAILED
    IGNORED_KEY = AFM_FETCH_QUEUE_IGNORED
    LOCK_KEY = AFM_FETCH_QUEUE_LOCK
    STATS_KEY = AFM_FETCH_QUEUE_STATS

    # Lock timeout (prevent stale locks)
    LOCK_TIMEOUT = 600  # 10 minutes

    def __init__(self):
        """Initialize Redis connection."""
        self.redis_client = get_redis_connection("default")

    def populate_queue_from_scores(
        self,
        limit: Optional[int] = None,
        force_refresh: bool = False,
        auto_trigger: bool = True,
        target_count: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Populate Redis queue from AFMEntityScore table.

        Entities are added to sorted set with their score as the sort key.
        Higher scores = higher priority = processed first.

        Args:
            limit: Maximum number of entities to examine from the top of the ranking.
                   Some of those may be skipped (already processed/queued), so the
                   actual number added can be lower.  Use `target_count` when you
                   need an exact number of *new* additions.
            force_refresh: Clear existing queue before populating
            auto_trigger: If True, automatically trigger processing task after adding items
            target_count: When set, paginate through the ranked list until exactly this
                          many *new* entities have been added (ignoring already-processed
                          ones).  Overrides `limit`.  Use this for the virtuous-cycle
                          batch trigger so gaps in the processed set are not mistaken
                          for "nothing left to do".

        Returns:
            Statistics about queue population
        """
        logger.info("Populating AFM fetch queue from scores")

        if force_refresh:
            self.clear_queue()

        # Base queryset — eligible entities ordered by score (highest first)
        base_queryset = (
            AFMEntityScore.objects.filter(is_eligible=True)
            .select_related("entity")
            .order_by("-total_score")
        )

        added = 0
        skipped_already_queued = 0
        skipped_already_processed = 0

        if target_count is not None:
            # Paginate through the ranked list until we have added exactly
            # target_count new entries.  This correctly skips over already-
            # processed entities without stopping early.
            page_size = max(target_count * 10, 100)
            offset = 0

            while added < target_count:
                page = list(base_queryset[offset : offset + page_size])
                if not page:
                    break  # Exhausted all eligible entities

                for score in page:
                    afm = score.entity.afm

                    if self._is_processed(afm):
                        skipped_already_processed += 1
                        continue

                    if self.redis_client.zscore(self.PENDING_KEY, afm) is not None:
                        skipped_already_queued += 1
                        continue

                    self.redis_client.zadd(
                        self.PENDING_KEY, {afm: float(score.total_score)}
                    )
                    added += 1

                    if added >= target_count:
                        break

                offset += page_size
        else:
            # Original behaviour: examine the top `limit` records (or all if None)
            queryset = base_queryset
            if limit:
                queryset = queryset[:limit]

            for score in queryset:
                afm = score.entity.afm

                if self._is_processed(afm):
                    skipped_already_processed += 1
                    continue

                if self.redis_client.zscore(self.PENDING_KEY, afm) is not None:
                    skipped_already_queued += 1
                    continue

                self.redis_client.zadd(
                    self.PENDING_KEY,
                    {afm: float(score.total_score)},
                )
                added += 1

        stats = {
            "added": added,
            "skipped_already_queued": skipped_already_queued,
            "skipped_already_processed": skipped_already_processed,
            "total_pending": self.get_pending_count(),
        }

        # Update stats hash
        self._update_stats(queue_populated_at=timezone.now().isoformat())

        logger.bind(**stats).info(f"Queue population completed")

        # Auto-trigger processing if items were added
        if auto_trigger and added > 0:
            try:
                from core.tasks.tasks_entities import process_afm_fetch_queue

                task = process_afm_fetch_queue.delay()
                logger.info(f"Auto-triggered queue processing task: {task.id}")
                stats["processing_task_id"] = task.id
            except Exception as e:
                logger.error(f"Failed to auto-trigger queue processing: {e}")
                stats["auto_trigger_error"] = str(e)

        return stats

    def process_batch(
        self, batch_size: int = 50, max_requests_per_minute: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Process a batch of AFMs from the queue.

        Respects GEMI rate limits and processes entities in priority order.

        Args:
            batch_size: Number of AFMs to process in this batch
            max_requests_per_minute: Override default rate limit (uses GemiService.MAX_REQUESTS_PER_MINUTE if None)

        Returns:
            Processing statistics
        """
        rate_limit = max_requests_per_minute or GemiService.MAX_REQUESTS_PER_MINUTE

        # Try to acquire global lock
        lock_acquired = self.redis_client.set(
            self.LOCK_KEY, "processing", nx=True, ex=self.LOCK_TIMEOUT
        )

        if not lock_acquired:
            logger.warning("AFM fetch queue is already being processed")
            return {
                "status": "locked",
                "message": "Queue is being processed by another worker",
            }

        try:
            logger.info(
                f"Starting batch processing: {batch_size} AFMs, rate limit: {rate_limit}/min"
            )

            stats = {
                "processed": 0,
                "successful": 0,
                "failed": 0,
                "not_found": 0,
                "errors": [],
            }

            start_time = time.time()

            # Get top batch_size AFMs from pending queue
            # ZPOPMAX returns items in descending order (highest score first)
            batch_afms = []
            for _ in range(batch_size):
                result = self.redis_client.zpopmax(self.PENDING_KEY, 1)
                if not result:
                    break  # Queue empty
                afm, score = result[0]
                if isinstance(afm, bytes):
                    afm = afm.decode("utf-8")
                batch_afms.append(afm)

            if not batch_afms:
                logger.info("No AFMs in pending queue")
                return {"status": "empty_queue"}

            logger.info(f"Processing {len(batch_afms)} AFMs from queue")

            for afm in batch_afms:
                # Mark as active
                self.redis_client.sadd(self.ACTIVE_KEY, afm)

                try:
                    # Fetch from GEMI (includes rate limiting)
                    companies = GemiService.fetch_companies_by_afm(
                        afm=afm,
                        update_entity=True,
                        max_requests_per_minute=rate_limit,
                        force_refresh=False,
                    )

                    # Move to fetched set
                    self.redis_client.srem(self.ACTIVE_KEY, afm)
                    self.redis_client.sadd(self.FETCHED_KEY, afm)

                    stats["successful"] += 1
                    logger.info(
                        f"Successfully fetched {len(companies)} companies for {afm}"
                    )

                except GemiNotFoundError:
                    # Not found is not an error - just no data available
                    self.redis_client.srem(self.ACTIVE_KEY, afm)
                    self.redis_client.sadd(self.FETCHED_KEY, afm)  # Mark as processed
                    stats["not_found"] += 1
                    logger.info(f"No company data found for {afm}")

                except GemiAPIError as e:
                    # API error - move to failed set
                    self.redis_client.srem(self.ACTIVE_KEY, afm)
                    self.redis_client.sadd(self.FAILED_KEY, afm)
                    stats["failed"] += 1
                    stats["errors"].append({"afm": afm, "error": str(e)})
                    logger.error(f"GEMI API error for {afm}: {e}")

                except Exception as e:
                    # Unexpected error - move to failed set
                    self.redis_client.srem(self.ACTIVE_KEY, afm)
                    self.redis_client.sadd(self.FAILED_KEY, afm)
                    stats["failed"] += 1
                    stats["errors"].append({"afm": afm, "error": str(e)})
                    logger.error(f"Unexpected error processing {afm}: {e}")

                stats["processed"] += 1

            elapsed = time.time() - start_time
            stats["elapsed_seconds"] = round(elapsed, 2)
            stats["afms_per_second"] = (
                round(stats["processed"] / elapsed, 2) if elapsed > 0 else 0
            )

            # Update stats hash
            self._update_stats(
                last_batch_at=timezone.now().isoformat(),
                last_batch_size=stats["processed"],
                last_batch_successful=stats["successful"],
                last_batch_failed=stats["failed"],
            )

            logger.bind(**stats).info(f"Batch processing completed")
            return stats

        finally:
            # Always release lock
            self.redis_client.delete(self.LOCK_KEY)

    def get_queue_status(self) -> Dict[str, Any]:
        """
        Get current queue status and statistics.

        Returns comprehensive metrics for monitoring dashboard.
        """
        pending_count = self.redis_client.zcard(self.PENDING_KEY)
        active_count = self.redis_client.scard(self.ACTIVE_KEY)
        fetched_count = self.redis_client.scard(self.FETCHED_KEY)
        failed_count = self.redis_client.scard(self.FAILED_KEY)
        ignored_count = self.redis_client.scard(self.IGNORED_KEY)

        # Get top 10 pending AFMs
        top_pending = []
        pending_afms = self.redis_client.zrevrange(
            self.PENDING_KEY, 0, 9, withscores=True
        )
        for afm, score in pending_afms:
            if isinstance(afm, bytes):
                afm = afm.decode("utf-8")
            # score is the total_score value
            top_pending.append({"afm": afm, "score": float(score)})

        # Get recent stats
        stats_hash = self.redis_client.hgetall(self.STATS_KEY)
        recent_stats = {
            k.decode("utf-8") if isinstance(k, bytes) else k: (
                v.decode("utf-8") if isinstance(v, bytes) else v
            )
            for k, v in stats_hash.items()
        }

        # Check if queue is locked
        is_locked = self.redis_client.exists(self.LOCK_KEY)

        return {
            "pending": pending_count,
            "active": active_count,
            "fetched": fetched_count,
            "failed": failed_count,
            "ignored": ignored_count,
            "total_processed": fetched_count + failed_count,
            "success_rate": (
                round(fetched_count / (fetched_count + failed_count) * 100, 2)
                if (fetched_count + failed_count) > 0
                else 0
            ),
            "top_pending": top_pending,
            "is_locked": bool(is_locked),
            "recent_stats": recent_stats,
        }

    def get_pending_count(self) -> int:
        """Get count of pending AFMs."""
        return self.redis_client.zcard(self.PENDING_KEY)

    def clear_queue(self, keep_stats: bool = True):
        """
        Clear all queue data.

        Args:
            keep_stats: If True, preserve stats hash
        """
        logger.warning("Clearing AFM fetch queue")

        self.redis_client.delete(self.PENDING_KEY)
        self.redis_client.delete(self.ACTIVE_KEY)
        self.redis_client.delete(self.FETCHED_KEY)
        self.redis_client.delete(self.FAILED_KEY)
        self.redis_client.delete(self.IGNORED_KEY)

        if not keep_stats:
            self.redis_client.delete(self.STATS_KEY)

    def retry_failed(self, limit: Optional[int] = None) -> Dict[str, Any]:
        """
        Move failed AFMs back to pending queue for retry.

        Args:
            limit: Maximum number to retry (None = all)

        Returns:
            Statistics about retry operation
        """
        failed_afms = self.redis_client.smembers(self.FAILED_KEY)

        if limit:
            failed_afms = list(failed_afms)[:limit]

        retried = 0
        for afm in failed_afms:
            if isinstance(afm, bytes):
                afm = afm.decode("utf-8")

            # Get entity score to restore priority
            try:
                entity = AFMEntity.objects.get(afm=afm)
                score = AFMEntityScore.objects.get(entity=entity)

                # Add back to pending with original score
                self.redis_client.zadd(
                    self.PENDING_KEY, {afm: float(score.total_score)}
                )

                # Remove from failed
                self.redis_client.srem(self.FAILED_KEY, afm)
                retried += 1

            except (AFMEntity.DoesNotExist, AFMEntityScore.DoesNotExist):
                logger.warning(f"Cannot retry {afm}: entity or score not found")
                continue

        logger.info(f"Retried {retried} failed AFMs")
        return {"retried": retried}

    def recover_stuck_active(self) -> Dict[str, Any]:
        """
        Recover AFMs stuck in ACTIVE set (processing never completed).

        This can happen if:
        - Worker crashes during processing
        - Task times out
        - Network issues cause hanging

        Moves stuck items back to PENDING queue for retry.

        Returns:
            Statistics about recovery operation
        """
        active_afms = self.redis_client.smembers(self.ACTIVE_KEY)

        if not active_afms:
            logger.info("No stuck items in ACTIVE set")
            return {"recovered": 0}

        recovered = 0
        for afm in active_afms:
            if isinstance(afm, bytes):
                afm = afm.decode("utf-8")

            # Get entity score to restore priority
            try:
                entity = AFMEntity.objects.get(afm=afm)
                score = AFMEntityScore.objects.get(entity=entity)

                # Add back to pending with original score
                self.redis_client.zadd(
                    self.PENDING_KEY, {afm: float(score.total_score)}
                )

                # Remove from active
                self.redis_client.srem(self.ACTIVE_KEY, afm)
                recovered += 1

            except (AFMEntity.DoesNotExist, AFMEntityScore.DoesNotExist):
                # No score found, use default priority
                self.redis_client.zadd(self.PENDING_KEY, {afm: 1.0})
                self.redis_client.srem(self.ACTIVE_KEY, afm)
                recovered += 1
                logger.warning(
                    f"Recovered {afm} with default priority (no score found)"
                )

        logger.warning(f"Recovered {recovered} stuck AFMs from ACTIVE set")
        return {"recovered": recovered}

    def _is_processed(self, afm: str) -> bool:
        """Check if AFM is in any processed set (fetched/failed/ignored)."""
        return (
            self.redis_client.sismember(self.FETCHED_KEY, afm)
            or self.redis_client.sismember(self.FAILED_KEY, afm)
            or self.redis_client.sismember(self.IGNORED_KEY, afm)
        )

    def _update_stats(self, **kwargs):
        """Update statistics hash in Redis."""
        if kwargs:
            self.redis_client.hset(self.STATS_KEY, mapping=kwargs)

    def add_single_afm(
        self,
        afm: str,
        priority_score: Optional[float] = None,
        jump_queue: bool = False,
        auto_trigger: bool = True,
    ) -> bool:
        """
        Manually add a single AFM to the queue.

        Args:
            afm: AFM to add
            priority_score: Optional score value (defaults to entity's total_score)
            jump_queue: If True, assign maximum score to process first
            auto_trigger: If True, automatically trigger processing task after adding

        Returns:
            True if added, False if already queued/processed
        """
        # Check if already processed
        if self._is_processed(afm):
            logger.info(f"AFM {afm} already processed, not adding to queue")
            return False

        # Check if already pending
        if self.redis_client.zscore(self.PENDING_KEY, afm) is not None:
            logger.info(f"AFM {afm} already in pending queue")
            return False

        # Determine priority score
        if jump_queue:
            # Use a very high score to ensure it's processed first
            priority_score = 999999.0
        elif priority_score is None:
            try:
                entity = AFMEntity.objects.get(afm=afm)
                score = AFMEntityScore.objects.get(entity=entity)
                priority_score = float(score.total_score)
            except (AFMEntity.DoesNotExist, AFMEntityScore.DoesNotExist):
                logger.warning(f"No score for {afm}, using default priority")
                priority_score = 1.0  # Low priority

        # Add to queue
        self.redis_client.zadd(self.PENDING_KEY, {afm: priority_score})

        logger.info(
            f"Added {afm} to queue with score {priority_score}"
            + (" (PRIORITY JUMP)" if jump_queue else "")
        )

        # Auto-trigger processing if requested
        if auto_trigger:
            try:
                from core.tasks.tasks_entities import process_afm_fetch_queue

                task = process_afm_fetch_queue.delay()
                logger.info(f"Auto-triggered queue processing task: {task.id}")
            except Exception as e:
                logger.error(f"Failed to auto-trigger queue processing: {e}")

        return True
